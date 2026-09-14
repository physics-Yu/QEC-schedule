"""Restricted single-event temporal recovery for two rotated d=3 patches.

Three potentially noisy extraction rounds are followed by one perfect closing
round. Recovery reads only the reported 64-bit history and a fixed support
table; neither the injected fault nor quantum truth is an input to decoding.
"""
from collections import Counter
from functools import lru_cache
import json
from random import Random
from types import MappingProxyType

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.quantum.stabilizer import StabilizerState
from .surface_qec import (QUBIT_IDS,DATA_IDS,X_CHECKS,Z_CHECKS,LOGICAL_X,LOGICAL_Z,
    data,ancilla,atom_roles,correction_table,_Builder,_syndrome,_corrections,
    optimize_h_pairs,reduce_dependencies)


NOISY_ROUNDS=('round1','round2','round3')
ROUNDS=NOISY_ROUNDS+('closing',)
ALL_ROUNDS=('prepare',)+ROUNDS
HISTORY_IDS=tuple(f'{r}_{kind}{block}_{i}' for r in ROUNDS for kind in ('X','Z') for block in range(2) for i in range(4))
MEASUREMENT_IDS=tuple(f'{r}_{kind}{block}_{i}' for r in ALL_ROUNDS for kind in ('X','Z') for block in range(2) for i in range(4))
CORRECTION_PREFIX='TEMP_CORR_'
FAULT_GATE_ID='TEMPORAL_FAULT'


def normalize_fault(fault):
    if fault is None:return None
    if not isinstance(fault,dict) or fault.get('kind') not in {'data','readout'}:
        raise ValueError('Temporal fault must have kind=data or kind=readout')
    if type(fault.get('round')) is not int or fault['round'] not in (1,2,3):
        raise ValueError('A single fault is allowed only in noisy round 1, 2 or 3')
    if fault['kind']=='data':
        if set(fault)!={'kind','round','pauli','qubit_id'} or fault['pauli'] not in {'X','Y','Z'} or fault['qubit_id'] not in DATA_IDS:
            raise ValueError('Data fault requires X/Y/Z on one of 18 data atoms')
    elif (set(fault)!={'kind','round','patch','check_type','check_index'} or
          type(fault['patch']) is not int or fault['patch'] not in (0,1) or
          fault['check_type'] not in {'X','Z'} or type(fault['check_index']) is not int or fault['check_index'] not in range(4)):
        raise ValueError('Readout fault requires patch 0/1, check_type X/Z, check_index 0..3')
    return dict(fault)


def supported_faults():
    """The fixed 211 advertised cases, independent of the selected example."""
    return (None,)+tuple({'kind':'data','round':r,'pauli':p,'qubit_id':q}
        for r in (1,2,3) for p in ('X','Y','Z') for q in DATA_IDS)+tuple(
        {'kind':'readout','round':r,'patch':b,'check_type':k,'check_index':i}
        for r in (1,2,3) for b in range(2) for k in ('X','Z') for i in range(4))


def _model_history(fault):
    """Analytic table construction from Pauli/check anticommutation."""
    bits=dict.fromkeys(HISTORY_IDS,0)
    if fault is None:return tuple(bits.values())
    if fault['kind']=='readout':
        bits[f"round{fault['round']}_{fault['check_type']}{fault['patch']}_{fault['check_index']}"]=1
    else:
        index=DATA_IDS.index(fault['qubit_id']);block,local=divmod(index,9)
        for number,r in enumerate(ROUNDS,1):
            if number<fault['round']:continue
            for kind,checks in (('X',X_CHECKS),('Z',Z_CHECKS)):
                for i,check in enumerate(checks):bits[f'{r}_{kind}{block}_{i}']=int(local in check and fault['pauli']!=kind)
    return tuple(bits.values())


@lru_cache(maxsize=1)
def supported_histories():
    return frozenset(_model_history(fault) for fault in supported_faults())


def _css_ids(block,kind):return tuple(f'{r}_{kind}{block}_{i}' for r in ROUNDS for i in range(4))


@lru_cache(maxsize=None)
def css_history_table(block,kind):
    """Sparse 16-bit histories, including supported no-correction histories."""
    indices=tuple(HISTORY_IDS.index(g) for g in _css_ids(block,kind))
    result={};corrections=correction_table(kind)
    for full in sorted(supported_histories()):
        history=tuple(full[i] for i in indices)
        result[history]=corrections[history[-4:]]
    return MappingProxyType(result)


def validate_history(readout_bits):
    missing=[g for g in HISTORY_IDS if g not in readout_bits]
    if missing:
        raise ValidationError('INCOMPLETE_SYNDROME_HISTORY',f'Temporal recovery needs all 64 reported history bits; missing {len(missing)}')
    history=tuple(readout_bits[g] for g in HISTORY_IDS)
    if any(type(bit) is not int or bit not in (0,1) for bit in history):
        raise ValidationError('INVALID_SYNDROME_HISTORY','Temporal reported history values must be integer bits')
    if history not in supported_histories():
        raise ValidationError('UNSUPPORTED_SYNDROME_HISTORY','Reported history is outside the fixed single-event temporal model')
    corrections=[]
    for block in range(2):
        for kind in ('X','Z'):
            local=tuple(readout_bits[g] for g in _css_ids(block,kind))
            corrections.extend({'gate_type':'Z' if kind=='X' else 'X','qubit_ids':[data(block,q)]}
                               for q in css_history_table(block,kind)[local])
    return {'supported':True,'history_bits':history,'corrections':corrections}


def decode(readout_bits):return validate_history(readout_bits)['corrections']


def _temporal_corrections(builder):
    builder.start('temporal-correction')
    for block in range(2):
        for kind in ('X','Z'):
            ids=_css_ids(block,kind)
            for bits,locals_ in sorted(css_history_table(block,kind).items()):
                pattern=sum(bit<<i for i,bit in enumerate(bits))
                for q in locals_:
                    builder.add('Z' if kind=='X' else 'X',(data(block,q),),
                        gate_id=f'{CORRECTION_PREFIX}{kind}{block}_{pattern:04x}_{q}',condition=tuple(zip(ids,bits)))


def protocol(fault=None,*,optimize=True,reduce_edges=True):
    fault=normalize_fault(fault);builder=_Builder()
    builder.start('initial-product-state')
    for q in range(9):builder.add('H',(data(0,q),))
    _syndrome(builder,'prepare');_corrections(builder,'prepare')
    builder.start('logical-cnot');builder.cnot_layer([(data(0,q),data(1,q)) for q in range(9)])
    boundaries=[]
    for number,r in enumerate(ROUNDS,1):
        # _Builder.start installs a full previous-stage exit barrier. A data
        # fault, when present, follows all previous work and precedes the
        # entire extraction round, including gates on unrelated atoms.
        builder.start(f'{r}-boundary')
        selected=fault is not None and fault['kind']=='data' and fault['round']==number
        boundaries.append({'round':r,'index':number,'column':builder.cursor,
                           'fault_gate_id':FAULT_GATE_ID if selected else None})
        if selected:builder.add(fault['pauli'],(fault['qubit_id'],),gate_id=FAULT_GATE_ID)
        elif r in NOISY_ROUNDS:builder.cursor+=1
        _syndrome(builder,r)
    flip_id=None
    if fault is not None and fault['kind']=='readout':
        flip_id=f"round{fault['round']}_{fault['check_type']}{fault['patch']}_{fault['check_index']}"
        next(g for g in builder.gates if g['id']==flip_id)['readout_flip']=True
    _temporal_corrections(builder)
    gates=optimize_h_pairs(builder.gates) if optimize else builder.gates
    original_edges=sum(len(g.get('depends_on',())) for g in gates)
    if reduce_edges:gates=reduce_dependencies(gates)
    kept={g['id'] for g in gates}
    return {'gates':gates,'readouts':builder.readouts,
        'stages':[s for s in builder.stages if s['gate_id'] in kept],
        'atom_roles':atom_roles(),'noisy_rounds':list(NOISY_ROUNDS),'closing_round':'closing',
        'round_boundaries':boundaries,'history_ids':list(HISTORY_IDS),'correction_prefix':CORRECTION_PREFIX,'noise_event':fault,
        'fault_gate_id':FAULT_GATE_ID,'fault_measurement_id':flip_id,'fault_targets':list(DATA_IDS),
        'supported_event_count':len(supported_faults()),'supported_unique_histories':len(supported_histories()),
        'optimization':{'raw_gate_slots':len(builder.gates),'optimized_gate_slots':len(gates),
                        'cancelled_H_pairs':(len(builder.gates)-len(gates))//2},
        'dependency_reduction':{'before':original_edges,'after':sum(len(g.get('depends_on',())) for g in gates)},
        'scope':'one pre-round data Pauli or one noisy-round reported readout flip; perfect physical closing round'}


def experiment_input(fault=None,compiler='qec_temporal'):
    definition=protocol(fault)
    return {'compiler':compiler,'atom_count':34,'layout':'surface_qec_ghz2','seed':0,'qec_enabled':True,
        'ez_policy':'adaptive','aod_traps':98,'aod_rows':7,'aod_columns':14,
        'aod_row_offsets_um':list(range(0,31,5)),
        'aod_column_offsets_um':list(range(0,31,5))+list(range(40,71,5)),
        'ez_neighbor_guard_enabled':False,'gates':definition['gates'],'compile_timeout_s':3600,
        'qec_protocol':{k:v for k,v in definition.items() if k!='gates'}}


def _protocol_complete(gates,executed):
    expected={f'{r}_{kind}{block}_{i}':(ancilla(block,kind,i),block,kind,i)
              for r in ALL_ROUNDS for kind in ('X','Z') for block in range(2) for i in range(4)}
    ancillas=set(QUBIT_IDS[18:]);wires={q:[] for q in ancillas};pending=set();measured=[]
    for gid in executed:
        gate=gates[gid];kind=gate['gate_type']
        for q in ancillas.intersection(gate['qubit_ids']):
            if q in pending and kind!='RESET':return False
            if kind=='RESET':wires[q]=[];pending.discard(q)
            elif kind=='MEASURE':
                if gid not in expected or expected[gid][0]!=q:return False
                _,block,check_kind,i=expected[gid];checks=X_CHECKS if check_kind=='X' else Z_CHECKS
                sequence=wires[q]
                if [g['gate_type'] for g in sequence]!=['H']+['CZ']*len(checks[i])+['H']:return False
                partners=[other for g in sequence if g['gate_type']=='CZ' for other in g['qubit_ids'] if other!=q]
                if sorted(partners)!=sorted(data(block,local) for local in checks[i]):return False
                pending.add(q);measured.append(gid)
            elif kind=='H' and wires[q] and wires[q][-1]['gate_type']=='H':wires[q].pop()
            else:wires[q].append(gate)
    return not pending and Counter(measured)==Counter(expected.keys())


def _summary(quantum,bits,true_bits,applied,gates,executed):
    complete=all(g in bits for g in HISTORY_IDS)
    supported=False;decoded=[];history_error=None
    if complete:
        try:
            decoded=decode(bits);supported=True
        except ValidationError as error:history_error=error.violation.code
    checks={f'{kind}{block}_{i}':quantum.expectation({data(block,q):kind for q in check})
            for block in range(2) for kind,group in (('X',X_CHECKS),('Z',Z_CHECKS)) for i,check in enumerate(group)}
    xx=quantum.expectation({data(b,q):'X' for b in range(2) for q in LOGICAL_X})
    zz=quantum.expectation({data(b,q):'Z' for b in range(2) for q in LOGICAL_Z})
    return {'code':'two rotated [[9,1,3]] patches with temporal syndrome recovery','data_qubits':18,'ancilla_qubits':16,
        'syndrome_bits':dict(bits),'reported_measurement_results':dict(bits),'true_measurement_results':dict(true_bits),
        'history_complete':complete,'history_supported':supported,'history_error':history_error,'decoded_corrections':decoded,
        'corrections':list(applied),'syndrome_rounds_complete':{r:all(f'{r}_{k}{b}_{i}' in bits for k in ('X','Z')
            for b in range(2) for i in range(4)) for r in ALL_ROUNDS},
        'measurement_protocol_complete':_protocol_complete(gates,executed),
        'stabilizer_expectations':checks,'logical_xx':xx,'logical_zz':zz,
        'verified_logical_ghz2':all(v==1 for v in checks.values()) and xx==zz==1,
        'supported_event_count':211,'supported_unique_histories':len(supported_histories()),
        'scope':'three noisy rounds plus one physically executed perfect closing round; at most one declared event',
        'fault_tolerant_circuit_noise_claim':False}


def simulate_ideal(gates=None,*,seed=0,fault=None):
    gates=protocol(fault)['gates'] if gates is None else gates
    quantum=StabilizerState.zero(QUBIT_IDS);rng=Random(seed);bits={};true_bits={};applied=[];executed=[]
    checked=False
    for gate in sorted(gates,key=lambda g:(g['column'],g['id'])):
        if gate['id'].startswith(CORRECTION_PREFIX) and not checked:validate_history(bits);checked=True
        if gate.get('condition') and not all(bits[ref]==bit for ref,bit in gate['condition']):continue
        executed.append(gate['id']);kind=gate['gate_type'];qs=gate['qubit_ids']
        if kind=='MEASURE':
            quantum,outcome=quantum.measure_z(qs[0],rng.getrandbits(1));true_bits[gate['id']]=outcome
            bits[gate['id']]=outcome ^ int(gate.get('readout_flip',False))
        elif kind=='RESET':quantum,_=quantum.reset_zero(qs[0],rng.getrandbits(1))
        else:
            quantum=quantum.apply_gate(kind,qs,gate.get('parameters',()))
            if gate.get('condition'):applied.append({'gate_id':gate['id'],'gate_type':kind,'qubit_ids':list(qs)})
    return quantum,_summary(quantum,bits,true_bits,applied,{g['id']:g for g in gates},executed)


def summarize(state):
    if state.quantum_state is None:raise ValueError('Quantum tracking is not enabled')
    gates={gid:{'id':gid,'gate_type':n.gate.gate_type,'qubit_ids':list(n.gate.qubit_ids),'condition':n.gate.condition}
           for gid,n in state.dag.nodes.items()}
    executed=[];applied=[];true_bits={}
    for raw in state.trace.records:
        record=json.loads(raw)
        if not record.get('effect_completed'):continue
        true_bits.update(record.get('measurement_true_results',record.get('measurement_results',{})))
        for gid in record.get('applied_gate_ids',()):
            executed.append(gid);gate=gates[gid]
            if gate['condition']:applied.append({'gate_id':gid,'gate_type':gate['gate_type'],'qubit_ids':gate['qubit_ids']})
    return _summary(state.quantum_state,state.measurement_results,true_bits,applied,gates,executed)

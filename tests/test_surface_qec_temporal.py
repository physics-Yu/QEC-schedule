"""Temporal single-event recovery checked against independent Pauli algebra."""
from collections import Counter
from copy import deepcopy
import pytest

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_experiments.surface_qec_temporal import DATA_IDS, QUBIT_IDS, ROUNDS, HISTORY_IDS, CORRECTION_PREFIX, FAULT_GATE_ID, X_CHECKS, Z_CHECKS, protocol, experiment_input, supported_faults, supported_histories, simulate_ideal, decode, validate_history, normalize_fault, css_history_table


CASES=tuple(enumerate(supported_faults()))


def independent_history(fault):
    """Symplectic commutator, independent of the decoder/support generator."""
    physical={};reported={}
    for t,r in enumerate(ROUNDS,1):
        for block in (0,1):
            for check_kind,checks in (('X',X_CHECKS),('Z',Z_CHECKS)):
                for i,check in enumerate(checks):
                    gid=f'{r}_{check_kind}{block}_{i}';outcome=0
                    if fault and fault['kind']=='data' and t>=fault['round']:
                        index=DATA_IDS.index(fault['qubit_id']);local=index%9
                        error_x=int(fault['pauli'] in ('X','Y'));error_z=int(fault['pauli'] in ('Z','Y'))
                        check_x=int(check_kind=='X');check_z=int(check_kind=='Z')
                        outcome=((error_x*check_z+error_z*check_x)%2)*int(index//9==block and local in check)
                    physical[gid]=outcome
                    flipped=bool(fault and fault['kind']=='readout' and t==fault['round'] and block==fault['patch']
                                 and check_kind==fault['check_type'] and i==fault['check_index'])
                    reported[gid]=outcome^int(flipped)
    return physical,reported


@pytest.mark.parametrize('index,fault',CASES,ids=[f'case-{i}' for i,_ in CASES])
def test_all_211_single_events_have_expected_true_reported_history_and_recover(index,fault):
    quantum,report=simulate_ideal(seed=7+17*index,fault=fault)
    physical,reported=independent_history(fault)
    assert {g:report['true_measurement_results'][g] for g in HISTORY_IDS}==physical
    assert {g:report['reported_measurement_results'][g] for g in HISTORY_IDS}==reported
    assert report['history_complete'] and report['history_supported']
    assert report['measurement_protocol_complete'] and all(report['syndrome_rounds_complete'].values())
    assert report['verified_logical_ghz2']
    assert len(report['stabilizer_expectations'])==16 and set(report['stabilizer_expectations'].values())=={1}
    assert report['logical_xx']==report['logical_zz']==1
    assert all(quantum.expectation({q:'Z'})==1 for q in QUBIT_IDS[18:])
    actual=Counter((g['gate_type'],tuple(g['qubit_ids'])) for g in report['corrections'] if g['gate_id'].startswith(CORRECTION_PREFIX))
    assert actual==Counter((g['gate_type'],tuple(g['qubit_ids'])) for g in decode(reported))
    if not fault or fault['kind']=='readout':assert not decode(reported)


def test_supported_global_set_is_fixed_deduplicated_and_includes_no_correction_histories():
    assert len(CASES)==211 and len(supported_histories())==187
    independent={tuple(independent_history(f)[1][g] for g in HISTORY_IDS) for _,f in CASES}
    assert supported_histories()==independent
    base=protocol()
    def corrections(definition):
        return [(g['id'],g['gate_type'],g['qubit_ids'],g['condition']) for g in definition['gates']
                if g['id'].startswith(CORRECTION_PREFIX)]
    for f in ({'kind':'data','round':1,'pauli':'Y','qubit_id':'Q014'},
              {'kind':'readout','round':3,'patch':1,'check_type':'Z','check_index':3}):
        assert corrections(protocol(f))==corrections(base)
    assert all(len(condition)==16 and {ref for ref,bit in condition}<=set(HISTORY_IDS)
               for _,_,_,condition in corrections(base))


def test_unknown_joint_history_rejected_even_when_each_css_subhistory_is_supported():
    bits=dict.fromkeys(HISTORY_IDS,0)
    bits['round1_X0_0']=1;bits['round1_Z1_0']=1
    for block in range(2):
        for kind in ('X','Z'):
            local=tuple(bits[f'{r}_{kind}{block}_{i}'] for r in ROUNDS for i in range(4))
            assert local in css_history_table(block,kind)
    with pytest.raises(ValidationError,match='UNSUPPORTED_SYNDROME_HISTORY'):decode(bits)
    with pytest.raises(ValidationError,match='INCOMPLETE_SYNDROME_HISTORY'):validate_history({})
    bits=dict.fromkeys(HISTORY_IDS,0);bits[HISTORY_IDS[0]]=True
    with pytest.raises(ValidationError,match='INVALID_SYNDROME_HISTORY'):validate_history(bits)


def test_actual_two_readout_flips_are_stopped_before_temporal_correction():
    gates=deepcopy(protocol()['gates'])
    for gid in ('round1_X0_0','round1_Z1_0'):next(g for g in gates if g['id']==gid)['readout_flip']=True
    with pytest.raises(ValidationError,match='UNSUPPORTED_SYNDROME_HISTORY'):simulate_ideal(gates,seed=7)


def test_closing_round_and_data_boundary_are_actual_gates_with_global_barriers():
    definition=protocol({'kind':'data','round':2,'pauli':'X','qubit_id':'Q014'})
    counts=Counter(g['gate_type'] for g in definition['gates'])
    assert counts['MEASURE']==counts['RESET']==80 and counts['CZ']==249
    assert len(definition['readouts'])==80 and len(definition['history_ids'])==64
    fault=next(g for g in definition['gates'] if g['id']==FAULT_GATE_ID)
    assert fault['gate_type']=='X' and fault['qubit_ids']==['Q014']
    stages={s['gate_id']:s['stage'] for s in definition['stages']}
    parents={};last={}
    ordered=sorted(definition['gates'],key=lambda g:(g['column'],g['id']))
    for gate in ordered:
        direct=set(gate.get('depends_on',()))|{g for g,_ in gate.get('condition',())}|{last[q] for q in gate['qubit_ids'] if q in last}
        assert direct<=parents.keys()
        parents[gate['id']]=direct|set().union(*(parents[g] for g in direct))
        for q in gate['qubit_ids']:last[q]=gate['id']
    previous={gid for gid,stage in stages.items() if stage.startswith('round1-')}
    assert previous<=parents[FAULT_GATE_ID]
    assert all(FAULT_GATE_ID in parents[gid] for gid,stage in stages.items() if stage.startswith('round2-') and gid!=FAULT_GATE_ID)
    for previous_round,following in zip(ROUNDS,ROUNDS[1:]):
        before={gid for gid,stage in stages.items() if stage.startswith(previous_round+'-')}
        after=[gid for gid,stage in stages.items() if stage.startswith(following+'-')]
        assert all(before<=parents[gid] for gid in after)
    assert all(set(HISTORY_IDS)<=parents[g['id']] for g in ordered if g['id'].startswith(CORRECTION_PREFIX))


def test_only_selected_noisy_readout_has_report_flip_and_input_metadata_is_display_only():
    fault={'kind':'readout','round':2,'patch':0,'check_type':'X','check_index':0}
    value=experiment_input(fault)
    assert value['compiler']=='qec_temporal' and 'qec_fault' not in value
    flips=[g for g in value['gates'] if g.get('readout_flip')]
    assert [(g['id'],g['gate_type']) for g in flips]==[('round2_X0_0','MEASURE')]
    assert value['qec_protocol']['noise_event']==fault
    _,report=simulate_ideal(value['gates'],seed=7)
    bits=dict(report['reported_measurement_results'])
    baseline=decode(bits)
    for gid in list(bits):
        if gid.startswith('prepare_'):bits[gid]^=1
    bits['fault_truth_metadata']={'pauli':'Y','qubit_id':'Q008'}
    assert decode(bits)==baseline


def test_optimized_and_raw_physical_gate_lists_have_same_temporal_histories():
    fault={'kind':'data','round':3,'pauli':'Z','qubit_id':'Q010'}
    _,optimized=simulate_ideal(seed=31,fault=fault)
    _,raw=simulate_ideal(protocol(fault,optimize=False)['gates'],seed=31)
    assert raw['reported_measurement_results']==optimized['reported_measurement_results']
    assert raw['true_measurement_results']==optimized['true_measurement_results']
    assert raw['verified_logical_ghz2'] and raw['measurement_protocol_complete']


@pytest.mark.parametrize('fault',[{'kind':'data','round':4,'pauli':'X','qubit_id':'Q000'},
    {'kind':'readout','round':4,'patch':0,'check_type':'X','check_index':0},
    {'kind':'data','round':1,'pauli':'X','qubit_id':'Q018'},
    {'kind':'data','round':True,'pauli':'X','qubit_id':'Q000'},
    {'kind':'readout','round':1,'patch':0,'check_type':'X','check_index':4}])
def test_declared_fault_domain_rejects_closing_or_out_of_model_events(fault):
    with pytest.raises(ValueError):normalize_fault(fault)

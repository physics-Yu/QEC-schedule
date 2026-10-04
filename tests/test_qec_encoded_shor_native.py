"""Cross-check actual streamed encoded boundaries against independent CT math."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pytest
from neutral_atom_experiments.qec_pbc.adaptive_pbc import compile_adaptive_pbc
from neutral_atom_experiments.qec_pbc.encoded_shor_native import execute_encoded_native, deserialize_adaptive, _resource_x_kernel
from neutral_atom_experiments.qec_pbc.logical_pauli import LogicalGate, compile_logical_pauli


def _program():
    gates=(LogicalGate('H',('a',)),LogicalGate('T',('a',)),LogicalGate('CX',('a','b')),
        LogicalGate('S',('b',)),LogicalGate('H',('a',)),LogicalGate('Tdg',('b',)),
        LogicalGate('H',('b',)),LogicalGate('T',('a',)))
    return gates,compile_adaptive_pbc(compile_logical_pauli(gates,wires=('a','b')),
        resource_quality='ideal_reference',resource_provenance='test actual native producer')


def _independent(gates,state):
    matrices={'H':np.array([[1,1],[1,-1]],complex)/np.sqrt(2),'S':np.diag([1,1j]),
        'T':np.diag([1,np.exp(1j*np.pi/4)]),'Tdg':np.diag([1,np.exp(-1j*np.pi/4)])}
    result=state.copy()
    for gate in gates:
        if gate.name=='CX':
            result=result.reshape(2,2,2).copy();result[1]=result[1][[1,0]];result=result.ravel()
        else:
            position=('a','b').index(gate.wires[0])
            full=np.array([[1]],complex)
            for i in range(3):full=np.kron(full,matrices[gate.name] if i==position else np.eye(2))
            result=full@result
    return result


@pytest.mark.parametrize('seed',[0,1,7])
def test_entangled_noncommuting_branch_matches_full_complex_ct(tmp_path,seed):
    gates,program=_program()
    rng=np.random.default_rng(22);initial=rng.normal(size=8)+1j*rng.normal(size=8);initial/=np.linalg.norm(initial)
    output=tmp_path/'run'
    summary=execute_encoded_native(program,initial,output,reference_qubits=1,rounds=1,seed=seed)
    value=json.loads((output/'shot0_semantic_state.json').read_text())
    actual=np.array([complex(*row) for row in value['amplitudes']])
    phase=np.exp(1j*np.pi*value['branch_global_phase_eighth_turns']/8)
    assert np.linalg.norm(actual-phase*_independent(gates,initial))<2e-11
    assert summary['encoded_native_branch_complete'] and summary['physical_executed'] is False
    native=[json.loads(line) for line in (output/'native_gates.jsonl').read_text().splitlines()]
    projections=[json.loads(line) for line in (output/'native_projections.jsonl').read_text().splitlines()]
    assert len({g['id'] for g in native})==len(native)
    assert {g['id'] for g in native if g['gate_type'] in ('RESET','MEASURE')}=={r['native_gate_id'] for r in projections}
    assert len(projections)==len({r['native_gate_id'] for r in projections})
    assert all(0<r['conditional_probability']<=1+1e-11 for r in projections)
    manifest=json.loads((output/'manifest.json').read_text())
    for name,record in manifest['artifacts'].items():
        assert hashlib.sha256((output/name).read_bytes()).hexdigest()==record['sha256']
    frames=[json.loads(line) for line in (output/'frames.jsonl').read_text().splitlines()]
    assert frames[-1]['ledger_length']==3


def test_function_byte_ranges_hash_actual_native_transcript(tmp_path):
    _,program=_program();initial=np.zeros(4,complex);initial[0]=1
    output=tmp_path/'run';execute_encoded_native(program,initial,output)
    gates=(output/'native_gates.jsonl').read_bytes();projections=(output/'native_projections.jsonl').read_bytes()
    for line in (output/'functions.jsonl').read_text().splitlines():
        row=json.loads(line)
        block=gates[row['gate_byte_start']:row['gate_byte_end']]
        assert block.count(b'\n')==row['gate_count']
        assert hashlib.sha256(block).hexdigest()==row['native_sha256']
        block=projections[row['projection_byte_start']:row['projection_byte_end']]
        assert block.count(b'\n')==row['projection_count']
        assert hashlib.sha256(block).hexdigest()==row['projection_sha256']


def test_adaptive_deserialize_validates_entire_operation_contract():
    _,program=_program();value=program.to_dict()
    assert deserialize_adaptive(value)==program
    value['injections'][0]['operations'][1]['observable']['sign']*=-1
    with pytest.raises(ValueError,match='operation semantics'):deserialize_adaptive(value)


def test_adaptive_json_roundtrip_keeps_validated_complete_schema():
    _,program=_program()
    assert deserialize_adaptive(json.loads(json.dumps(program.to_dict())))==program


def test_resource_raw_bras_complete_and_fixed_support():
    bras=_resource_x_kernel()
    assert bras.shape==(512,2)
    assert np.linalg.norm(bras.conj().T@bras-np.eye(2))<2e-12
    assert np.count_nonzero(np.max(abs(bras),axis=1)>1e-12)==32


def test_existing_output_is_preserved(tmp_path):
    _,program=_program();output=tmp_path/'run';output.mkdir();marker=output/'marker';marker.write_text('preserve')
    with pytest.raises(FileExistsError):execute_encoded_native(program,np.array([1,0,0,0],complex),output)
    assert marker.read_text()=='preserve'


def test_retry_cleanup_costs_cover_every_actual_native_record(tmp_path):
    """Synthetic zero-output CT probe exercises retries; not a Shor proof."""
    from neutral_atom_experiments.qec_pbc.qft_synthesis import SynthesizedShor15
    from neutral_atom_experiments.qec_pbc.shor15 import build_shor15
    wires=tuple(f'phase{i}' for i in range(8))+tuple(f'work{i}' for i in range(4))
    gates=(LogicalGate('T',('phase0',)),)
    program=compile_adaptive_pbc(compile_logical_pauli(gates,wires=wires),resource_quality='ideal_reference',
        resource_provenance='synthetic zero-output CT retry test only')
    # Trusted semantic probe supplied directly; complete CLI instead must
    # pass the unchanged full72source/28CP cache loader.
    semantic_probe=SynthesizedShor15(build_shor15(),wires,gates,0.,1e-3,1e-3,(),
        ({'source_gate_index':0,'stage':'synthetic_zero_output_probe','name':'T','gate_span':[0,1]},))
    initial=np.zeros(4096,complex);initial[0]=1
    output=tmp_path/'retry'
    summary=execute_encoded_native(program,initial,output,terminal_wires=wires[:8],synthesized=semantic_probe,max_attempts=2)
    assert len(summary['attempts'])==2 and not summary['success']
    assert [row['phase_outcome'] for row in summary['attempts']]==[0,0]
    first=summary['attempts'][0]
    assert first['cleanup_native_gate_count']==first['cleanup_projection_count']==12*18
    assert first['algorithm_reset_released_before_next_shot']
    assert sum(row['native_gate_count'] for row in summary['attempts'])==summary['native_gate_count']
    assert sum(row['native_projection_count'] for row in summary['attempts'])==summary['native_projection_count']
    functions=[json.loads(line) for line in (output/'functions.jsonl').read_text().splitlines()]
    assert len([f for f in functions if f['kind']=='algorithm_cleanup_reset'])==12
    assert sum(f['gate_count'] for f in functions)==summary['native_gate_count']


def test_algorithm_patch_cannot_alias_reserved_resource_roles(tmp_path):
    program=compile_adaptive_pbc(compile_logical_pauli((),wires=('resource',)),
        resource_quality='ideal_reference',resource_provenance='alias negative test')
    output=tmp_path/'alias'
    with pytest.raises(ValueError,match='reserved physical resource patch'):
        execute_encoded_native(program,np.array([1,0],complex),output)
    assert not output.exists()

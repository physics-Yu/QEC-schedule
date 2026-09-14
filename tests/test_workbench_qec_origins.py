"""Explicit patch geometry is editable input; absent fields stay absent."""
import json

import pytest

from neutral_atom_env.experiments.surface_qec import experiment_input
from neutral_atom_env.visualization.workbench import build_inputs,validate_input,preview


def test_old_normalized_input_does_not_gain_origins():
    raw=experiment_input();old=validate_input(raw)
    assert 'qec_patch_origins' not in old
    assert validate_input(json.loads(json.dumps(old)))==old
    assert build_inputs(raw)[0]==old


def test_explicit_default_origins_preserve_default_physical_platform():
    raw=experiment_input()
    implicit=build_inputs(raw)
    explicit=build_inputs(raw|{'qec_patch_origins':[[0,0],[40,0]]})
    assert explicit[0]['qec_patch_origins']==[[0,0],[40,0]]
    assert explicit[1:]==implicit[1:]


def test_shifted_origins_reach_preview_and_keep_edited_gates_and_hardware():
    raw=experiment_input();raw.update(compiler='qec_joint',qec_patch_origins=[[0,0],[45,5]],
        aod_rows=8,aod_columns=14,aod_traps=112,aod_row_offsets_um=list(range(0,40,5)),
        aod_column_offsets_um=list(range(0,35,5))+list(range(45,80,5)))
    raw['gates']=[{'id':'edited','gate_type':'H','qubit_ids':['Q009'],'parameters':[],'column':0}]
    value,circuit,platform,placement=build_inputs(raw)
    assert value['qec_patch_origins']==[[0,0],[45,5]]
    assert [g.id for g in circuit.gates]==['edited']
    assert (platform.aod.rows,platform.aod.columns)==(8,14)
    result=preview(raw)
    atoms={a['id']:a for a in result['recording']['frames'][0]['atom_updates']}
    assert atoms['Q000']['position']=={'x_um':0,'y_um':0}
    assert atoms['Q009']['position']=={'x_um':45,'y_um':5}
    assert atoms['Q026']['position']=={'x_um':50,'y_um':10}
    assert result['input']==value and len(placement)==34


@pytest.mark.parametrize('origins',[None,[],[[0,0]],[[0,0],[40,0],[80,0]],
    [[True,0],[40,0]],[[float('nan'),0],[40,0]],[[0,0],[42,0]],[[0,0],[0,0]],
    [[0,0],[10,0]],[[0,0],['40',0]],[[0,0],[1000,0]]])
def test_invalid_origin_input_is_rejected_as_declared_negative(origins):
    with pytest.raises(ValueError):validate_input(experiment_input()|{'qec_patch_origins':origins})


def test_non_qec_origins_are_not_silently_dropped():
    with pytest.raises(ValueError,match='QEC profile'):
        validate_input({'atom_count':1,'layout':'row','gates':[],
                        'qec_patch_origins':[[0,0],[40,0]]})

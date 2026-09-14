import pytest
from neutral_atom_experiments.qec_four_layout import build_qec_four_inputs, coordinates


def test_explicit_small_aod_changes_actual_capacity_instead_of_silently_using98():
    for fields,shape in (({'aod_traps':9},(1,9)),({'aod_rows':3,'aod_columns':6},(3,6))):
        _,_,platform,_=build_qec_four_inputs({'gates':[],**fields})
        assert (platform.aod.rows,platform.aod.columns)==shape
        assert len(platform.aod.configuration().x_um)==shape[1]
        assert len(platform.aod.configuration().y_um)==shape[0]


def test_origin_shift_must_keep_real_measurement_sites_in_mz():
    # Shift C/D by +10: storage still fits, but highest readout trap would
    # be y=-145, outside MZ. Reject the input before scheduling.
    with pytest.raises(ValueError,match='readout sites'):
        coordinates(((0,0),(40,0),(0,50),(40,50)))
    assert max(y for _,y in coordinates(((0,0),(40,0),(0,45),(40,45))))==70


@pytest.mark.parametrize('origins',[
    ((0,0),(40,0)),((0,0),(40,0),(0,0),(40,40)),
    ((0,0),(40,0),(False,40),(40,40)),
    ((0,0),(40,0),(0,float('inf')),(40,40)),
])
def test_bad_four_origins_are_rejected(origins):
    with pytest.raises(ValueError):coordinates(origins)

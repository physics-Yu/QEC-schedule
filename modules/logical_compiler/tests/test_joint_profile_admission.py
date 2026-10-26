"""Joint trace claims preserve shared AOD admission for vertical mixed modules."""

from dataclasses import replace

import pytest

from modules.codes.contracts.parallel import ComponentExecutionSpec, SharedAODClaim
from modules.logical_compiler.src.scheduling.compatibility import compatible_specs


def joint_spec(member, component="raw_t_postselection", blocks=None):
    claim = SharedAODClaim(
        "transport",
        "joint-world",
        0,
        60,
        4,
        4,
        None,
        None,
        "camera",
        8,
        None,
        joint_family="validated-world-profile",
        joint_member=member,
    )
    return ComponentExecutionSpec(
        "rotated_surface_d5",
        component,
        "joint-world",
        blocks or (member,),
        (),
        (),
        "shared_aod_lockstep",
        24,
        claim,
    )


def test_vertical_joint_claims_allow_same_columns_and_mixed_frontiers():
    left = joint_spec("factory0/R")
    right = joint_spec(
        "factory1/W1", "transversal_cnot", ("factory1/W1", "factory1/W2")
    )
    assert compatible_specs((left, right))
    assert not compatible_specs(
        (left, replace(right, participant_blocks=left.participant_blocks))
    )
    assert not compatible_specs(
        (
            left,
            replace(
                right, shared_aod=replace(right.shared_aod, joint_family="other-world")
            ),
        )
    )


def test_legacy_column_claims_are_not_reinterpreted_as_joint_traces():
    joint = joint_spec("factory0/R")
    legacy = replace(
        joint,
        shared_aod=replace(joint.shared_aod, joint_family=None, joint_member=None),
    )
    assert not compatible_specs(
        (joint, replace(legacy, participant_blocks=("factory1/R",)))
    )
    assert "joint_family" not in legacy.shared_aod.to_dict()
    assert legacy.shared_aod.band_peaks() == (4, 4, 8)
    with pytest.raises(ValueError, match="JOINT_AOD_CLAIM_REQUIRES_GROUP_EXECUTION"):
        joint.shared_aod.band_peaks()

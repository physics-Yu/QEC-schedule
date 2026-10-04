"""The collection profile declares real supports without replacing source state."""
from math import hypot

import pytest

from neutral_atom_env.domain.models import HolderType, ZoneType
from neutral_atom_experiments.qec_pbc.parallel_prefix import load_native_parallel_prefix
from neutral_atom_experiments.qec_pbc.patch_layout import (
    create_collective_environment, create_enola_environment, create_interleaved_environment,
)

SOURCE = 'references/qec_pbc_validation/shor15_native_prefix_seed0_2026_10_04'
PROPOSAL = 'references/qec_pbc_validation/enola_patch_proposal_2026_10_04.json'


@pytest.mark.parametrize('patches,magic,layout', [(12, True, 'enola'), (1, False, 'interleaved')])
def test_mz_inventory_preserves_sources_thresholds_and_full_x_illumination(patches, magic, layout):
    prefix = load_native_parallel_prefix(SOURCE, patch_count=patches, include_magic=magic)
    if layout == 'enola':
        old, _, old_placement, _ = create_enola_environment(prefix, PROPOSAL)
    else:
        old, _, old_placement, _ = create_interleaved_environment(prefix)
    env, platform, placement, metadata = create_collective_environment(prefix,
        layout=layout, proposal=PROPOSAL)
    assert env.state.hardware == old.state.hardware
    assert env.state.dag.circuit == old.state.dag.circuit == prefix.circuit
    assert env.state.quantum_state == old.state.quantum_state
    assert placement == old_placement
    assert env.state.placement == old.state.placement
    slots = metadata['collective_mz_contract']['target_traps']
    assert len(slots) == len(placement) == 17*patches + (17 if magic else 0)
    assert len(set(slots.values())) == len(slots)
    mz = next(z for z in platform.world.zones if z.zone_type == ZoneType.MEASUREMENT)
    compute = next(z for z in platform.world.zones if z.zone_type == ZoneType.ENTANGLEMENT)
    assert (compute.bounds.lower.x_um, compute.bounds.upper.x_um) == (
        platform.world.bounds.lower.x_um, platform.world.bounds.upper.x_um)
    for q, home in placement.items():
        assert platform.world.traps[home] == old.state.world.traps[home]
        assert env.state.placement.atom_to_holder[q].holder_type == HolderType.STATIC
        trap = platform.world.traps[slots[q]]
        assert not trap.enabled and mz.bounds.contains(trap.position)
        assert trap.position.x_um % 5 == trap.position.y_um % 5 == 0
    points = [platform.world.traps[key].position for key in slots.values()]
    assert min(hypot(a.x_um-b.x_um, a.y_um-b.y_um)
        for i, a in enumerate(points) for b in points[i+1:]) >= 10

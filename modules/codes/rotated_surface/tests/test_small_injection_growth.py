"""Channel, decoder and staged admission checks for fixed-distance injection."""

import pytest


@pytest.fixture(scope="module")
def staged():
    from experiments.msd.standard import ExperimentSpec, build_world
    from modules.codes.contracts.component import InvocationContext
    from modules.codes.rotated_surface import RawTPostselection

    world = build_world(ExperimentSpec(distance=5))
    patch = world.patch(0, "R")
    protocol = RawTPostselection(5)
    template = protocol.compile(
        world.device,
        home_sites=patch.home_sites,
        origin=patch.binding.origin,
        aod_id=patch.binding.aod_id,
    )
    bound = template.bind(patch.binding)
    stage = bound.expand(InvocationContext("seed", 100, 50, world.device, world.state))
    return protocol, world, bound, stage


def test_accepted_stage_grows_decodes_and_preserves_full_world(staged):
    from modules.codes.contracts.component import InvocationContext

    protocol, world, bound, stage = staged
    sequence = stage.sequence
    accepted = stage.with_results(
        {m.result.measurement_id: 0 for m in sequence.measurements}
    )
    context = InvocationContext(
        "outer", sequence.results_ready_us, 1000, world.device, sequence.exit_state
    )
    result = bound.grow(accepted, context)
    assert len(result.parts) == protocol.growth_rounds
    assert result.parts[-1].exit_state == world.state
    assert all(not p.acceptance_conditions for p in result.parts)
    with pytest.raises(ValueError, match="received"):
        result.decode(result.results_ready_us)
    # Nonzero, constant target checks are gauge information, not rejection.
    values = {
        m.result.measurement_id: int(i == 0)
        for p in result.parts
        for i, m in enumerate(p.measurements)
    }
    result = result.with_results(values)
    frame = result.decode(result.results_ready_us)
    assert frame.x or frame.z
    with pytest.raises(ValueError, match="arrived"):
        result.decode(result.results_ready_us - 1)

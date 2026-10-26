"""Channel, decoder and staged admission checks for fixed-distance injection."""

import pytest
import stim

from modules.codes.rotated_surface.components import SurfaceComponent
from modules.codes.rotated_surface.definition import definition
from modules.codes.rotated_surface.growth import GrowthComponent, injection_indices
from modules.codes.rotated_surface.tests.test_distance_components import circuit, pauli


@pytest.mark.parametrize("distance", (5, 7, 9))
@pytest.mark.parametrize("basis", ("X", "Y", "Z"))
def test_growth_preserves_arbitrary_seed_channel_in_every_sampled_branch(
    distance, basis
):
    code = definition(distance)
    growth = GrowthComponent(distance)
    mapping = injection_indices(distance)
    source = circuit(SurfaceComponent("raw_t", 3).source_qasm, seed_basis=basis)
    embedded = stim.Circuit()
    for instruction in source:
        embedded.append(
            instruction.name, [mapping[t.value] for t in instruction.targets_copy()]
        )
    outer = circuit(growth.source_qasm)
    for seed in range(16):
        sim = stim.TableauSimulator(seed=seed)
        sim.do(embedded)
        sim.do(outer)
        values = sim.current_measurement_record()[-code.check_count :]
        for term, bit in zip(growth.correction_terms, values, strict=True):
            if bit:
                for role, p in term.pauli_roles:
                    getattr(sim, p.lower())(int(role[5:-1]))
        for b, support in code.checks:
            assert sim.peek_observable_expectation(pauli(code, b, support)) == 1
        x = pauli(code, "X", code.logical_x)
        z = pauli(code, "Z", code.logical_z)
        logical = x if basis == "X" else z if basis == "Z" else 1j * x * z
        assert sim.peek_observable_expectation(logical) == 1


@pytest.mark.parametrize("distance", (5, 7, 9))
def test_growth_never_resets_injected_data_and_keeps_upper_edge(distance):
    component = GrowthComponent(distance)
    mapping = injection_indices(distance)
    code = definition(distance)
    assert len(mapping) == len(set(mapping)) == 17
    assert max(code.data_coordinates[q][1] for q in mapping[:9]) == 2 * distance - 1
    for q in mapping[:9]:
        assert f"reset q[{q}];" not in component.source_qasm
    assert "\nt q[" not in component.source_qasm
    assert component.acceptance_ports == ()


@pytest.mark.parametrize("distance", (5, 7))
def test_decoder_corrects_persistent_single_data_faults_and_readout_blips(distance):
    from modules.codes.rotated_surface.growth_decoder import GrowthDecoder

    code = definition(distance)
    decoder = GrowthDecoder(distance)
    for basis in ("X", "Z"):
        for q in range(code.data_count):
            syndrome = tuple(int(b != basis and q in qs) for b, qs in code.checks)
            history = [(0,) * code.check_count, syndrome, syndrome, syndrome, syndrome]
            frame = decoder.decode(history)
            x, z = (
                frame.x ^ ((1 << q) if basis == "X" else 0),
                frame.z ^ ((1 << q) if basis == "Z" else 0),
            )
            assert all(
                sum(((z if b == "X" else x) >> a) & 1 for a in qs) % 2 == 0
                for b, qs in code.checks
            )
            assert sum((z >> a) & 1 for a in code.logical_x) % 2 == 0
            assert sum((x >> a) & 1 for a in code.logical_z) % 2 == 0
    for j in range(code.check_count):
        history = [[0] * code.check_count for _ in range(5)]
        history[2][j] = 1
        frame = decoder.decode(history)
        assert frame.x == frame.z == 0


def test_decoder_accepts_nonzero_initial_gauge_and_requires_complete_bits():
    from modules.codes.rotated_surface.growth_decoder import GrowthDecoder

    decoder = GrowthDecoder(5)
    syndrome = tuple(int(i % 3 == 0) for i in range(24))
    frame = decoder.decode([syndrome] * 5)
    assert frame.x or frame.z
    assert frame.decoder == "phenomenological_mwpm_open_boundary/1"
    with pytest.raises(ValueError):
        decoder.decode([[None] * 24] * 5)


@pytest.fixture(scope="module", params=(3, 5, 7))
def staged(request):
    from experiments.msd.standard import ExperimentSpec, build_world
    from modules.codes.contracts.component import InvocationContext
    from modules.codes.rotated_surface import RawTPostselection

    world = build_world(ExperimentSpec(distance=request.param))
    patch = world.patch(0, "R")
    protocol = RawTPostselection(request.param)
    template = protocol.compile(
        world.device,
        home_sites=patch.home_sites,
        origin=patch.binding.origin,
        aod_id=patch.binding.aod_id,
    )
    bound = template.bind(patch.binding)
    stage = bound.expand(InvocationContext("seed", 100, 50, world.device, world.state))
    return protocol, world, template, bound, stage


def test_rejected_or_pending_seed_never_grows(staged):
    from modules.codes.contracts.component import InvocationContext

    _, world, _, bound, stage = staged
    sequence = stage.sequence
    context = InvocationContext(
        "outer", sequence.results_ready_us, 1000, world.device, sequence.exit_state
    )
    with pytest.raises(ValueError, match="accepted"):
        bound.grow(stage, context)
    bits = {m.result.measurement_id: 0 for m in sequence.measurements}
    bits[sequence.detectors[0].measurements[0].result.measurement_id] = 1
    with pytest.raises(ValueError, match="accepted"):
        bound.grow(stage.with_results(bits), context)
    assert len(sequence.parts) == 3
    assert len(sequence.detectors) == 20
    assert len(sequence.parts[0].wire_atoms) == 17


def test_accepted_stage_grows_decodes_and_preserves_full_world(staged):
    from modules.codes.contracts.component import InvocationContext

    protocol, world, _, bound, stage = staged
    sequence = stage.sequence
    accepted = stage.with_results(
        {m.result.measurement_id: 0 for m in sequence.measurements}
    )
    context = InvocationContext(
        "outer", sequence.results_ready_us, 1000, world.device, sequence.exit_state
    )
    result = bound.grow(accepted, context)
    assert len(result.parts) == protocol.growth_rounds
    if result.parts:
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
    else:
        frame = result.decode(result.results_ready_us)
        assert frame.x == frame.z == 0
    with pytest.raises(ValueError, match="arrived"):
        result.decode(result.results_ready_us - 1)


def test_cache_identity_and_growth_is_not_a_delivery_event(staged):
    from modules.codes.rotated_surface import DirectRawTPostselection, RawTPostselection

    protocol, world, template, _, stage = staged
    port = protocol.acceptance_port(stage, world.device, noise_params={})
    assert port.outcome("accepted").probability == 1
    assert port.to_dict()["branches"][0]["transition"] == "continue"
    protocol.validate_acceptance_port(port, template, noise_params={})
    old = DirectRawTPostselection(
        3, 2, round_policy="explicit_control"
    ).acceptance_port(stage.sequence, world.device, noise_params={})
    with pytest.raises(ValueError, match="cache"):
        protocol.validate_acceptance_port(old, template, noise_params={})
    with pytest.raises(ValueError, match="cache"):
        RawTPostselection(
            protocol.distance, injection_rounds=2
        ).validate_acceptance_port(port, template, noise_params={})
    with pytest.raises(ValueError, match="cache"):
        protocol.validate_acceptance_port(
            port, template, noise_params={"readout_flip": 0.1}
        )
    from modules.codes.rotated_surface_d3.protocols.fast_profile import (
        validate_raw_t_port,
    )

    with pytest.raises(ValueError, match="INCONSISTENT_FAST_RAW_T_PORT"):
        validate_raw_t_port(port.to_dict())

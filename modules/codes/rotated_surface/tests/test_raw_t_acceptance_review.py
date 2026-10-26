"""Independent seed algebra, readout controls, categorical sampling, and admission."""

from dataclasses import replace
from itertools import pairwise, product
from math import isclose, pi, sqrt
from statistics import NormalDist

import pytest
import qiskit.qasm3
from nadit_physical_compiler.atom_ir import AtomProgram, Rotation
from nadit_physical_compiler.cost import prepare

from experiments.msd.standard import ExperimentSpec, build_world
from modules.codes._support.detector_probability import estimate_acceptance
from modules.codes._support.pauli_detector_events import detector_fault_channels
from modules.codes.contracts.component import InvocationContext
from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.rotated_surface import DirectRawTPostselection as RawTPostselection
from modules.codes.rotated_surface import definition, get_component
from modules.codes.rotated_surface.probabilities.raw_t import (
    _joint_document,
    raw_t_acceptance_port,
)


def _rank(vectors):
    """Independent elimination, without the code family's algebra implementation."""
    pivots = {}
    for value in vectors:
        while value:
            high = value.bit_length() - 1
            if high in pivots:
                value ^= pivots[high]
            else:
                pivots[high] = value
                break
    return len(pivots)


def _source_seed(distance):
    """Read the actual preparation prefix, retaining its real T checkpoint."""
    code = definition(distance)
    parsed = qiskit.qasm3.loads(
        get_component("raw_t_direct_control", distance).source_qasm
    )
    axes, seeds = {}, []
    for instruction in parsed.data:
        name = instruction.operation.name
        if name == "barrier":
            break
        (q,) = (parsed.find_bit(q).index for q in instruction.qubits)
        if name == "reset":
            axes[q] = "Z"
        elif name == "h":
            axes[q] = "X" if axes[q] == "Z" else "Z"
        else:
            assert name == "t"
            assert axes[q] == "X"
            seeds.append(q)
    assert seeds == [code.data_count // 2]
    assert set(axes) == set(range(code.data_count))
    return code, axes, seeds[0]


@pytest.mark.parametrize("distance,boundary", ((3, 4), (5, 8), (7, 20), (9, 32)))
def test_actual_product_seed_has_exact_deterministic_intersection(distance, boundary):
    code, axes, seed = _source_seed(distance)
    n = code.data_count
    checks = [
        sum(1 << q for q in support) << (0 if basis == "X" else n)
        for basis, support in code.checks
    ]
    initial = [(1 << q) << (0 if axes[q] == "X" else n) for q in axes if q != seed]
    dimension = _rank(checks) + _rank(initial) - _rank(checks + initial)
    accepted = get_component("raw_t_direct_control", distance).acceptance_ports
    deterministic = [checks[code.check_roles.index(port)] for port in accepted]
    assert dimension == len(accepted) == boundary
    assert _rank(initial + deterministic) == len(initial)
    assert _rank(deterministic) == boundary
    center = distance // 2
    assert all(axes[q] == "X" for q in range(center, n, distance) if q != seed)
    assert all(
        axes[q] == "Z"
        for q in range(center * distance, (center + 1) * distance)
        if q != seed
    )


def _readout_channels(distance, rounds, probability):
    code = definition(distance)
    accepted = get_component("raw_t_direct_control", distance).acceptance_ports
    boundary = {port: index for index, port in enumerate(accepted)}
    count = len(boundary) + (rounds - 1) * code.check_count
    channels = []
    for r in range(rounds):
        for check_index, port in enumerate(code.check_roles):
            mask = 1 << boundary[port] if r == 0 and port in boundary else 0
            if r:
                mask ^= 1 << (len(boundary) + (r - 1) * code.check_count + check_index)
            if r + 1 < rounds:
                mask ^= 1 << (len(boundary) + r * code.check_count + check_index)
            channels.append(((mask, probability),))
    return count, tuple(channels)


def _enumerated_single_check(rounds, p, deterministic):
    total = 0.0
    for errors in product((0, 1), repeat=rounds):
        passes = all(a == b for a, b in pairwise(errors))
        if deterministic:
            passes = passes and errors[0] == 0
        if passes:
            total += p ** sum(errors) * (1 - p) ** (rounds - sum(errors))
    return total


@pytest.mark.parametrize("distance", (3, 5, 7, 9))
@pytest.mark.parametrize("rounds", (2, 3))
def test_readout_only_channels_match_independent_multiround_formula(distance, rounds):
    p, shots = 0.013, 32768
    code = definition(distance)
    boundary = len(get_component("raw_t_direct_control", distance).acceptance_ports)
    random = code.check_count - boundary
    expected = _enumerated_single_check(rounds, p, True) ** boundary
    expected *= _enumerated_single_check(rounds, p, False) ** random
    closed = (1 - p) ** (rounds * boundary) * ((1 - p) ** rounds + p**rounds) ** random
    assert expected == pytest.approx(closed, abs=1e-13)
    count, channels = _readout_channels(distance, rounds, p)
    estimate = estimate_acceptance(
        count, channels, shots=shots, seed=1543, batch_size=4096
    )
    if estimate["kind"] == "exact":
        assert estimate["probability"] == pytest.approx(expected, abs=1e-12)
    else:
        assert abs(estimate["probability"] - expected) < 6 * sqrt(
            expected * (1 - expected) / shots
        )
        assert estimate["shots"] == shots
        assert estimate["ci_method"] == "wilson_score"


@pytest.mark.parametrize("method,count", (("exact", 3), ("monte_carlo", 130)))
def test_exclusive_alternatives_and_cross_channel_cancellation(method, count):
    a, b = 1, 1 << (count - 1)
    options = {"method": method, "shots": 1003, "seed": 49, "batch_size": 127}
    # Exactly one nonidentity branch occurs. Sampling X and Z independently
    # would incorrectly invent an identity/cancellation contribution.
    exclusive = estimate_acceptance(count, (((a, 0.5), (b, 0.5)),), **options)
    assert exclusive["probability"] == 0
    cancelled = estimate_acceptance(
        count, (((a | b, 1.0),), ((a | b, 1.0),)), **options
    )
    assert cancelled["probability"] == 1
    assert cancelled["cross_channel_cancellations_preserved"]
    noisy = estimate_acceptance(count, (((a, 0.2),), ((a, 0.3),)), **options)
    expected = 0.8 * 0.7 + 0.2 * 0.3
    if method == "exact":
        assert noisy["probability"] == pytest.approx(expected, abs=1e-14)
    else:
        assert abs(noisy["probability"] - expected) < 6 * sqrt(
            expected * (1 - expected) / 1003
        )
        assert noisy == estimate_acceptance(
            count, (((a, 0.2),), ((a, 0.3),)), **options
        )


def test_reported_interval_is_pointwise_binomial_wilson_not_logical_quality():
    estimate = estimate_acceptance(
        65,
        (((1 << 64, 0.21),), ((1 << 64, 0.17),)),
        method="monte_carlo",
        shots=8191,
        seed=847,
        batch_size=1024,
    )
    n, accepted = estimate["shots"], estimate["accepted"]
    p, z = accepted / n, NormalDist().inv_cdf(0.975)
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    assert estimate["ci95"] == pytest.approx(
        [max(0, center - half), min(1, center + half)]
    )
    assert estimate["probability"] == accepted / n
    assert estimate["kind"] == "estimated"
    assert "logical_error_probability" not in estimate


@pytest.fixture(scope="module")
def actual_raw_sequence():
    world = build_world(ExperimentSpec(5, 1))
    patch = world.patch(0, "R")
    protocol = RawTPostselection(5, extra_rounds=2, round_policy="explicit_control")
    template = protocol.compile(
        world.device,
        home_sites=patch.home_sites,
        origin=patch.binding.origin,
        aod_id=patch.binding.aod_id,
    )
    sequence = template.bind(patch.binding).expand(
        InvocationContext("independent-d5-raw", 4000, 900, world.device, world.state)
    )
    return world, protocol, sequence


def test_real_t_checkpoint_is_required_and_acceptance_export_has_no_quality_claim(
    actual_raw_sequence,
):
    world, protocol, sequence = actual_raw_sequence
    port = protocol.acceptance_port(sequence, world.device, noise_params={})
    model = port.to_dict()["model"]
    proof = model["evidence"]
    assert port.outcome("accepted").probability == 1
    assert proof["center_t_identity_checks"] == len(sequence.detectors)
    assert proof["non_clifford_seed_gates"] == 1
    assert proof["logical_state_replaced_by_clifford_proxy"] is False
    assert proof["logical_error_rate_claimed"] is False
    assert proof["accepted_output_quality"] == "not_estimated"
    assert proof["canonical_class_distribution"] == "not_provided"
    assert dict(port.outcome("accepted").values) == {"accepted": True}
    assert model["parameters"]["distance"] == 5
    assert model["parameters"]["extra_rounds"] == 2
    assert (
        ProbabilityPort.from_dict(port.to_dict()).content_sha256 == port.content_sha256
    )

    document = _joint_document(sequence, world.device, distance=5)
    activity = prepare(document)
    seed = sequence.parts[0].wire_atoms[12]
    t_events = [
        i
        for i, event in enumerate(activity.events)
        if event.kind == "Rotation"
        and event.atoms == (seed,)
        and event.parameters.get("axis") == "Z"
        and isclose(event.parameters["angle"], pi / 4, abs_tol=1e-12)
    ]
    assert len(t_events) == 1
    index = t_events[0]
    altered = replace(
        activity,
        events=tuple(
            replace(event, parameters={**event.parameters, "angle": pi / 2})
            if i == index
            else event
            for i, event in enumerate(activity.events)
        ),
    )
    detectors = tuple(
        tuple(m.result.measurement_id for m in det.measurements)
        for det in sequence.detectors
    )
    with pytest.raises(ValueError, match="exactly one seed T"):
        detector_fault_channels(
            altered,
            [],
            detectors,
            wire_atoms=sequence.parts[0].wire_atoms,
            seed_atom=seed,
            world_atom_ids=tuple(a.atom_id for a in activity.per_atom),
        )


def test_distance_consumer_and_actual_t_action_tampering_are_rejected(
    actual_raw_sequence,
):
    world, _, sequence = actual_raw_sequence
    with pytest.raises(ValueError, match="distance|code"):
        RawTPostselection(
            3, extra_rounds=2, round_policy="explicit_control"
        ).acceptance_port(sequence, world.device, noise_params={})
    first = sequence.parts[0]
    seed = first.wire_atoms[12]
    changed = 0
    steps = []
    for step in first.program.steps:
        actions = []
        for action in step.actions:
            if (
                isinstance(action, Rotation)
                and action.atoms == (seed,)
                and action.axis == "Z"
                and isclose(action.angle, pi / 4, abs_tol=1e-12)
            ):
                action = replace(action, angle=pi / 2)
                changed += 1
            actions.append(action)
        steps.append(replace(step, actions=tuple(actions)))
    assert changed == 1
    forged = replace(
        sequence,
        parts=(
            replace(
                first, program=AtomProgram(tuple(steps), first.program.global_phase)
            ),
            *sequence.parts[1:],
        ),
    )
    with pytest.raises(ValueError, match="semantic|source|pulse"):
        raw_t_acceptance_port(forged, world.device, distance=5, noise_params={})

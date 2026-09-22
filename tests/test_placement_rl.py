"""Behavioral checks for the isolated discrete placement-learning model.

These checks certify the declared discrete model only.  No test here establishes
continuous-path safety or execution in the production neutral-atom environment.
"""

from dataclasses import replace
from collections import Counter
from copy import deepcopy
from itertools import combinations
import json
from math import hypot, sqrt

import pytest

from neutral_atom_strategies.placement_rl import (
    Circuit,
    CompileResult,
    CompilerConfig,
    Hardware,
    Scenario,
    audit_result,
    compile_layout,
    standard_hardware,
)
from neutral_atom_strategies.placement_rl.compiler import conflict_graph, group_violation


def _hardware(storage, *, rows=4, cols=4, targets=()):
    entangling = (((100.0, 100.0), (102.0, 100.0)),
                  ((124.0, 100.0), (126.0, 100.0)))
    storage = tuple(storage)
    known = set(storage) | {point for pair in entangling for point in pair}
    storage += tuple(point for point in targets if point not in known)
    return Hardware(
        storage=storage,
        entangling=entangling,
        aod_rows=rows,
        aod_cols=cols,
    )


@pytest.mark.parametrize(
    ("positions", "targets"),
    [
        (((0, 0), (10, 10)), {0: (20, 20), 1: (10, 30)}),  # Columns cross.
        (((0, 0), (10, 0)), {0: (20, 20), 1: (30, 30)}),  # Shared row splits.
        (((0, 0), (10, 10)), {0: (20, 20), 1: (30, 20)}),  # Distinct rows merge.
        (((0, 0), (0, 10)), {0: (20, 20), 1: (30, 30)}),  # Shared column splits.
        (((0, 0), (10, 10)), {0: (20, 20), 1: (20, 30)}),  # Columns merge.
    ],
)
def test_incompatible_shared_axes_or_order_create_conflict(positions, targets):
    graph = conflict_graph(positions, targets)
    assert 1 in graph[0]
    assert 0 in graph[1]
    hardware = _hardware(positions, targets=targets.values())
    assert group_violation(hardware, positions, targets) == "AXIS_SPLIT_MERGE_OR_CROSSING"


def test_ordered_nonuniform_axis_stretch_is_compatible():
    positions = ((0, 0), (10, 0), (10, 20))
    targets = {0: (30, 40), 1: (47, 40), 2: (47, 63)}
    assert all(not neighbours for neighbours in conflict_graph(positions, targets).values())
    assert group_violation(_hardware(positions, targets=targets.values()), positions, targets) is None


def test_conflict_free_motion_does_not_hide_cartesian_incidental_capture():
    # A pairwise MOTION graph sees no order conflicts.  The active Cartesian
    # grid also illuminates stationary q3 at (0, 10), so the group is illegal.
    # There is necessarily a two-member witness for an endpoint Cartesian ghost;
    # this test does not claim that every pair passes the full capture check.
    positions = ((0, 0), (10, 10), (20, 20), (0, 10))
    targets = {0: (100, 100), 1: (110, 110), 2: (120, 120)}
    assert all(not neighbours for neighbours in conflict_graph(positions, targets).values())
    hardware = _hardware(positions, targets=targets.values())
    assert group_violation(hardware, positions, targets) == "SOURCE_CAPTURE_CLOSURE"


def test_grid_capacity_counts_axes_even_for_sparse_diagonal_occupancy():
    positions = ((0, 0), (10, 10), (20, 20))
    targets = {0: (100, 100), 1: (110, 110), 2: (120, 120)}
    hardware = _hardware(positions, rows=2, cols=2, targets=targets.values())
    # Every pair fits a 2x2 active grid, but the triple needs a 3x3 grid even
    # though just three atoms is below the hardware's four-trap capacity.
    for pair in combinations(targets, 2):
        assert group_violation(hardware, positions, {q: targets[q] for q in pair}) is None
    assert all(not neighbours for neighbours in conflict_graph(positions, targets).values())
    assert group_violation(hardware, positions, targets) == "AOD_CAPACITY"


def test_destination_empty_cartesian_trap_cannot_overlap_stationary_atom():
    positions = ((0, 0), (10, 10), (100, 110))
    targets = {0: (100, 100), 1: (110, 110)}
    assert all(not neighbours for neighbours in conflict_graph(positions, targets).values())
    hardware = _hardware(positions, targets=targets.values())
    assert group_violation(hardware, positions, targets) == "TARGET_STATIONARY_INTERSECTION"


@pytest.mark.parametrize(
    ("positions", "targets"),
    [
        (((0, 0), (0.5, 10)), {0: (100, 100), 1: (110, 110)}),
        (((0, 0), (10, 10)), {0: (100, 100), 1: (100.5, 110)}),
    ],
)
def test_positive_axis_gap_must_meet_minimum_at_both_endpoints(positions, targets):
    hardware = _hardware(positions, targets=targets.values())
    assert all(not neighbours for neighbours in conflict_graph(positions, targets).values())
    assert group_violation(hardware, positions, targets) == "AOD_AXIS_MINIMUM_SEPARATION"
    assert group_violation(replace(hardware, min_axis_separation_um=0.5), positions, targets) is None


def test_independent_replay_rejects_group_below_minimum_axis_gap():
    circuit = Circuit(2, (((0, 1),),))
    hardware = standard_hardware(2)
    mapping = (0, 1)
    result = compile_layout(circuit, hardware, mapping)
    assert result.status == "completed", result.error
    assert audit_result(circuit, hardware, mapping, result)["status"] == "passed"
    # The declared paired EZ traps are separated by 2 um.  Replaying with a
    # stricter 3 um AOD requirement must reject its two-column transport.
    audit = audit_result(circuit, replace(hardware, min_axis_separation_um=3.), mapping, result)
    assert audit["status"] == "failed"
    assert any("minimum axis separation" in message for message in audit["errors"])


def test_transport_timing_includes_longest_empty_cartesian_intersection():
    circuit = Circuit(2, (((0, 1),),))
    hardware = Hardware(storage=((0, 0), (20, 10)),
                        entangling=(((30, 20), (35, 40)),), aod_rows=2, aod_cols=2)
    mapping = (0, 1)
    result = compile_layout(circuit, hardware, mapping)
    assert result.status == "completed", result.error
    move = next(event for event in result.trace if event["kind"] == "move")
    assert set(move["qubits"]) == {0, 1}
    # q0 moves (+30,+20); q1 moves (+15,+30).  Their empty Cartesian
    # intersection combines +30 in each axis, farther than either loaded trap.
    expected = 2. * sqrt(hypot(30., 30.))
    loaded_only = 2. * sqrt(max(hypot(30., 20.), hypot(15., 30.)))
    assert move["duration_us"] == pytest.approx(expected)
    assert move["duration_us"] > loaded_only
    assert audit_result(circuit, hardware, mapping, result)["status"] == "passed"

    trace = deepcopy(result.trace)
    wrong_move = next(event for event in trace if event["kind"] == "move")
    wrong_move["duration_us"] = loaded_only
    elapsed = 0.
    for event in trace:
        event["start_us"] = elapsed
        elapsed += event["duration_us"]
    corrupted = replace(result, trace=trace, duration_us=elapsed)
    audit = audit_result(circuit, hardware, mapping, corrupted)
    assert audit["status"] == "failed"
    assert any("transport duration mismatch" in message for message in audit["errors"])


@pytest.mark.parametrize(
    "layers",
    [(((0, 1), (1, 2)),), (((0, 0),),), (((0, 3),),)],
)
def test_circuit_rejects_nonmatching_or_out_of_range_gates(layers):
    with pytest.raises(ValueError):
        Circuit(3, layers)


def test_hardware_rejects_duplicate_traps_and_invalid_capacity():
    with pytest.raises(ValueError):
        _hardware(((0, 0), (0, 0)))
    with pytest.raises(ValueError):
        _hardware(((0, 0),), rows=0)


def _small_circuit():
    return Circuit(4, (((0, 1), (2, 3)), ((0, 1), (2, 3)), ((0, 2), (1, 3))))


def test_compiler_preserves_every_layer_and_replay_checks_trace():
    circuit = _small_circuit()
    hardware = standard_hardware(4, vacancies=2)
    mapping = (5, 0, 4, 2)
    result = compile_layout(circuit, hardware, mapping)
    assert result.status == "completed", result.error
    expected = Counter((t, tuple(sorted(g))) for t, layer in enumerate(circuit.layers) for g in layer)
    actual = Counter((event["layer"], tuple(sorted(g)))
                     for event in result.trace if event["kind"] == "pulse"
                     for g in event["pairs"])
    assert actual == expected
    assert result.metrics["model_only"] is True
    assert result.metrics["continuous_safety_checked"] is False
    assert audit_result(circuit, hardware, mapping, result)["status"] == "passed"


@pytest.mark.parametrize("removed_kind", ["load", "move", "unload", "pulse"])
def test_replay_rejects_deleted_transport_or_gate_event(removed_kind):
    circuit = _small_circuit()
    hardware = standard_hardware(4, vacancies=2)
    mapping = (0, 1, 2, 3)
    result = compile_layout(circuit, hardware, mapping)
    assert result.status == "completed", result.error
    index = next(i for i, event in enumerate(result.trace) if event["kind"] == removed_kind)
    corrupted = replace(result, trace=result.trace[:index] + result.trace[index + 1:])
    assert audit_result(circuit, hardware, mapping, corrupted)["status"] != "passed"


def test_replay_rejects_tampered_transport_destination_and_reported_duration():
    circuit = _small_circuit()
    hardware = standard_hardware(4, vacancies=2)
    mapping = (0, 1, 2, 3)
    result = compile_layout(circuit, hardware, mapping)
    assert result.status == "completed", result.error
    trace = deepcopy(result.trace)
    event = next(event for event in trace if event["kind"] == "move")
    x, y = event["positions"][0]
    event["positions"][0] = (x + 123.0, y)
    assert audit_result(circuit, hardware, mapping, replace(result, trace=trace))["status"] != "passed"
    corrupted = replace(result, duration_us=result.duration_us + 1.0)
    assert audit_result(circuit, hardware, mapping, corrupted)["status"] != "passed"


@pytest.mark.parametrize("mapping", [(0, 0, 2, 3), (0, 1, 2), (0, 1, 2, 9), (False, 1, 2, 3)])
def test_initial_mapping_requires_complete_injective_storage_assignment(mapping):
    with pytest.raises(ValueError):
        compile_layout(_small_circuit(), standard_hardware(4, vacancies=2), mapping)


def test_exact_pair_reuse_reduces_transport_without_changing_gates_or_terminal():
    circuit = Circuit(4, (((0, 1), (2, 3)),) * 3)
    hardware = standard_hardware(4, vacancies=2)
    mapping = (0, 1, 2, 3)
    on = CompilerConfig(reuse=True, terminal="canonical")
    off = replace(on, reuse=False)
    reused = compile_layout(circuit, hardware, mapping, config=on)
    restored = compile_layout(circuit, hardware, mapping, config=off)
    assert reused.status == restored.status == "completed"
    assert reused.metrics["transport_groups"] < restored.metrics["transport_groups"]
    assert reused.metrics["reused_atoms"] > 0
    assert reused.final_positions == restored.final_positions == hardware.storage[:4]
    assert audit_result(circuit, hardware, mapping, reused, config=on)["status"] == "passed"
    assert audit_result(circuit, hardware, mapping, restored, config=off)["status"] == "passed"


def test_different_initial_layouts_share_explicit_canonical_terminal():
    circuit = _small_circuit()
    hardware = standard_hardware(4, vacancies=2)
    config = CompilerConfig(terminal="canonical")
    for mapping in ((0, 1, 2, 3), (5, 0, 4, 2)):
        result = compile_layout(circuit, hardware, mapping, config=config)
        assert result.status == "completed", result.error
        assert result.final_positions == hardware.storage[:4]
        assert audit_result(circuit, hardware, mapping, result, config=config)["status"] == "passed"


def test_empty_circuit_completes_without_fabricated_gates_or_transport():
    circuit = Circuit(4, ())
    hardware = standard_hardware(4, vacancies=2)
    mapping = (5, 0, 4, 2)
    result = compile_layout(circuit, hardware, mapping, config=CompilerConfig(terminal="storage"))
    assert result.status == "completed", result.error
    assert result.duration_us == 0
    assert result.trace == ()
    assert result.final_positions == tuple(hardware.storage[i] for i in mapping)
    assert audit_result(circuit, hardware, mapping, result)["status"] == "passed"


def test_policy_masks_used_sites_and_can_use_initial_vacancies():
    torch = pytest.importorskip("torch")
    from neutral_atom_strategies.placement_rl.policy import PlacementPolicy

    torch.manual_seed(11)
    actor = PlacementPolicy(hidden=16)
    circuit, hardware = _small_circuit(), standard_hardware(4, vacancies=2)
    used_vacancy = False
    for _ in range(16):
        mapping, logp, entropy = actor.sample(circuit, hardware)
        assert len(mapping) == len(set(mapping)) == circuit.n_qubits
        assert all(0 <= site < len(hardware.storage) for site in mapping)
        assert torch.isfinite(logp) and torch.isfinite(entropy)
        assert logp.requires_grad and entropy.requires_grad
        used_vacancy |= any(site >= circuit.n_qubits for site in mapping)
    assert used_vacancy
    with pytest.raises(ValueError):
        actor.sample(Circuit(7, ()), hardware)


def test_actor_and_adversary_have_separate_gradient_paths():
    torch = pytest.importorskip("torch")
    from neutral_atom_strategies.placement_rl.policy import PlacementPolicy, ScenarioAdversary
    from neutral_atom_strategies.placement_rl.game import default_scenarios, game_value

    torch.manual_seed(11)
    circuit, hardware = _small_circuit(), standard_hardware(4, vacancies=2)
    actor = PlacementPolicy(hidden=16)
    adversary = ScenarioAdversary(len(default_scenarios()), hidden=16)
    mapping, logp, _ = actor.sample(circuit, hardware)
    distribution = adversary.distribution(circuit, hardware, mapping)
    losses = torch.tensor([0.1, 0.5, -0.2, 0.3, -0.1])
    (game_value(losses, distribution.probs.detach()).detach() * logp).backward()
    assert any(p.grad is not None and torch.any(p.grad != 0) for p in actor.parameters())
    assert all(p.grad is None for p in adversary.parameters())
    actor.zero_grad(set_to_none=True)
    (-(distribution.probs * losses.detach()).sum()).backward()
    assert all(p.grad is None for p in actor.parameters())
    assert any(p.grad is not None and torch.any(p.grad != 0) for p in adversary.parameters())


def test_evaluator_caches_exact_scenarios_and_reference_costs():
    pytest.importorskip("torch")
    from neutral_atom_strategies.placement_rl.game import Evaluator, default_scenarios

    circuit, hardware = _small_circuit(), standard_hardware(4, vacancies=2)
    scenarios = default_scenarios()
    evaluator = Evaluator(circuit, hardware, scenarios, CompilerConfig(terminal="canonical"))
    mapping = (0, 1, 2, 3)
    costs = evaluator.costs(mapping)
    assert len(costs) == len(scenarios)
    assert all(0 < cost < float("inf") for cost in costs)
    assert evaluator.calls == len(scenarios)
    assert evaluator.costs(mapping) == costs
    assert evaluator.calls == len(scenarios)
    assert evaluator.losses(mapping, mapping).tolist() == [0.] * len(scenarios)


def test_failed_short_prefix_cannot_receive_favorable_loss(monkeypatch):
    pytest.importorskip("torch")
    from neutral_atom_strategies.placement_rl.game import Evaluator

    circuit, hardware = _small_circuit(), standard_hardware(4, vacancies=2)
    evaluator = Evaluator(circuit, hardware, (Scenario("nominal"),))
    reference, failed, slow = (0, 1, 2, 3), (3, 2, 1, 0), (1, 0, 3, 2)
    results = {
        reference: CompileResult("completed", 10., {}, (), hardware.storage[:4]),
        failed: CompileResult("failed", 0., {}, (), hardware.storage[:4], "budget"),
        slow: CompileResult("completed", 1e12, {}, (), hardware.storage[:4]),
    }
    monkeypatch.setattr(evaluator, "result", lambda mapping, _index: results[tuple(mapping)])
    assert evaluator.losses(failed, reference).item() == 2.
    assert evaluator.losses(slow, reference).item() < evaluator.losses(failed, reference).item()
    with pytest.raises(ValueError, match="Reference failed"):
        evaluator.losses(reference, failed)


def test_actual_learning_step_updates_both_networks():
    torch = pytest.importorskip("torch")
    from neutral_atom_strategies.placement_rl.policy import PlacementPolicy, ScenarioAdversary
    from neutral_atom_strategies.placement_rl.game import Evaluator, default_scenarios, learn_step

    torch.manual_seed(11)
    scenarios = default_scenarios()
    actor = PlacementPolicy(hidden=16)
    adversary = ScenarioAdversary(len(scenarios), hidden=16)
    actor_optimizer = torch.optim.Adam(actor.parameters(), lr=0.01)
    adversary_optimizer = torch.optim.Adam(adversary.parameters(), lr=0.01)
    evaluator = Evaluator(_small_circuit(), standard_hardware(4, vacancies=2), scenarios,
                          CompilerConfig(terminal="canonical"))
    actor_before = [p.detach().clone() for p in actor.parameters()]
    adversary_before = [p.detach().clone() for p in adversary.parameters()]
    report = learn_step(actor, adversary, actor_optimizer, adversary_optimizer, [evaluator],
                        actor_entropy=0., adversary_entropy=0.)
    assert report["records"] and evaluator.calls > 0
    assert any(not torch.equal(old, new) for old, new in zip(actor_before, actor.parameters()))
    assert any(not torch.equal(old, new) for old, new in zip(adversary_before, adversary.parameters()))
    assert torch.isfinite(torch.tensor(report["actor_loss"]))
    assert torch.isfinite(torch.tensor(report["adversary_loss"]))


def test_model_digest_uses_logical_tensor_bytes_without_numpy(monkeypatch):
    import hashlib
    import struct
    torch = pytest.importorskip('torch')
    from neutral_atom_experiments.rl_initial_placement import model_digest

    class Model:
        def state_dict(self):
            return {'weight': torch.arange(6, dtype=torch.float32).reshape(2, 3).T,
                    'scalar': torch.tensor(-0.0, dtype=torch.float32)}

    def unavailable(*args, **kwargs):
        raise RuntimeError('NumPy bridge is unavailable')

    monkeypatch.setattr(torch.Tensor, 'numpy', unavailable)
    expected = hashlib.sha256()
    expected.update(b'weight')
    expected.update(struct.pack('=6f', 0, 3, 1, 4, 2, 5))
    expected.update(b'scalar')
    expected.update(struct.pack('=f', -0.0))
    assert model_digest(Model()) == expected.hexdigest()


def test_training_runner_writes_complete_reviewable_report(tmp_path):
    pytest.importorskip("torch")
    from neutral_atom_experiments.rl_initial_placement import run

    config = dict(dataset_seed=20260922, seeds=[11], modes=["adversarial"],
                  qubits=4, depth=3, vacancies=2, train_cases=2, validation_cases=1,
                  test_cases=1, holdout_cases=1, updates=1, batch_size=1,
                  validation_interval=1, hidden=16, learning_rate=0.002,
                  adversary_learning_rate=0.003, nominal_share=0.25, search_budget=2,
                  compiler=dict(trials=2, queue_capacity=24, site_limit=4, reuse=True,
                                terminal="storage"))
    output = tmp_path / "pilot"
    result = run(config, output)
    assert len(result) == 1
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "completed"
    assert summary["physical_validation"] == "not_run"
    assert (output / "manifest.json").is_file()
    assert (output / "report.md").is_file()
    run_dir = output / "adversarial-seed-11"
    assert (run_dir / "checkpoint.pt").is_file()
    evaluation = json.loads((run_dir / "evaluation.json").read_text(encoding="utf-8"))
    assert {row["split"] for row in evaluation["cases"]} == {"test", "size_holdout"}
    for row in evaluation["cases"]:
        assert set(row["measurements"]) == {"identity", "interaction", "untrained_greedy",
                                             "trained_greedy", "random", "anneal", "trained_search"}
        for measure in row["measurements"].values():
            assert "worst_bounded_regret" in measure
            assert 1 <= measure["search"]["unique_layouts"] <= config["search_budget"]
    witnesses = list((run_dir / "witnesses").glob("*/*.json"))
    assert len(witnesses) == 30
    assert all(json.loads(path.read_text(encoding="utf-8"))["audit"]["status"] == "passed"
               for path in witnesses)

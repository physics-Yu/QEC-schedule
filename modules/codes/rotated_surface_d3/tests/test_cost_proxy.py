"""Scoped cost proxies never become quantum syndromes or logical success."""

from copy import deepcopy
from dataclasses import replace
from math import exp, prod

import pytest
from nadit_physical_compiler.activity import derive_activity
from nadit_physical_compiler.cost.noise import NoiseModel
from nadit_physical_compiler.provenance import canonical_hash

from modules.codes.rotated_surface_d3.probabilities.cost_proxy import (
    algorithm_proxy_port,
    factory_proxy_port,
)
from modules.physical_compiler.tests.test_cost import timeline_document


def scoped_report(*, stage="factory", params=None, included=None):
    """Actually clip source activity before evaluating the existing noise model."""
    document = timeline_document()
    source = derive_activity(document)
    included = [[0, 5], [15, 24]] if included is None else included
    excluded, cursor = [], 0
    for start, end in included:
        if cursor < start:
            excluded.append([cursor, start])
        cursor = end
    if cursor < source.duration_us:
        excluded.append([cursor, source.duration_us])

    def clip(intervals):
        return tuple(
            replace(
                interval,
                start_us=max(a, interval.start_us),
                end_us=min(b, interval.end_us),
            )
            for interval in intervals
            for a, b in included
            if max(a, interval.start_us) < min(b, interval.end_us)
        )

    selected = []
    for i, event in enumerate(source.events):
        for a, b in included:
            start, end = (
                max(a, event.start_us),
                min(b, event.start_us + event.duration_us),
            )
            if event.kind == "Wait" and start < end:
                selected.append(
                    (i, replace(event, start_us=start, duration_us=end - start))
                )
            elif a <= event.start_us and event.start_us + event.duration_us <= b:
                selected.append((i, event))
    indices = sorted({i for i, _ in selected})
    activity = replace(
        source,
        duration_us=sum(b - a for a, b in included),
        events=tuple(event for _, event in selected),
        per_atom=tuple(
            replace(atom, busy=clip(atom.busy), idle=clip(atom.idle))
            for atom in source.per_atom
        ),
    )
    report = NoiseModel().evaluate(activity, document, params or {})
    report.update(
        time_scope="disjoint_include_intervals",
        probability_kind="physical_no_fault_proxy",
        interval_selection={
            "schema": "nadit.physical_cost_intervals/1",
            "time_basis": "absolute_us",
            "include_intervals": included,
            "source_horizon_us": source.duration_us,
            "selected_duration_us": activity.duration_us,
            "selected_event_indices": indices,
            "event_index_map": [
                {
                    "selected_event_id": i,
                    "source_event_id": original,
                    "start_us": event.start_us,
                    "duration_us": event.duration_us,
                }
                for i, (original, event) in enumerate(selected)
            ],
            "source_activity_sha256": canonical_hash(source.document()),
            "selected_activity_sha256": canonical_hash(activity.document()),
            "exposure_partition": (
                "original_activity_interval_intersections_with_merged_include_intervals"
            ),
            "discrete_channels": "complete_action_ownership",
            "noise_profile": "independent_pauli_rates_v1",
            "full_trace_probability_equivalence_claimed": False,
        },
    )
    scope = {
        "scope_id": f"{stage}/attempt[0]",
        "stage": stage,
        "window_us": [0, 24],
        "included_intervals_us": included,
        "excluded_raw_intervals_us": excluded,
        "source_result_hash": report["result_hash"],
        "scoped_activity_hash": canonical_hash(activity.document()),
        "original_event_indices": indices,
        "action_boundaries_checked": True,
    }
    return report, scope


def test_real_scoped_cost_loss_is_counted_once_and_fidelity_is_not_used():
    report, scope = scoped_report(
        params={
            "single": {"probabilities": [0.1, 0, 0]},
            "transport": {"load_loss": 0.2, "store_loss": 0.3},
            "exposure": {"slm_t2_us": 100, "aod_t2_us": 100},
        }
    )
    noise = report["noise"]
    expected = prod(1 - sum(c["probabilities"]) for c in noise["channels"])
    expected *= prod(e["survival_probability"] for e in noise["loss"]["events"])
    assert expected != pytest.approx(report["metrics"]["fidelity"])
    assert noise["loss"]["all_atoms_survive_probability"] == pytest.approx(0.8 * 0.7)
    port = factory_proxy_port(report, scope)
    assert port.port_id == "rotated_surface_d3.factory_15_to_1.cost_proxy"
    assert port.outcome("accepted").probability == pytest.approx(expected)
    assert dict(port.outcome("accepted").values) == {
        "accepted": True,
        "proxy_no_fault": True,
    }
    assert port.branch("accepted").transition == "deliver"
    assert port.branch("rejected").transition == "retry"
    assert not port.branch("accepted").steps  # Output X belongs to the later scope.
    model = port.to_dict()["model"]
    assert model["kind"] == "estimated"
    assert model["evidence"]["logical_success_probability"] is None
    assert model["evidence"]["scope_sha256"] == canonical_hash(scope)
    assert model["evidence"]["noise_report_sha256"] == canonical_hash(report)
    assert (
        model["evidence"]["source_activity_sha256"]
        == report["interval_selection"]["source_activity_sha256"]
    )
    assert len(model["evidence"]["estimator_source_sha256"]) == 64
    assert report["interval_selection"]["selected_event_indices"] == [0, 1, 3, 4]
    assert all(c["kind"] != "Move" for c in noise["channels"])


def test_algorithm_outcomes_do_not_retry_or_claim_success():
    report, scope = scoped_report(stage="algorithm")
    report["caller_diagnostic"] = {"arbitrary": "allowed"}
    port = algorithm_proxy_port(report, scope)
    assert port.port_id == "rotated_surface_d3.algorithm.cost_proxy"
    assert [dict(o.values) for o in port.outcomes] == [
        {"proxy_success": True, "no_fault": True},
        {"proxy_success": False, "no_fault": False},
    ]
    assert all(b.transition == "continue" for b in port.branches)
    assert all(not b.steps for b in port.branches)
    assert all("logical_success" not in dict(o.values) for o in port.outcomes)


@pytest.mark.parametrize(
    "change",
    [
        {"scope_id": ""},
        {"stage": "algorithm"},
        {"window_us": [0, float("nan")]},
        {"window_us": [1, 24]},
        {"included_intervals_us": [[0, 6], [5, 24]]},
        {"included_intervals_us": [[0, 5], [0, 5]]},
        {"excluded_raw_intervals_us": [[4, 15]]},
        {"excluded_raw_intervals_us": [[5, 15], [5, 15]]},
        {"excluded_raw_intervals_us": [[5, 25]]},
        {"source_result_hash": "a" * 64},
        {"scoped_activity_hash": "b" * 64},
        {"original_event_indices": [0, 0]},
        {"action_boundaries_checked": 1},
    ],
)
def test_bad_scope_rejected(change):
    report, scope = scoped_report()
    scope.update(change)
    with pytest.raises(ValueError):
        factory_proxy_port(report, scope)


def test_missing_scope_and_unsliced_report_rejected():
    report, scope = scoped_report()
    with pytest.raises(ValueError):
        factory_proxy_port(report, {})
    del report["interval_selection"]
    with pytest.raises(ValueError, match="interval"):
        factory_proxy_port(report, scope)


def test_missing_raw_exclusion_leaves_an_unowned_gap_and_is_rejected():
    report, scope = scoped_report()
    scope["excluded_raw_intervals_us"] = []
    with pytest.raises(ValueError, match="cover|gap|partition"):
        factory_proxy_port(report, scope)


@pytest.mark.parametrize("stage", ["factory", "algorithm"])
def test_real_shortened_include_cannot_omit_the_rest_of_the_window(stage):
    report, scope = scoped_report(stage=stage, included=[[0, 5]])
    scope["excluded_raw_intervals_us"] = []
    producer = factory_proxy_port if stage == "factory" else algorithm_proxy_port
    with pytest.raises(ValueError, match="cover|gap|partition"):
        producer(report, scope)


def test_adjacent_raw_exclusions_cover_the_gap_without_losing_evidence():
    report, scope = scoped_report()
    scope["excluded_raw_intervals_us"] = [[5, 10], [10, 15]]
    port = factory_proxy_port(report, scope)
    assert port.to_dict()["model"]["evidence"]["scope"] == scope
    assert port.to_dict()["model"]["evidence"]["scope_sha256"] == canonical_hash(scope)


def test_algorithm_without_exclusions_owns_its_complete_window():
    report, scope = scoped_report(stage="algorithm", included=[[0, 24]])
    assert scope["excluded_raw_intervals_us"] == []
    port = algorithm_proxy_port(report, scope)
    assert port.outcome("no_fault").probability == 1


def test_zero_length_window_is_not_a_complete_proxy_segment():
    report, scope = scoped_report(included=[])
    scope["window_us"] = [0, 0]
    with pytest.raises(ValueError, match="positive|window"):
        factory_proxy_port(report, scope)


def test_real_wait_split_across_included_intervals_keeps_unique_source_indices():
    report, scope = scoped_report(
        included=[[0, 17], [18, 24]],
        params={"exposure": {"slm_t2_us": 100, "aod_t2_us": 100}},
    )
    selection = report["interval_selection"]
    assert selection["selected_event_indices"] == [0, 1, 2, 3, 4]
    assert len(selection["event_index_map"]) == 6
    assert selection["event_index_map"][-2:] == [
        {
            "selected_event_id": 4,
            "source_event_id": 4,
            "start_us": 15,
            "duration_us": 2,
        },
        {
            "selected_event_id": 5,
            "source_event_id": 4,
            "start_us": 18,
            "duration_us": 1,
        },
    ]
    port = factory_proxy_port(report, scope)
    assert port.outcome("accepted").probability == pytest.approx(
        report["metrics"]["no_fault_probability"]
    )
    assert all("kind" not in entry for entry in selection["event_index_map"])


@pytest.mark.parametrize(
    "mutation",
    [
        "same_interval",
        "overlap",
        "reverse_time",
        "zero_duration",
        "nonmonotonic_source",
        "noncontiguous_selected",
    ],
)
def test_invalid_repeated_source_piece_map_is_rejected(mutation):
    report, scope = scoped_report(included=[[0, 17], [18, 24]])
    rows = report["interval_selection"]["event_index_map"]
    if mutation == "same_interval":
        rows[-2].update(start_us=15, duration_us=1)
        rows[-1].update(start_us=16, duration_us=1)
    elif mutation == "overlap":
        rows[-1].update(start_us=16, duration_us=1)
    elif mutation == "reverse_time":
        rows[-2].update(start_us=18, duration_us=1)
        rows[-1].update(start_us=15, duration_us=2)
    elif mutation == "zero_duration":
        rows[-1]["duration_us"] = 0
    elif mutation == "nonmonotonic_source":
        rows[0]["source_event_id"], rows[1]["source_event_id"] = 1, 0
    else:
        rows[-1]["selected_event_id"] = 7
    with pytest.raises(ValueError):
        factory_proxy_port(report, scope)


@pytest.mark.parametrize(
    "key,value",
    [
        ("include_intervals", [[0, 24]]),
        ("selected_duration_us", 24),
        ("source_horizon_us", 23),
        ("selected_event_indices", [0, 1]),
        ("selected_activity_sha256", "c" * 64),
        ("source_activity_sha256", "bad"),
        ("exposure_partition", "repartition_as_needed"),
        ("full_trace_probability_equivalence_claimed", True),
        ("noise_profile", "native_channel"),
        ("event_index_map", []),
    ],
)
def test_cross_checked_selection_tamper_rejected(key, value):
    report, scope = scoped_report()
    report["interval_selection"][key] = value
    with pytest.raises(ValueError):
        factory_proxy_port(report, scope)


@pytest.mark.parametrize(
    "path,value",
    [
        (("params_hash",), "a" * 64),
        (("metrics", "no_fault_probability"), 0.7),
        (("metrics", "no_fault_probability"), float("nan")),
        (("noise", "loss", "all_atoms_survive_probability"), 0.1),
        (("noise", "upstream_records"), {"native": {}}),
        (("noise", "gate_diagnostics"), [{"computational_survival_probability": 0.8}]),
        (("time_scope",), "whole_trace"),
        (("probability_kind",), "logical_success"),
    ],
)
def test_bad_report_rejected(path, value):
    report, scope = scoped_report()
    target = report
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        factory_proxy_port(report, scope)


@pytest.mark.parametrize("gate", ["single", "cz", "override"])
def test_non_pauli_config_rejected_even_with_matching_hash(gate):
    report, scope = scoped_report()
    if gate == "override":
        report["params"]["single_overrides"] = {"Z": {"backend": "ideal"}}
    else:
        report["params"][gate] = {"backend": "ideal"}
    from nadit_physical_compiler.cost.noise.config import resolve

    report["params"] = resolve(report["params"])
    report["params_hash"] = canonical_hash(report["params"])
    with pytest.raises(ValueError, match="Pauli"):
        factory_proxy_port(report, scope)


def test_channel_probability_tamper_and_out_of_scope_exposure_rejected():
    original, scope = scoped_report(params={"single": {"probabilities": [0.1, 0, 0]}})
    for change in (
        {"probabilities": [1.1, 0, 0]},
        {"probabilities": [0.2, 0, 0]},
        {"start_us": 10},
        {"instruction": "KRAUS"},
    ):
        report = deepcopy(original)
        report["noise"]["channels"][0].update(change)
        with pytest.raises(ValueError):
            factory_proxy_port(report, scope)


def test_t2_probability_uses_frozen_intersections_not_full_trace_equivalence():
    report, scope = scoped_report(
        params={"exposure": {"slm_t2_us": 100, "aod_t2_us": 100}}
    )
    port = factory_proxy_port(report, scope)
    channels = report["noise"]["channels"]
    expected = prod((1 + exp(-c["duration_us"] / 100)) / 2 for c in channels)
    assert port.outcome("accepted").probability == pytest.approx(expected)
    # Splitting one idle channel introduces a different 'no fault at every slice'
    # event, although the composed dephasing channel describes the same memory.
    assert ((1 + exp(-10 / 100)) / 2) ** 2 != pytest.approx((1 + exp(-20 / 100)) / 2)
    evidence = port.to_dict()["model"]["evidence"]
    assert evidence["full_trace_probability_equivalence_claimed"] is False
    assert (
        evidence["exposure_partition"]
        == report["interval_selection"]["exposure_partition"]
    )


def test_certain_loss_and_immutable_port():
    report, scope = scoped_report(params={"transport": {"load_loss": 1}})
    port = factory_proxy_port(report, scope)
    assert port.outcome("accepted").probability == 0
    original_hash = port.content_sha256
    scope["scope_id"] = "changed"
    report["metrics"]["no_fault_probability"] = 1
    assert port.content_sha256 == original_hash

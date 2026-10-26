"""Current-schedule interval composition, rather than scalar component products."""

from copy import deepcopy
from math import exp, log

import pytest

from modules.codes.rotated_surface_d3.protocols.fast_cost import (
    FastCostCall,
    evaluate_factory_cost,
    factory_probability_port,
)
from modules.codes.rotated_surface_d3.protocols.fast_profile import (
    FastProfile,
    make_fast_layout,
)
from modules.codes.rotated_surface_d3.tests.test_fast_profile import profile_document


def setup():
    document = profile_document()
    document["noise_params"]["exposure"]["slm_t2_us"] = 100
    profile = FastProfile.from_dict(document)
    layout = make_fast_layout(profile, 2)
    patch = layout.factories[0].bindings["W1"]
    return profile, layout, FastCostCall("x", "logical_x", (patch,), 0)


def survival(duration):
    return (1 + exp(-duration / 100)) / 2


def test_idle_partitions_join_across_calls_and_preserve_reference_model():
    profile, layout, call = setup()
    result = evaluate_factory_cost(
        profile,
        [call],
        layout=layout,
        factory_id="factory0",
        window=(0, 10),
        raw_horizons=[],
    )
    expected = exp(-0.01) * survival(9) * survival(10) ** 101
    assert result["metrics"]["no_fault_probability"] == pytest.approx(
        expected, rel=1e-12
    )
    assert result["physical_validation_run"] is False


def test_own_raw_union_clips_each_original_idle_interval():
    profile, layout, call = setup()
    result = evaluate_factory_cost(
        profile,
        [call],
        layout=layout,
        factory_id="factory0",
        window=(0, 10),
        raw_horizons=[(3, 5), (4, 7)],
    )
    expected = exp(-0.01) * survival(2) * survival(3) * (survival(3) ** 2) ** 101
    assert result["metrics"]["no_fault_probability"] == pytest.approx(
        expected, rel=1e-12
    )
    assert result["excluded_raw_intervals_us"] == [[3, 7]]
    assert result["metrics"]["no_fault_probability"] != pytest.approx(
        exp(-0.01) * survival(5) * survival(6) ** 101, rel=1e-5
    )


def test_discrete_channels_cannot_be_fractionally_clipped():
    profile, layout, call = setup()
    with pytest.raises(ValueError, match="STRADDLES"):
        evaluate_factory_cost(
            profile,
            [call],
            layout=layout,
            factory_id="factory0",
            window=(0, 10),
            raw_horizons=[(0.5, 3)],
        )


def test_factory_port_uses_current_cost_and_does_not_claim_physical_execution():
    profile, layout, call = setup()
    port = profile.factory_port(
        [call], layout=layout, factory_id="factory0", window=(0, 10), raw_horizons=[]
    )
    assert port.to_dict()["model"]["kind"] == "estimated"
    assert port.to_dict()["model"]["evidence"]["physical_validation_run"] is False
    assert port.outcome("accepted").probability < 1


def test_full_line_diagnostic_retains_raw_windows_and_successful_patch_waits():
    profile, layout, call = setup()
    result = evaluate_factory_cost(
        profile,
        [call],
        layout=layout,
        factory_id="factory0",
        window=(0, 10),
        raw_horizons=[(3, 5), (4, 7)],
        scope="full_line_diagnostic",
    )
    expected = exp(-0.01) * survival(9) * survival(10) ** 101
    assert result["metrics"]["no_fault_probability"] == pytest.approx(expected)
    assert result["included_intervals_us"] == [[0, 10]]
    assert result["excluded_raw_intervals_us"] == []
    assert result["raw_attempt_union_us"] == [[3, 7]]
    assert result["controls_factory_acceptance"] is False
    assert result["coverage"]["raw_activity_included"] is True
    assert result["coverage"]["physical_loss_events_sampled"] is False
    patches = result["exposure_by_patch"]
    assert sum(p["included_role_time_us"] for p in patches.values()) == 1020
    assert sum(p["raw_window_role_time_us"] for p in patches.values()) == 408
    assert patches["factory0/W1"]["raw_window_role_time_us"] == 68
    assert patches["factory0/W1"]["log_dephasing"] == pytest.approx(
        log(survival(9)) + 16 * log(survival(10))
    )


def test_raw_transport_loss_is_in_diagnostic_without_a_second_probability_draw():
    document = profile_document()
    document["noise_params"]["transport"].update(
        slm_loss_per_us=0.001, aod_loss_per_us=0.002
    )
    raw = deepcopy(document["entries"]["logical_x"])
    raw.update(
        component_id="raw_t_postselection",
        phase_durations_us=[1, 1, 1],
        events=[
            {
                "offset_us": offset,
                "duration_us": 1,
                "kind": kind,
                "log_survival": log(0.99),
            }
            for offset, kind in enumerate(("Load", "Move", "Store"))
        ],
        busy=[
            [0, 0, 0, 1, "Load", "slm"],
            [0, 0, 1, 1, "Move", "aod"],
            [0, 0, 2, 1, "Store", "aod"],
        ],
    )
    document["entries"]["raw"] = raw
    profile = FastProfile.from_dict(document)
    layout = make_fast_layout(profile, 1)
    patches = layout.factories[0].bindings
    calls = [
        FastCostCall("accepted_patch", "logical_x", (patches["W1"],), 0),
        FastCostCall("peer_raw_retry", "raw_t_postselection", (patches["W2"],), 3),
    ]
    arguments = {
        "layout": layout,
        "factory_id": "factory0",
        "window": (0, 10),
        "raw_horizons": [(3, 7)],
    }
    result = evaluate_factory_cost(
        profile, calls, **arguments, scope="full_line_diagnostic"
    )
    legacy = evaluate_factory_cost(profile, calls, **arguments)
    assert result["metrics"]["log_contributions"] == pytest.approx(
        {
            "discrete": -0.01 + 3 * log(0.99),
            "holder_residence": -(1018 * 0.001 + 2 * 0.002),
            "dephasing": 0,
        }
    )
    assert legacy["metrics"]["log_contributions"] == pytest.approx(
        {
            "discrete": -0.01,
            "holder_residence": -612 * 0.001,
            "dephasing": 0,
        }
    )
    assert result["selected_discrete_events"] == 4
    assert legacy["selected_discrete_events"] == 1
    assert result["coverage"]["raw_physical_loss_included"] is True
    assert legacy["coverage"]["raw_physical_loss_included"] is False
    assert result["exposure_by_patch"]["factory0/W2"]["holder_role_time_us"] == {
        "slm": 168,
        "aod": 2,
    }
    assert result["logical_success_probability"] is None
    with pytest.raises(
        ValueError, match="DIAGNOSTIC_CANNOT_CONTROL_FACTORY_ACCEPTANCE"
    ):
        factory_probability_port(profile, result)


@pytest.mark.parametrize(
    ("scope", "horizons", "error"),
    [
        ("all", [], "INVALID_FAST_COST_SCOPE"),
        ("full_line_diagnostic", [(-1, 2)], "INVALID_FAST_COST_TIME"),
        ("full_line_diagnostic", [(2, 11)], "INVALID_FAST_RAW_HORIZON"),
    ],
)
def test_diagnostic_scope_and_raw_provenance_are_validated(scope, horizons, error):
    profile, layout, call = setup()
    with pytest.raises(ValueError, match=error):
        evaluate_factory_cost(
            profile,
            [call],
            layout=layout,
            factory_id="factory0",
            window=(0, 10),
            raw_horizons=horizons,
            scope=scope,
        )

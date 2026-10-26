"""Theoretical distillation checks are distinct from physical cost diagnostics."""

from copy import deepcopy

import pytest

from modules.codes.rotated_surface_d3.probabilities.factory import factory_mx_port
from modules.codes.rotated_surface_d3.protocols.fast_profile import FastProfile
from modules.logical_compiler.examples.factory_fast import run_fast
from modules.logical_compiler.tests.test_fast_experiment_review import (
    _complete_document,
)


def _run(p, document=None, seed=0):
    return run_fast(
        FastProfile.from_dict(document or _complete_document()),
        code="rotated_surface_d3",
        seed=seed,
        input_z_error=p,
    )


@pytest.mark.parametrize("p", [0.0, 0.001, 0.01])
def test_reference_final_checks_and_output_quality_share_one_joint_model(p):
    run = _run(p)
    assert run.summary["execution_completed"]
    assert run.summary["experiment_model"]["mode"] == "theory"
    assert run.ledger["factory_acceptance_kind"] == "theoretical_iid_z"
    reference = factory_mx_port(input_z_error=p)
    expected = reference.to_dict()["model"]["evidence"]
    assert expected["acceptance_probability"] == pytest.approx(
        (1 + 15 * (1 - 2 * p) ** 8) / 16
    )
    checks = [
        e for e in run.case["events"] if e["occurrence"]["port_id"] == reference.port_id
    ]
    assert len(checks) == 2
    for event in checks:
        assert event["port_sha256"] == reference.content_sha256
        assert event["values"]["accepted"] == all(
            event["values"][f"m_w{i}"] == 0 for i in range(2, 6)
        )
    assert run.summary["outputs"] == sum(e["values"]["accepted"] for e in checks)
    for line in run.ledger["lines"].values():
        assert (
            line["factory_acceptance_probability"] == expected["acceptance_probability"]
        )
        assert (
            line["conditional_output_z_error"] == expected["conditional_output_z_error"]
        )
    if p == 0:
        assert run.summary["outputs"] == 2
    for token in run.case["resources"]["tokens"]:
        quality = token["quality"]
        expected_p = (
            expected["conditional_output_z_error"]
            if token["status"] == "offered"
            else p
        )
        assert quality["consumption_parameters"]["input_z_error"] == expected_p


def test_cost_failure_cannot_reject_theory_and_raw_retries_still_replay():
    first_doc = _complete_document()
    second_doc = deepcopy(first_doc)
    second_doc["noise_params"]["transport"]["slm_loss_per_us"] = 10
    first, second = _run(0.01, first_doc), _run(0.01, second_doc)
    replay = _run(0.01, first_doc)
    assert first.case == replay.case
    assert first.ledger["counts"] == second.ledger["counts"]
    assert first.ledger["counts"]["raw_rejections"] > 0
    assert (
        first.ledger["counts"]["raw_attempts"]
        == 30 + first.ledger["counts"]["raw_rejections"]
    )
    assert (
        first.summary["factory_acceptance_probabilities"]
        == second.summary["factory_acceptance_probabilities"]
    )
    for line, rows in second.reports.items():
        for event_id, row in rows["factory"].items():
            assert row["report"]["metrics"]["no_fault_probability"] == 0
            assert row["report"]["controls_factory_acceptance"] is False
            assert (
                first.reports[line]["factory"][event_id]["report"]["metrics"][
                    "no_fault_probability"
                ]
                > 0
            )
    assert first.summary["outputs"] > 0


def test_theory_requires_explicit_p_and_legacy_proxy_is_opt_in():
    profile = FastProfile.from_dict(_complete_document())
    with pytest.raises(ValueError, match="input_z_error|INPUT_Z_ERROR"):
        run_fast(profile, code="rotated_surface_d3", seed=0)
    legacy = run_fast(
        profile,
        code="rotated_surface_d3",
        seed=1,
        acceptance_model="physical_no_fault_proxy",
    )
    assert legacy.summary["case_id"] == "factory-array-cost-proxy-v1"
    assert legacy.ledger["factory_acceptance_kind"] == "profile_estimate_no_fault_proxy"

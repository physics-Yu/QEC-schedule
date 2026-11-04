"""Theoretical distillation checks are distinct from physical cost diagnostics."""

from copy import deepcopy

from modules.codes.rotated_surface_d3.protocols.fast_profile import FastProfile
from modules.logical_compiler.examples.factory_fast import run_fast
from modules.logical_compiler.tests.fast_profile_fixtures import (
    _complete_document,
)


def _run(p, document=None, seed=0):
    return run_fast(
        FastProfile.from_dict(document or _complete_document()),
        code="rotated_surface_d3",
        seed=seed,
        input_z_error=p,
    )


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

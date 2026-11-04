"""Compare completed logical and physical case evidence without executing either.

This readback checks protocol decisions, schedules and resource lifetimes.
Probability differences remain a separate model comparison. Matching schedules
do not validate a logical estimate's geometry, quantum state or noise accuracy.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from math import isfinite
from typing import Any

from nadit_physical_compiler.cost.noise.config import resolve as resolve_noise
from nadit_physical_compiler.provenance import canonical_hash


def _plain(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))


def _calls(case: Mapping[str, Any], *, logical: bool) -> list[dict[str, Any]]:
    timings = {
        record["invocation_id"]: record
        for record in (
            case["execution"]["calls"] if logical else case["physical"]["parts"]
        )
    }
    records = []
    for call in case["calls"]:
        roles = case["factories"][call["factory_id"]]["role_bindings"]
        sources = (call["invocation_id"],) if logical else call["part_invocations"]
        records.append(
            {
                "invocation_id": call["invocation_id"],
                "component_id": call["component_id"],
                "participant_blocks": [
                    roles[role] for role in call["participant_roles"]
                ],
                "start_us": call["start_us"],
                "end_us": call["end_us"],
                "results_ready_us": max(
                    timings[identity]["results_ready_us"] for identity in sources
                ),
                "after_calls": call["after_calls"],
                "event_dependencies": call["event_dependencies"],
                "consumed_token_id": call["consumed_token_id"],
            }
        )
    return records


def _events(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    keys = (
        "occurrence",
        "outcome_key",
        "values",
        "branch_id",
        "transition",
        "available_at_us",
        "released_at_us",
    )
    return [
        {
            **{key: event[key] for key in keys},
            "uniform_evidence": {
                "exported": "uniform" in event,
                "value": event.get("uniform"),
            },
        }
        for event in case["events"]
    ]


def _added_defaults(
    raw: Mapping[str, Any], resolved: Mapping[str, Any], path: str = "noise_params"
) -> list[dict[str, Any]]:
    additions: list[dict[str, Any]] = []
    for key, value in resolved.items():
        location = path + "." + key
        if key not in raw:
            additions.append({"path": location, "value": value})
        elif isinstance(raw[key], Mapping) and isinstance(value, Mapping):
            additions.extend(_added_defaults(raw[key], value, location))
    return additions


def _normalize_inputs(
    identity: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized: dict[str, Any] = _plain(identity)
    evidence: dict[str, Any] = {}
    for name, line in normalized.items():
        parameters = line["reference_parameters"]
        if parameters.get("noise_model") != "noise/v1":
            continue
        raw = parameters["noise_params"]
        resolved = resolve_noise(raw)
        evidence[name] = {
            "resolver": "nadit_physical_compiler.cost.noise.config.resolve",
            "noise_model": "noise/v1",
            "raw_sha256": canonical_hash(raw),
            "resolved_sha256": canonical_hash(resolved),
            "defaults_added": _added_defaults(raw, resolved),
            "resolved_noise_params": resolved,
        }
        parameters["noise_params"] = resolved
    return normalized, evidence


def _lifetimes(value: Any) -> Any:
    ignored = {
        "quality",
        "provenance",
        "atom_ids",
        "representation",
        "resource_time_basis",
    }
    if isinstance(value, Mapping):
        return {
            key: _lifetimes(item) for key, item in value.items() if key not in ignored
        }
    if isinstance(value, list):
        return [_lifetimes(item) for item in value]
    return value


def _sections(case: Mapping[str, Any], *, logical: bool) -> dict[str, Any]:
    return {
        "calls": _calls(case, logical=logical),
        "events": _events(case),
        "admissions": [
            {
                "members": [node["id"] for node in admission["nodes"]],
                "start_us": admission["start_us"],
            }
            for admission in case["component_schedule"]["admissions"]
        ],
        "resources": {
            key: _lifetimes(case["resources"][key])
            for key in ("carriers", "tokens", "audit")
        },
        "outcomes": {
            "status": case["status"],
            "duration_us": case["duration_us"],
            "factories": {
                name: {
                    key: line[key]
                    for key in (
                        "status",
                        "output_token_id",
                        "algorithm_consumed_token_id",
                        "completed_at_us",
                    )
                }
                for name, line in case["factories"].items()
            },
        },
    }


def _compare(fast: Any, physical: Any, tolerance: float) -> dict[str, Any]:
    differences: list[dict[str, Any]] = []
    count, maximum = 0, 0.0

    def mismatch(path: str, left: Any, right: Any) -> None:
        nonlocal count
        count += 1
        if len(differences) < 20:
            differences.append({"path": path, "fast": left, "physical": right})

    def visit(left: Any, right: Any, path: str, field: str = "") -> None:
        nonlocal maximum
        if isinstance(left, dict) and isinstance(right, dict):
            if left.keys() != right.keys():
                mismatch(path + ".keys", sorted(left), sorted(right))
            for key in sorted(left.keys() & right.keys()):
                visit(left[key], right[key], path + "." + key, key)
        elif isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                mismatch(path + ".length", len(left), len(right))
            for index, (a, b) in enumerate(zip(left, right, strict=False)):
                visit(a, b, f"{path}[{index}]", field)
        elif (
            field.endswith("_us")
            and type(left) in (int, float)
            and type(right) in (int, float)
        ):
            delta = abs(float(left) - float(right))
            maximum = max(maximum, delta)
            if delta > tolerance:
                mismatch(path, left, right)
        elif left != right:
            mismatch(path, left, right)

    visit(_plain(fast), _plain(physical), "$")
    return {
        "matches": count == 0,
        "difference_count": count,
        "max_abs_timing_delta_us": maximum,
        "first_differences": differences,
    }


def _distributions(case: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    result = {}
    for event in case["events"]:
        identity = json.dumps(
            event["occurrence"], sort_keys=True, separators=(",", ":")
        )
        model = case["probability_models"][event["port_sha256"]]
        result[identity] = {
            outcome["key"]: float(outcome["probability"])
            for outcome in model["outcomes"]
        }
    return result


def _probability_delta(
    fast: Mapping[str, float], physical: Mapping[str, float]
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = [
        {
            "key": key,
            "fast": fast[key],
            "physical": physical[key],
            "delta": fast[key] - physical[key],
        }
        for key in sorted(fast.keys() & physical.keys())
    ]
    return {
        "compared": len(rows),
        "max_abs_delta": max((abs(row["delta"]) for row in rows), default=None),
        "missing_in_fast": sorted(physical.keys() - fast.keys()),
        "missing_in_physical": sorted(fast.keys() - physical.keys()),
        "values": rows,
    }


def _cost_probabilities(value: Any, path: str = "$") -> dict[str, float]:
    probabilities: dict[str, float] = {}
    if isinstance(value, Mapping):
        for key, item in value.items():
            location = path + "." + key
            if key in (
                "no_fault_probability",
                "acceptance_probability",
                "all_atoms_survive_probability",
            ) and type(item) in (int, float):
                probabilities[location] = float(item)
            else:
                probabilities.update(_cost_probabilities(item, location))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            probabilities.update(_cost_probabilities(item, f"{path}[{index}]"))
    return probabilities


def compare_fast_physical(
    fast_case: Mapping[str, Any],
    physical_case: Mapping[str, Any],
    *,
    fast_cost_reports: Mapping[str, Any] | None = None,
    physical_cost_reports: Mapping[str, Any] | None = None,
    timing_tolerance_us: float = 0.0,
) -> dict[str, Any]:
    """Return an auditable comparison; never compile, resample or fill gaps.

    Input case and seed identities must match. The clock tolerance is explicit
    and defaults to exact equality. Different physical part decomposition,
    quality/provenance records and atom footprints are intentionally excluded
    from protocol comparison. Full outcome distributions are compared separately.
    """
    if (
        type(timing_tolerance_us) not in (int, float)
        or not isfinite(timing_tolerance_us)
        or timing_tolerance_us < 0
    ):
        raise ValueError("INVALID_ACCEPTANCE_TIME_TOLERANCE")
    if (
        fast_case["case_id"] != physical_case["case_id"]
        or fast_case["seed"] != physical_case["seed"]
    ):
        raise ValueError("ACCEPTANCE_CASE_IDENTITY_MISMATCH")
    if (
        fast_case.get("execution_representation") != "logical_estimate"
        or fast_case.get("physical") is not None
        or physical_case.get("physical") is None
    ):
        raise ValueError("ACCEPTANCE_REQUIRES_LOGICAL_AND_PHYSICAL_CASES")
    if set(fast_case["factories"]) != set(physical_case["factories"]):
        raise ValueError("ACCEPTANCE_FACTORY_SET_MISMATCH")

    def identity(case: Mapping[str, Any]) -> dict[str, Any]:
        return {
            name: {
                key: line[key]
                for key in (
                    "code",
                    "recipe",
                    "limits",
                    "reference_parameters",
                    "role_bindings",
                )
            }
            for name, line in case["factories"].items()
        }

    fast_identity, physical_identity = identity(fast_case), identity(physical_case)
    inputs = _compare(fast_identity, physical_identity, 0)
    fast_normalized, fast_normalization = _normalize_inputs(fast_identity)
    physical_normalized, physical_normalization = _normalize_inputs(physical_identity)
    semantic_inputs = _compare(fast_normalized, physical_normalized, 0)
    left, right = (
        _sections(fast_case, logical=True),
        _sections(physical_case, logical=False),
    )
    comparisons = {
        key: _compare(left[key], right[key], timing_tolerance_us) for key in left
    }
    fast_prob, physical_prob = _distributions(fast_case), _distributions(physical_case)
    probabilities = {
        key: _probability_delta(fast_prob[key], physical_prob[key])
        for key in sorted(fast_prob.keys() & physical_prob.keys())
    }
    return {
        "schema": "nadit.fast_physical_comparison/1",
        "case_id": fast_case["case_id"],
        "seed": fast_case["seed"],
        "fast_case_sha256": canonical_hash(fast_case),
        "physical_case_sha256": canonical_hash(physical_case),
        "timing_tolerance_us": float(timing_tolerance_us),
        "input_compatibility": inputs,
        "semantic_input_compatibility": semantic_inputs,
        "noise_parameter_normalization": {
            "fast": fast_normalization,
            "physical": physical_normalization,
        },
        "uniform_evidence": {
            "source": "exported_event_uniform_only",
            "reconstructed": False,
            "fast_exported": sum("uniform" in event for event in fast_case["events"]),
            "physical_exported": sum(
                "uniform" in event for event in physical_case["events"]
            ),
            "fast_missing": sum(
                "uniform" not in event for event in fast_case["events"]
            ),
            "physical_missing": sum(
                "uniform" not in event for event in physical_case["events"]
            ),
        },
        "semantic_schedule_matches": semantic_inputs["matches"]
        and all(row["matches"] for row in comparisons.values()),
        "comparisons": comparisons,
        "event_probability_comparison": {
            "events": probabilities,
            "missing_in_fast": sorted(physical_prob.keys() - fast_prob.keys()),
            "missing_in_physical": sorted(fast_prob.keys() - physical_prob.keys()),
        },
        "cost_probability_comparison": None
        if fast_cost_reports is None or physical_cost_reports is None
        else _probability_delta(
            _cost_probabilities(fast_cost_reports),
            _cost_probabilities(physical_cost_reports),
        ),
        "physical_baseline_validation_ok": physical_case["physical"]
        .get("validation", {})
        .get("ok"),
        "fast_physical_validation": "not_run",
        "logical_success": None,
        "probability_agreement_included_in_schedule_verdict": False,
    }

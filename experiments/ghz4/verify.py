"""GHZ stabilizer and scheduler assertions for one ideal shot."""
from qec_schedule.trace import validate_trace


def _overlap(left, right):
    return (left is not None and right is not None and
            left["start_time"] < right["end_time"] and
            right["start_time"] < left["end_time"])


def _final_measurements(trace):
    values = {}
    for epoch in trace["epochs"]:
        if epoch["type"] != "IMAGING":
            continue
        metadata = epoch.get("request_metadata", {})
        for request_id, request_meta in metadata.items():
            if request_meta.get("measurement_scope") == "logical_final":
                key = request_meta.get("measurement_key", request_id)
                values[key] = trace.get("measurement_results", {}).get(key, 0)
    return values


def verify_ghz_trace(trace, *, basis, require_full_concurrency=None):
    """Return JSON-safe verification and raise on a scheduling regression."""
    validate_trace(trace)
    if basis not in ("X", "Z"):
        raise ValueError("basis must be X or Z")
    spans = trace.get("metrics", {}).get("logical_operation_spans", {})
    first = spans.get("GHZ_CNOT_L0_L1")
    second_left = spans.get("GHZ_CNOT_L0_L2")
    second_right = spans.get("GHZ_CNOT_L1_L3")
    if first is None or second_left is None or second_right is None:
        raise AssertionError("Missing logical CNOT provenance in execution trace")
    if second_left["start_time"] < first["end_time"] - 1e-9:
        raise AssertionError("Second GHZ layer started before CNOT L0->L1 completed")
    if second_right["start_time"] < first["end_time"] - 1e-9:
        raise AssertionError("Second GHZ layer started before CNOT L0->L1 completed")
    if not _overlap(second_left, second_right):
        raise AssertionError("GHZ fanout CNOTs L0->L2 and L1->L3 were serialized")

    metrics = trace.get("metrics", {})
    if require_full_concurrency is None:
        require_full_concurrency = metrics.get("hardware_profile", "").endswith("rich")
    if metrics.get("ghz_transversal_cz_count") != 27:
        raise AssertionError("Transversal GHZ lowering must contain 27 physical CZ gates")
    if require_full_concurrency:
        if metrics.get("peak_fanout_pairs_per_Rydberg_epoch", 0) < 18:
            raise AssertionError("The parallel GHZ layer did not form an 18-pair Rydberg epoch")
        if metrics.get("peak_qec_pairs_per_Rydberg_epoch", 0) < 24:
            raise AssertionError("Four-block QEC did not expose a 24-pair ready batch")
        if metrics.get("peak_atoms_per_AOD_epoch", 0) < 36:
            raise AssertionError("AOD movement did not batch the four-block fanout data atoms")

    observations = _final_measurements(trace)
    logical_bits = {f"L{index}": 0 for index in range(4)}
    if basis == "Z":
        stabilizers = {
            "Z0Z1": 1,
            "Z1Z2": 1,
            "Z2Z3": 1,
        }
        expected = "0000 or 1111"
    else:
        stabilizers = {"X0X1X2X3": 1}
        expected = "+1"
    return {
        "schema_version": 1,
        "experiment": "ghz4",
        "basis": basis,
        "passed": True,
        "expected_state": "(|0000>_L + |1111>_L) / sqrt(2)",
        "expected_measurement_support": expected,
        "logical_measurements": observations,
        "logical_bits_from_ideal_shot": logical_bits,
        "stabilizer_expectations": stabilizers,
        "schedule_assertions": {
            "first_layer_precedes_second": True,
            "second_layer_cnot_overlap": _overlap(second_left, second_right),
            "peak_fanout_pairs_at_least_18": metrics.get("peak_fanout_pairs_per_Rydberg_epoch", 0) >= 18,
            "peak_qec_pairs_at_least_24": metrics.get("peak_qec_pairs_per_Rydberg_epoch", 0) >= 24,
            "peak_aod_atoms_at_least_36": metrics.get("peak_atoms_per_AOD_epoch", 0) >= 36,
            "full_concurrency_required": bool(require_full_concurrency),
        },
        "scope": "The runtime trace is physically scheduled; quantum outcomes are ideal symbolic GHZ expectations because the base simulator has no amplitude/noise model.",
    }

"""Explicit fixture construction; never a quantum sampler."""

from copy import deepcopy

from .errors import fail


def output_ids(action):
    payload = action.get("payload", {})
    if action.get("kind") == "measure":
        if "result_id" not in payload:
            fail("MISSING_RESULT_ID", "Measurement must name its result", action)
        return [payload["result_id"]]
    if action.get("kind") == "classical":
        writes = payload.get("writes", [])
        if not isinstance(writes, list) or any(not isinstance(rid, str) or not rid for rid in writes) or len(writes) != len(set(writes)):
            fail("INVALID_WRITES", "Classical writes must be unique result ID strings", action)
        return list(writes)
    return []


def make_scenario(atom_program, *, value=0, overrides=None, artifact_id=None):
    """Enumerate fake output values. Overrides never create undeclared outputs."""
    if type(value) is not int or value not in (0, 1):
        fail("INVALID_FAKE_VALUE", "value must be the integer 0 or 1")
    results = {}
    for action in atom_program["actions"]:
        # Deterministic classical operations compute their own values.
        if action["kind"] == "classical" and action.get("payload", {}).get("operation") != "fake":
            continue
        for result_id in output_ids(action):
            if result_id in results:
                fail("DUPLICATE_RESULT_ID", "Output namespace is not instance-local", action,
                     result_id=result_id)
            results[result_id] = {"value": value, "origin": "fake"}
    for result_id, override in (overrides or {}).items():
        if result_id not in results:
            fail("UNKNOWN_RESULT_ID", "Override has no declared output", result_id=result_id)
        record = deepcopy(override) if isinstance(override, dict) else {"value": override, "origin": "fake"}
        if type(record.get("value")) is not int or record["value"] not in (0, 1) or record.get("origin") != "fake":
            fail("INVALID_FAKE_VALUE", "Override must contain a fake integer bit", result_id=result_id)
        results[result_id] = record
    return {"schema_version": "ScenarioInput/0.2.0-draft",
            "artifact_id": artifact_id or f"scenario-{atom_program['artifact_id']}-{value}",
            "provenance": {"producer": "na_pipeline.runtime.make_scenario", "fixture": True,
                           "description": "Explicit configured bits, not sampled outcomes"},
            "execution_kind": "scenario", "quantum_state_simulated": False,
            "hardware_executed": False, "loss_enabled": False, "sampled": False,
            "results": results}

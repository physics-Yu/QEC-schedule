"""Explicit fake scenarios; this module never predicts a quantum outcome."""

def make_scenario(atom_program: dict, *, value: int = 0, artifact_id: str | None = None) -> dict:
    if type(value) is not int or value not in (0, 1):
        raise ValueError("fake scenario value must be integer 0 or 1")
    results = {}
    for action in atom_program["actions"]:
        if action["kind"] != "measure":
            continue
        result_id = action["payload"]["result_id"]
        if not isinstance(result_id, str) or not result_id or result_id in results:
            raise ValueError(f"invalid or reused measurement result_id: {result_id!r}")
        results[result_id] = {"value": value, "origin": "fake"}
    return {
        "schema_version": "ScenarioInput/0.2.0-draft",
        "artifact_id": artifact_id or f"{atom_program['artifact_id']}/explicit-fake-{value}",
        "provenance": {"producer": "na_pipeline.validation.make_scenario", "source_artifact": atom_program["artifact_id"], "purpose": "explicit_uniform_fake_scenario"},
        "execution_kind": "scenario", "quantum_state_simulated": False,
        "hardware_executed": False, "loss_enabled": False,
        "results": results,
    }

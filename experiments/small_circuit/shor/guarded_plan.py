"""Bind single-qubit feedback guards to the reserved physical slots."""

from collections import Counter

from nadit_physical_compiler.visualization.result import build_result_trace


def guarded_plan(n: int, document: dict) -> dict:
    """Export one maximal result with measurement guards and physical DD zones."""
    trace = build_result_trace(document)
    if any(
        node.get("condition")
        and (len(node["qubits"]) != 1 or node["name"] in ("measure", "reset"))
        for node in document["dag"]["nodes"]
    ):
        raise ValueError("Only individually guarded LocalU actions are supported.")
    dag = document["dag"]
    nodes = {node["id"]: node for node in dag["nodes"]}
    conditions = {key: node for key, node in nodes.items() if node["condition"]}
    if any(node["name"] == "cp" for node in nodes.values()):
        raise ValueError("The guarded experiment requires semiclassical CZ inputs.")
    binding = {atom["qubit"]: atom["id"] for atom in trace["initial"]["atoms"]}
    measurements = [
        {
            "measurement_id": node["source_id"],
            "bit": node["clbits"][0],
            "qubit": node["qubits"][0],
        }
        for node in nodes.values()
        if node["name"] == "measure"
    ]
    if len({m["measurement_id"] for m in measurements}) != len(measurements):
        raise ValueError("Measurement occurrence identities must be unique.")
    if sorted(m["bit"] for m in measurements) != list(range(dag["num_clbits"])):
        raise ValueError("The experiment expects one measurement per output bit.")
    measurement_by_id = {m["measurement_id"]: m for m in measurements}
    availability: dict[int, float] = {}
    seen: Counter[int] = Counter()
    seen_measurements: Counter[int] = Counter()
    latency = document["device"]["readout"]["latency_us"]
    for step in trace["steps"]:
        # Conditions are checked before adding measurements produced in this
        # parallel step, even when a test parameter could make durations zero.
        for action in step["actions"]:
            guarded_ids = [key for key in action["source_ids"] if key in conditions]
            if guarded_ids:
                if action["kind"] != "LocalU" or len(action["source_ids"]) != 1:
                    raise ValueError(
                        "Only individually guarded LocalU actions are supported."
                    )
                node = conditions[guarded_ids[0]]
                if len(node["qubits"]) != 1 or action["atoms"] != [
                    binding[node["qubits"][0]]
                ]:
                    raise ValueError(
                        "Conditional LocalU target does not match its source qubit."
                    )
                condition = node["condition"]
                reference = condition["result"]["measurement_id"]
                if condition["value"] not in (0, 1):
                    raise ValueError("A guard must compare a measurement to a bit.")
                if (
                    reference not in availability
                    or availability[reference] > step["start_us"] + 1e-8
                ):
                    raise ValueError(
                        "A conditional gate precedes its classical result."
                    )
                action["guard"] = {
                    "measurement_id": reference,
                    "value": condition["value"],
                }
                seen[node["id"]] += 1
        for action in step["actions"]:
            if action["kind"] == "Measure":
                for result in action["parameters"]["results"]:
                    reference = result["measurement_id"]
                    metadata = measurement_by_id.get(reference)
                    if (
                        metadata is None
                        or result["atom_id"] != binding[metadata["qubit"]]
                    ):
                        raise ValueError(
                            "Physical measurement target differs from the source DAG."
                        )
                    availability[reference] = (
                        step["start_us"] + action["duration_us"] + latency
                    )
                    seen_measurements[reference] += 1
    if set(seen) != set(conditions) or any(count != 1 for count in seen.values()):
        raise ValueError(
            "Every conditional source operation must occur exactly once in the template."
        )
    if set(seen_measurements) != set(measurement_by_id) or any(
        count != 1 for count in seen_measurements.values()
    ):
        raise ValueError("Every source measurement must occur exactly once.")
    represented = {
        key
        for step in trace["steps"]
        for action in step["actions"]
        for key in action["source_ids"]
    }
    if any(
        node["name"] not in ("barrier", "global_phase") and key not in represented
        for key, node in nodes.items()
    ):
        raise ValueError("Maximal template is missing a non-metadata source operation.")
    return {
        "schema": "nadit.guarded-shor/1",
        "n": n,
        "num_qubits": dag["num_qubits"],
        "num_bits": dag["num_clbits"],
        "initial": trace["initial"],
        "steps": trace["steps"],
        "dag": dag,
        "measurements": sorted(measurements, key=lambda m: m["bit"]),
        "dd_zones": [
            {key: zone[key] for key in ("id", "role", "bounds")}
            for zone in document["device"]["zones"]
        ],
        "dd_control_assumption": (
            "Storage-zone pulses may run during measurement-zone exposure; "
            "independent zone addressing and negligible readout crosstalk are assumed."
        ),
    }

"""Export a single fixed-slot guarded program from a maximal saved compilation.

This experiment adapter does not extend production Atom IR. A false LocalU
guard leaves an idle slot of the same duration; geometry and later slots stay
fixed. The source artifact's forced measurement values are never exported.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ..simplified_circuit.compile_inputs import BUILD

TIMING_DEFAULTS = {
    "speed": 1.0,
    "transfer": 15.0,
    "readout": 100.0,
    "singleTime": 1.0,
    "czTime": 0.5,
    "resetTime": 5.0,
    "latency": 0.0,
}
Record = dict[str, Any]


def load_plan(n: int) -> Record:
    """Load the maximal result produced by the shared Small Shor compiler."""
    from experiments.small_circuit.shor.guarded_plan import guarded_plan

    path = BUILD / "results" / f"n{n}.json"
    raw = path.read_bytes()
    document = json.loads(raw)
    plan = guarded_plan(n, document)
    plan["provenance"] = {
        **document["source_provenance"],
        "template_sha256": hashlib.sha256(raw).hexdigest(),
        "execution_policy": "fixed slots; false LocalU guard is idle",
    }
    return plan


def retime(plan: Mapping[str, Any], params: Mapping[str, Any]) -> Record:
    """Recompute fixed-slot timing, retaining geometry and feedback causality.

    Args:
        plan: A guarded program returned by :func:`load_plan`.
        params: Timing values in microseconds and speed in micrometres per
            microsecond. Extra noise-model keys are ignored.

    Returns:
        A deep copy with new step/action durations, per-atom move distances,
        total duration, and measurement start/end/availability records.

    Raises:
        ValueError: For zero/nonfinite speed, invalid durations, unknown action
            kinds, or a template whose native dependencies cannot be respected.
    """
    timing = {
        key: float(params.get(key, value)) for key, value in TIMING_DEFAULTS.items()
    }
    if any(not math.isfinite(value) or value < 0 for value in timing.values()):
        raise ValueError("Timing parameters must be finite and nonnegative.")
    if timing["speed"] == 0:
        raise ValueError("Zero speed cannot complete a nonzero-distance move.")
    result = deepcopy(dict(plan))
    nodes = {node["id"]: node for node in result["dag"]["nodes"]}
    predecessors: dict[int, list[int]] = {key: [] for key in nodes}
    for before, after in result["dag"]["edges"]:
        predecessors[after].append(before)
    ends: dict[int, float] = {}
    available: dict[int, float] = {}
    measured: list[Record] = []
    metadata = {m["measurement_id"]: m for m in result["measurements"]}
    positions = {
        atom["id"]: (atom["x"], atom["y"]) for atom in result["initial"]["atoms"]
    }
    original_steps = result["steps"]
    steps: list[Record] = []
    clock, action_index = 0.0, 0

    def condition_time(node: Record) -> float:
        condition = node.get("condition")
        if condition is None:
            return 0.0
        reference = condition["result"]["measurement_id"]
        if reference not in available:
            raise ValueError(
                f"Feedback references unscheduled measurement {reference}."
            )
        return available[reference]

    def node_end(key: int) -> float:
        if key not in ends:
            node = nodes[key]
            if node["name"] not in ("barrier", "global_phase"):
                raise ValueError(f"Native dependency {key} has not been scheduled.")
            ends[key] = max(
                condition_time(node), *(node_end(p) for p in predecessors[key]), 0.0
            )
        return ends[key]

    # Transport actions have no native source IDs. Keep the conservative
    # dependency boundary for their next native gate, matching the fixed plan.
    upcoming: list[int] = []
    requirements: list[list[int]] = [[] for _ in original_steps]
    for index in range(len(original_steps) - 1, -1, -1):
        identifiers = [
            key
            for action in original_steps[index]["actions"]
            for key in action["source_ids"]
        ]
        if identifiers:
            upcoming = identifiers
        requirements[index] = upcoming

    def append_wait(duration: float, original_index: int, reason: str) -> None:
        nonlocal clock, action_index
        steps.append(
            {
                "index": len(steps),
                "original_index": original_index,
                "start_us": clock,
                "duration_us": duration,
                "actions": [
                    {
                        "index": action_index,
                        "kind": "Wait",
                        "duration_us": duration,
                        "source_ids": [],
                        "atoms": [],
                        "parameters": {},
                        "pairs": [],
                        "coverage": None,
                        "patch": {"atoms": [], "grids": []},
                        "text": reason,
                    }
                ],
            }
        )
        clock += duration
        action_index += 1

    duration_keys = {
        "Load": "transfer",
        "Store": "transfer",
        "Measure": "readout",
        "LocalU": "singleTime",
        "Rotation": "singleTime",
        "GlobalRY": "singleTime",
        "CZPulse": "czTime",
        "Reset": "resetTime",
    }
    for index, old in enumerate(original_steps):
        if all(action["kind"] == "Wait" for action in old["actions"]):
            continue
        earliest = clock
        for key in requirements[index]:
            earliest = max(
                earliest,
                condition_time(nodes[key]),
                *(node_end(p) for p in predecessors[key]),
            )
        if earliest > clock:
            append_wait(earliest - clock, index, "WAIT: classical result availability")
        actions = deepcopy(old["actions"])
        for action in actions:
            kind = action["kind"]
            if kind == "Move":
                targets = {
                    atom["id"]: (atom["x"], atom["y"])
                    for atom in action["patch"]["atoms"]
                }
                action["movement"] = [
                    {
                        "atom": atom,
                        "distance_um": math.dist(
                            positions[atom], targets.get(atom, positions[atom])
                        ),
                    }
                    for atom in action["atoms"]
                ]
                duration = (
                    max(
                        (move["distance_um"] for move in action["movement"]),
                        default=0.0,
                    )
                    / timing["speed"]
                )
            elif kind in duration_keys:
                duration = timing[duration_keys[kind]]
            else:
                raise ValueError(f"Unsupported guarded-plan action: {kind}.")
            action["duration_us"] = duration
            action["index"] = action_index
            # The serialized source text contains old timing. Do not export it
            # as though it were the retimed instruction's authoritative text.
            action["text"] = f"{kind}: {duration:.12g} us"
            action_index += 1
            for key in action["source_ids"]:
                ends[key] = max(ends.get(key, 0.0), clock + duration)
            if kind == "Measure":
                for item in action["parameters"]["results"]:
                    reference = item["measurement_id"]
                    available[reference] = clock + duration + timing["latency"]
                    measured.append(
                        {
                            **metadata[reference],
                            "start_us": clock,
                            "end_us": clock + duration,
                            "available_at_us": available[reference],
                        }
                    )
        duration = max(action["duration_us"] for action in actions)
        steps.append(
            {
                "index": len(steps),
                "original_index": old.get("original_index", index),
                "start_us": clock,
                "duration_us": duration,
                "actions": actions,
            }
        )
        clock += duration
        for action in actions:
            for atom in action["patch"]["atoms"]:
                positions[atom["id"]] = (atom["x"], atom["y"])
    program_duration = clock
    final_available = max(available.values(), default=clock)
    if final_available > clock:
        append_wait(
            final_available - clock,
            len(original_steps),
            "WAIT: final classical results",
        )
    result.update(
        steps=steps,
        duration_us=clock,
        program_duration_us=program_duration,
        measurement_times=measured,
        timing=timing,
    )
    return result

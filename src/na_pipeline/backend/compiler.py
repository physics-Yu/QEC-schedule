"""Bounded-input, deterministic R4 compilation for the initial physical slice.

The physical stream is never flattened into a second DAG. The returned action
artifact is materialized, as required by the initial public dict interface.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
import math
import time

from .geometry import EPS, broadcast_pairs, in_zone, route_waypoints, validate_cz_pairs, validate_motion

VERSION = "0.1.0"
NATIVE_1Q = {"H", "X", "Y", "Z", "S", "SDG", "T", "TDG", "RZ", "RX", "RY"}


def _hash(obj):
    return sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


class CompilationError(ValueError):
    """An explicit failure, with a diagnostic prefix that is never complete."""
    def __init__(self, code, message, *, source_id=None, details=None, partial_program=None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.source_id = source_id
        self.details = details or {}
        self.partial_program = partial_program

    def to_dict(self):
        return {"code": self.code, "message": str(self), "source_id": self.source_id,
                "details": self.details, "complete": False}


def _zone(device, name):
    zone = device["zones"][name]
    return {"bounds_um": [zone["x_range_um"], zone["y_range_um"]]}


class _Compiler:
    def __init__(self, program, device):
        self.program, self.device = program, device
        self.started = time.perf_counter()
        self.timings = device["timings_us"]
        self.pitch = device["geometry"]["initial_spacing_um"]
        self.speed = device["movement"]["speed_um_per_us"]
        self.gate_distance = device["geometry"]["gate_pair_distance_um"]
        self.tolerance = device["geometry"]["distance_tolerance_um"]
        self.broadcast_zone_id = device["broadcast"]["zone_id"]
        self.measurement_zone_id = device["measurement"]["zone_id"]
        self.broadcast_zone = _zone(device, self.broadcast_zone_id)
        self.measurement_zone = _zone(device, self.measurement_zone_id)
        self.actions, self.source_map = [], {}
        self.atoms, self.qubit_atoms, self.traps = {}, {}, {}
        self.home_traps, self.measure_traps = {}, {}
        self.available, self.resource_last = {}, {}
        self.action_end, self.op_end, self.op_last = {}, {}, {}
        self.result_ready, self.result_producer = {}, {}
        self.q_last = {}
        self.geometry_last = None
        self.illumination_counts = Counter()
        self.operation_count = 0
        self.stage_seconds = Counter()
        self._place()
        self.initial_state = {"atoms": deepcopy(list(self.atoms.values())),
                              "slm_traps": deepcopy(list(self.traps.values())),
                              "aod_rows": [], "aod_columns": []}
        self.stage_seconds["initial_placement"] = time.perf_counter() - self.started

    def fail(self, code, message, **details):
        raise CompilationError(code, message, source_id=getattr(self, "op", {}).get("id"),
                               details=details)

    def _place(self):
        qubits = self.program.get("qubits", [])
        if not qubits:
            self.fail("QUBITS_REQUIRED", "PhysicalProgram must declare physical qubits")
        ncols = math.ceil(math.sqrt(len(qubits)))
        xb, yb = self.broadcast_zone["bounds_um"]
        xmin = 0. if xb[0] is None else xb[0] + self.pitch
        ymin = 0. if yb[0] is None else yb[0] + self.pitch
        mb = self.measurement_zone["bounds_um"][1]
        my = ((mb[0] + mb[1])/2 if None not in mb
              else mb[0] + self.pitch if mb[0] is not None
              else mb[1] - self.pitch if mb[1] is not None else ymin + 100*self.pitch)
        for i, q in enumerate(qubits):
            qid, group = q["id"], q["aod_group"]
            if qid in self.qubit_atoms or group not in self.device["aod_groups"]:
                self.fail("QUBIT_BINDING", "Duplicate qubit or unknown AOD group", qubit=qid)
            aid, tid, mtid = f"atom:{i}", f"slm:home:{i}", f"slm:measure:{i}"
            pos = [xmin + (i % ncols)*self.pitch, ymin + (i // ncols)*self.pitch]
            # Measurement parking positions are distinct even for equal home x.
            mpos = [xmin + i*self.pitch, my]
            if not in_zone(pos, self.broadcast_zone) or not in_zone(mpos, self.measurement_zone):
                self.fail("PLACEMENT_SEARCH_EXHAUSTED", "Default grid does not fit configured zones; no infeasibility claim", qubit=qid)
            self.atoms[aid] = {"atom_id": aid, "qubit_id": qid, "position_um": pos,
                               "carrier": "SLM", "trap_id": tid, "aod_group": group,
                               "row_id": None, "column_id": None}
            self.qubit_atoms[qid] = aid
            self.home_traps[aid], self.measure_traps[aid] = tid, mtid
            for trapid, position, zone, occupant in ((tid, pos, self.broadcast_zone_id, aid),
                                                     (mtid, mpos, self.measurement_zone_id, None)):
                self.traps[trapid] = {"trap_id": trapid, "position_um": list(position),
                                      "zone_id": zone, "occupant": occupant}

    def _emit(self, kind, atoms, duration, payload, *, extra_resources=(), deps=(),
              not_before=0., condition=None, spatial=False):
        if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
            self.fail("ACTION_DURATION", "Action duration must be finite and positive", kind=kind)
        resources = sorted(set([f"atom:{a}" for a in atoms] + list(extra_resources)))
        dependencies = set(deps) | set(self.base_deps)
        if spatial and self.geometry_last:
            dependencies.add(self.geometry_last)
        dependencies.update(self.resource_last[r] for r in resources if r in self.resource_last)
        start = max([self.earliest, not_before, 0.] +
                    [self.action_end[d] for d in dependencies] +
                    [self.available.get(r, 0.) for r in resources])
        aid = f"action:{len(self.actions):07d}"
        content = {"physical_op_id": self.op["id"], "params": deepcopy(self.op["params"]),
                   "reads": list(self.op["reads"]) if kind in {"gate", "measure", "reset", "wait", "classical"} else [],
                   "writes": [], "source_reads": list(self.op["reads"]), "source_writes": list(self.op["writes"]),
                   "source_metadata": deepcopy(self.op.get("metadata", {})), **deepcopy(payload)}
        action = {"id": aid, "kind": kind, "atoms": list(atoms),
                  "t_start_us": start, "t_end_us": start + duration,
                  "resources": resources, "source_ids": list(dict.fromkeys([self.op["id"]] + self.op["source_ids"])),
                  "depends_on": sorted(dependencies), "condition": deepcopy(condition), "payload": content}
        self.actions.append(action)
        self.source_map[self.op["id"]].append(aid)
        self.action_end[aid] = action["t_end_us"]
        for resource in resources:
            self.available[resource] = action["t_end_us"]
            self.resource_last[resource] = aid
        if spatial:
            self.geometry_last = aid
        return action

    def _axis_resources(self, group):
        return [f"aod:{group}:row:0", f"aod:{group}:column:0"]

    def _pickup(self, aid):
        atom = self.atoms[aid]
        if atom["carrier"] != "SLM":
            self.fail("PICKUP_CARRIER", "Pickup requires an SLM atom", atom=aid)
        group, old = atom["aod_group"], atom["trap_id"]
        if any(a["carrier"] == "AOD" and a["aod_group"] == group for a in self.atoms.values()):
            self.fail("ROUTER_ACTIVE_AXIS", "Single-mover router cannot add another occupied line", group=group)
        row, col, new = f"{group}:r0", f"{group}:c0", f"aod:{group}:r0:c0"
        action = self._emit("pickup", [aid], self.timings["pickup"],
            {"from_trap_id": old, "to_trap_id": new, "aod_group": group,
             "row_id": row, "column_id": col, "position_um": atom["position_um"]},
            extra_resources=[f"slm:{old}"] + self._axis_resources(group), spatial=True)
        self.traps[old]["occupant"] = None
        atom.update(carrier="AOD", trap_id=new, row_id=row, column_id=col)
        return action

    def _move(self, aid, target):
        atom = self.atoms[aid]
        if math.dist(atom["position_um"], target) < EPS:
            return
        tick = time.perf_counter()
        stationary = [a["position_um"] for k, a in self.atoms.items() if k != aid]
        try:
            points = route_waypoints(atom["position_um"], target, stationary, self.pitch)
        except ValueError as exc:
            self.fail("ROUTE_SEARCH_EXHAUSTED", str(exc), atom=aid, target_um=target)
        self.stage_seconds["routing"] += time.perf_counter() - tick
        for point in points:
            start = list(atom["position_um"])
            trajectory = {"atom_id": aid, "from_um": start, "to_um": list(point),
                          "row_id": atom["row_id"], "column_id": atom["column_id"]}
            tick = time.perf_counter()
            errors = validate_motion(list(self.atoms.values()), [trajectory], atom["aod_group"])
            self.stage_seconds["compiler_geometry_checks"] += time.perf_counter() - tick
            if errors:
                self.fail("INVALID_MOTION", "Linear trajectory violates current geometry", errors=errors)
            duration = max(abs(point[i] - start[i]) for i in (0, 1))/self.speed
            self._emit("move", [aid], duration,
                       {"aod_group": atom["aod_group"], "trajectories": [trajectory], "interpolation": "linear"},
                       extra_resources=self._axis_resources(atom["aod_group"]), spatial=True)
            atom["position_um"] = list(point)

    def _drop(self, aid, tid):
        atom, trap = self.atoms[aid], self.traps[tid]
        if trap["occupant"] is not None or math.dist(atom["position_um"], trap["position_um"]) > EPS:
            self.fail("DROP_OCCUPANCY", "Drop needs an aligned empty SLM trap", trap=tid)
        group = atom["aod_group"]
        action = self._emit("drop", [aid], self.timings["drop"],
            {"from_trap_id": atom["trap_id"], "to_trap_id": tid, "aod_group": group,
             "row_id": atom["row_id"], "column_id": atom["column_id"], "position_um": atom["position_um"]},
            extra_resources=[f"slm:{tid}"] + self._axis_resources(group), spatial=True)
        trap["occupant"] = aid
        atom.update(carrier="SLM", trap_id=tid, row_id=None, column_id=None)
        return action

    def _transport(self, aid, tid):
        self._pickup(aid)
        self._move(aid, self.traps[tid]["position_um"])
        return self._drop(aid, tid)

    def _one_qubit(self, aid, name, *, condition=None, deps=(), lowering=None):
        if name not in self.device["operations"]["native_1q_gates"]:
            self.fail("DEVICE_GATE_UNSUPPORTED", "Native lowering requires a device-declared gate", gate=name)
        payload = {"name": name}
        if lowering:
            payload.update(lowering)
        return self._emit("gate", [aid], self.timings["gate_1q"], payload, deps=deps, condition=condition)

    def _cz(self, control, target, deps=()):
        # The moving atom is returned explicitly, clearing this pair before the
        # next broadcast. No return is represented by a placement-only change.
        self._pickup(control)
        p = self.atoms[target]["position_um"]
        goal = None
        expected = [sorted([control, target])]
        multibody_candidates = []
        tick = time.perf_counter()
        for dx, dy in ((self.gate_distance, 0), (-self.gate_distance, 0),
                       (0, self.gate_distance), (0, -self.gate_distance)):
            candidate = [p[0] + dx, p[1] + dy]
            trial = [dict(a, position_um=candidate) if k == control else a
                     for k, a in self.atoms.items()]
            if not in_zone(candidate, self.broadcast_zone):
                continue
            if any(math.dist(candidate, a["position_um"]) <= EPS for k, a in self.atoms.items() if k != control):
                continue
            actual = broadcast_pairs(trial, self.broadcast_zone, self.gate_distance, self.tolerance)
            if validate_cz_pairs(actual):
                multibody_candidates.append({"goal_um": candidate, "all_pairs": actual})
                continue
            if actual == expected:
                goal = candidate
                break
        self.stage_seconds["gate_layout_search"] += time.perf_counter() - tick
        if goal is None:
            if multibody_candidates:
                self.fail("UNSUPPORTED_MULTIBODY_BROADCAST", "No supported candidate found; geometric edges with degree > 1 cannot be treated as qualified CZ pulses", candidates=multibody_candidates)
            self.fail("BROADCAST_LAYOUT_SEARCH_EXHAUSTED", "No candidate has exactly the requested full broadcast graph", expected_pairs=expected)
        self._move(control, goal)
        actual = broadcast_pairs(list(self.atoms.values()), self.broadcast_zone, self.gate_distance, self.tolerance)
        if validate_cz_pairs(actual):
            self.fail("UNSUPPORTED_MULTIBODY_BROADCAST", "Actual broadcast graph is outside disjoint-pair support", all_pairs=actual)
        if actual != expected:
            self.fail("UNINTENDED_BROADCAST_PAIR", "Actual full-configuration pairs differ", actual_pairs=actual)
        illuminated = [a["atom_id"] for a in self.atoms.values() if in_zone(a["position_um"], self.broadcast_zone)]
        pulse = self._emit("gate", illuminated, self.timings["cz"],
             {"name": "CZ", "pairs": actual, "broadcast": True, "zone_id": self.broadcast_zone_id,
              "logical_gate": {"name": self.op["params"]["name"], "qubits": self.op["qubits"]},
              "lowering_rule": "CX=H(target);CZ;H(target)" if self.op["params"]["name"] == "CX" else "CZ identity"},
             extra_resources=[self.device["broadcast"]["resource_id"]] + self._axis_resources(self.atoms[control]["aod_group"]),
             deps=deps, spatial=True)
        self.illumination_counts.update(illuminated)
        self._move(control, self.traps[self.home_traps[control]]["position_um"])
        self._drop(control, self.home_traps[control])
        return pulse

    def operation(self, op):
        self.op = op
        required = {"id", "kind", "qubits", "params", "reads", "writes", "after", "source_ids", "condition"}
        if not required <= op.keys() or set(op) - required - {"metadata"} or not op["source_ids"]:
            self.fail("PHYSICAL_OP_FIELDS", "Physical operation fields are missing or unrecognized")
        if "metadata" in op and not isinstance(op["metadata"], dict):
            self.fail("PHYSICAL_METADATA", "Optional metadata must be a JSON object")
        if op["id"] in self.source_map:
            self.fail("DUPLICATE_OP", "Operation ID is already compiled")
        if any(q not in self.qubit_atoms for q in op["qubits"]):
            self.fail("UNKNOWN_QUBIT", "Operation references an undeclared physical qubit")
        self.source_map[op["id"]] = []
        condition = op["condition"]
        reads = list(op["reads"])
        if condition is not None:
            if set(condition) != {"bit", "equals"} or condition["equals"] not in (0, 1):
                self.fail("CONDITION_SCHEMA", "Only a single bit equality condition is supported")
            reads.append(condition["bit"])
        missing = [d for d in op["after"] if d not in self.op_end]
        missing_results = [r for r in reads if r not in self.result_ready]
        if missing or missing_results:
            self.fail("FORWARD_DEPENDENCY", "Operation stream must be topological; no speculative result reads", operations=missing, results=missing_results)
        self.base_deps = {self.op_last[d] for d in op["after"]}
        self.base_deps.update(self.q_last[q] for q in op["qubits"] if q in self.q_last)
        self.base_deps.update(self.result_producer[r] for r in reads)
        self.earliest = max([0.] + [self.op_end[d] for d in op["after"]] +
                            [self.result_ready[r] + (self.timings["feedback_latency"] if condition else 0.) for r in reads])
        atoms = [self.qubit_atoms[q] for q in op["qubits"]]
        kind = op["kind"]
        name = op["params"].get("name")
        allowed_params = ({"name", "angle", "angle_unit"} if name in {"RX", "RY", "RZ"} else {"name"}) if kind == "gate" else {
            "measure": {"basis"}, "reset": {"basis", "state"}, "wait": {"duration_us"}}.get(kind, set())
        if set(op["params"]) - allowed_params:
            self.fail("UNSUPPORTED_PARAMETERS", "Operation parameters have no declared lowering semantics", fields=sorted(set(op["params"]) - allowed_params))
        if condition and (kind != "gate" or len(atoms) != 1):
            self.fail("UNSUPPORTED_CONDITIONAL_OPERATION", "This router supports only conditional native 1q gates")
        if kind != "measure" and op["writes"]:
            self.fail("UNSUPPORTED_RESULT_WRITER", "Only Z measurement currently produces classical results")
        if kind == "gate":
            if len(set(atoms)) != len(atoms):
                self.fail("ALIASED_GATE", "Gate operands must be distinct")
            if name in NATIVE_1Q and name not in self.device["operations"]["native_1q_gates"]:
                self.fail("DEVICE_GATE_UNSUPPORTED", "Gate not declared in DeviceSpec", gate=name)
            if name in NATIVE_1Q and len(atoms) == 1:
                if name in {"RX", "RY", "RZ"} and (op["params"].get("angle_unit") != "rad" or not isinstance(op["params"].get("angle"), (int, float))):
                    self.fail("ROTATION_PARAMETERS", "Rotation requires a numeric angle and angle_unit=rad")
                self._one_qubit(atoms[0], name, condition=condition)
            elif name in {"CX", "CZ"} and len(atoms) == 2:
                pre = []
                if name == "CX":
                    h = self._one_qubit(atoms[1], "H", lowering={"lowering_rule": "CX=H(target);CZ;H(target)"})
                    pre.append(h["id"])
                pulse = self._cz(*atoms, deps=pre)
                if name == "CX":
                    self._one_qubit(atoms[1], "H", deps=[pulse["id"]], lowering={"lowering_rule": "CX=H(target);CZ;H(target)"})
            else:
                self.fail("UNSUPPORTED_GATE", "Gate is outside the implemented native lowering", gate=name)
        elif kind == "measure":
            if len(atoms) != 1 or len(op["writes"]) != 1 or op["params"].get("basis", "Z") != "Z":
                self.fail("UNSUPPORTED_MEASUREMENT", "Only one-atom Z measurement with one result is supported")
            result = op["writes"][0]
            if result in self.result_ready:
                self.fail("DUPLICATE_RESULT", "Results must be unique per instance", result_id=result)
            self._transport(atoms[0], self.measure_traps[atoms[0]])
            action = self._emit("measure", atoms, self.timings["measure"],
                                {"basis": "Z", "result_id": result, "origin": "fake", "writes": [result]})
            ready = action["t_end_us"] + self.timings["result_latency"]
            action["payload"]["result_ready_us"] = ready
            self.result_ready[result], self.result_producer[result] = ready, action["id"]
            self._transport(atoms[0], self.home_traps[atoms[0]])
        elif kind == "reset":
            if len(atoms) != 1 or op["params"].get("state", 0) != 0:
                self.fail("UNSUPPORTED_RESET", "Only one-atom reset to zero is implemented")
            self._emit("reset", atoms, self.timings["reset"], {"state": 0})
        elif kind == "wait":
            self._emit("wait", atoms, op["params"].get("duration_us"), {})
        else:
            self.fail("UNSUPPORTED_PHYSICAL_KIND", "Physical operation kind has no implemented semantics", kind=kind)
        mapped = self.source_map[op["id"]]
        # A source operation can end with two concurrent branches (CX H versus
        # control return). Use the latest end, not append order.
        self.op_last[op["id"]] = max(mapped, key=lambda a: self.action_end[a])
        self.op_end[op["id"]] = self.action_end[self.op_last[op["id"]]]
        for q in op["qubits"]:
            self.q_last[q] = self.op_last[op["id"]]
        self.operation_count += 1

    def artifact(self, complete):
        counts = Counter(a["kind"] for a in self.actions)
        end = max([0.] + list(self.action_end.values()) + list(self.result_ready.values()))
        ph, dh = _hash(self.program), _hash(self.device)
        return {"schema_version": "AtomProgram/0.2.0-draft",
                "artifact_id": f"atom-{ph[:12]}-{dh[:12]}", "producer_version": f"na_pipeline.backend/{VERSION}",
                "provenance": {"owner": "R4", "kb_revision": "kb-0004", "contract": "IF-MVP-001/0.2.1-draft",
                               "physical_program_ref": self.program["artifact_id"],
                               "fixture": bool(self.program.get("provenance", {}).get("fixture", False)),
                               "parameter_source": "DeviceSpec.parameter_provenance; project assumptions, not calibrated",
                               "routing_policy": "single occupied AOD intersection; explicit home restoration; conservative spatial prefix",
                               "geometry_model": "point atoms; shared noncrossing axes; linear segments",
                               "cz_support_domain": "disjoint geometric pairs only; many-body degree>1 rejected",
                               "lowering_rules": {"CX": "H(target);CZ(control,target);H(target)"}},
                "input_hashes": {"physical_program": ph, "device": dh},
                "device_ref": self.device["artifact_id"],
                "execution_kind": "compile_plan", "quantum_state_simulated": False,
                "hardware_executed": False, "loss_enabled": False, "complete": complete,
                "initial_state": self.initial_state, "actions": self.actions, "source_map": self.source_map,
                "stats": {"physical_op_count": self.operation_count, "action_count": len(self.actions),
                          "atom_count": len(self.atoms), "t_start_us": 0., "t_end_us": end, "duration_us": end,
                          "action_counts": dict(counts), "planned_illumination_counts": dict(self.illumination_counts),
                          "stage_wall_seconds": dict(self.stage_seconds),
                          "wall_seconds": time.perf_counter() - self.started,
                          "max_live_physical_ops": 1, "route_candidates_per_segment": 7,
                          "layout_candidates_per_cz": 4, "cache_hits": 0,
                          "cache_policy": "no mutable instance state or result cache; upstream templates reused by reference"},
                "unverified": ["independent R6 validation is external", "no global scheduling optimality",
                               "no quantum state, fault tolerance, fidelity or hardware execution",
                               "full Shor, factory lifecycle and online window checkpointing are outside this implementation"]}


def compile_physical(program: dict, device: dict, *, max_ops: int | None = None) -> dict:
    """Compile a complete physical operation stream, or raise CompilationError.

    max_ops is a diagnostic budget. Reading its next operation triggers failure;
    a prefix cannot be returned as a completed AtomProgram.
    """
    if max_ops is not None and (type(max_ops) is not int or max_ops < 0):
        raise CompilationError("INVALID_BUDGET", "max_ops must be a nonnegative integer or None")
    if not isinstance(program, dict):
        raise CompilationError("PHYSICAL_PROGRAM_SCHEMA", "PhysicalProgram must be a dict")
    if (program.get("schema_version") != "physical-program/0.2.0-draft"
            or not isinstance(program.get("artifact_id"), str) or not program["artifact_id"]
            or not isinstance(program.get("provenance"), dict)
            or not isinstance(program.get("qubits"), list)):
        raise CompilationError("PHYSICAL_PROGRAM_SCHEMA", "Missing or unsupported physical artifact envelope")
    if any(program.get(flag, False) is not False for flag in
           ("quantum_state_simulated", "hardware_executed", "loss_enabled", "sampled")):
        raise CompilationError("UNSUPPORTED_EVIDENCE", "This compiler accepts the loss-free compile-plan profile only")
    from na_pipeline.device import validate_device
    from na_pipeline.qec import iter_physical_ops
    errors = validate_device(device)
    if errors:
        raise CompilationError("INVALID_DEVICE", "DeviceSpec failed its producer contract", details={"errors": errors})
    try:
        c = _Compiler(program, device)
    except CompilationError:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise CompilationError("PHYSICAL_PROGRAM_SCHEMA", str(exc)) from exc
    iterator = iter(iter_physical_ops(program))
    try:
        while True:
            tick = time.perf_counter()
            try:
                op = next(iterator)
            except StopIteration:
                break
            finally:
                c.stage_seconds["physical_expansion"] += time.perf_counter() - tick
            if max_ops is not None and c.operation_count >= max_ops:
                raise CompilationError("OP_BUDGET_EXHAUSTED", "Compilation stopped before the next source operation; not a complete plan",
                                       source_id=op.get("id"), details={"max_ops": max_ops, "compiled_ops": c.operation_count})
            tick = time.perf_counter()
            nested_before = sum(c.stage_seconds[key] for key in
                                ("routing", "gate_layout_search", "compiler_geometry_checks"))
            c.operation(op)
            nested_after = sum(c.stage_seconds[key] for key in
                               ("routing", "gate_layout_search", "compiler_geometry_checks"))
            c.stage_seconds["lowering_and_scheduling"] += time.perf_counter() - tick - (nested_after - nested_before)
    except CompilationError as exc:
        exc.partial_program = c.artifact(False)
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise CompilationError("UPSTREAM_OR_SCHEMA_ERROR", str(exc), details={"type": type(exc).__name__},
                               partial_program=c.artifact(False)) from exc
    return c.artifact(True)

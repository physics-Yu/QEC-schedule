"""Bounded-memory instantiation of IF-03 operations and result namespaces."""

from collections.abc import Iterator
from copy import deepcopy
from math import isfinite
import re


class QECContractError(ValueError):
    def __init__(self, code, message, source_id=None, resource_id=None):
        self.code, self.source_id, self.resource_id = code, source_id, resource_id
        super().__init__(f"{code}: {message}; source={source_id}; resource={resource_id}")


def _fail(code, message, source=None, resource=None):
    raise QECContractError(code, message, source, resource)


def _id(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]+", value) is not None


def _strings(value):
    return isinstance(value, list) and all(isinstance(s, str) and s for s in value)


def _check_ops(body, allowed_qubits):
    """Only local structure is validated here; no repeat is flattened."""
    seen, writers = set(), set()
    if not isinstance(body, list):
        _fail("BAD_BODY", "body must be a list")
    for node in body:
        if not isinstance(node, dict) or node.get("kind") != "op" or set(node) != {"kind", "op"}:
            _fail("UNSUPPORTED_NODE", "template body supports op nodes only")
        op = node["op"]
        required = {"id", "kind", "qubits", "params", "reads", "writes", "after", "source_ids", "condition"}
        if not isinstance(op, dict) or not required <= op.keys():
            _fail("BAD_OPERATION", "operation missing required fields")
        oid = op["id"]
        if not _id(oid) or oid in seen:
            _fail("DUPLICATE_OR_BAD_ID", "operation ID must be unique and namespace-safe", oid)
        for key in ("qubits", "reads", "writes", "after", "source_ids"):
            if not _strings(op[key]) or len(op[key]) != len(set(op[key])):
                _fail("BAD_FIELD", f"{key} must contain unique nonempty strings", oid)
        if not op["source_ids"] or not set(op["qubits"]) <= allowed_qubits:
            _fail("BAD_QUBIT_OR_SOURCE", "unknown qubit or missing source", oid)
        if not set(op["after"]) <= seen or not set(op["reads"]) <= writers:
            _fail("FORWARD_REFERENCE", "after/reads must refer to earlier local producers", oid)
        if any(not _id(bit) or bit in writers for bit in op["writes"]):
            _fail("BAD_RESULT", "result must be unique and namespace-safe", oid)
        condition = op["condition"]
        if condition is not None:
            if (not isinstance(condition, dict) or set(condition) != {"bit", "equals"}
                    or type(condition["equals"]) is not int or condition["equals"] not in (0, 1)
                    or condition["bit"] not in op["reads"]):
                _fail("BAD_CONDITION", "condition bit must be an explicit earlier read", oid)
            if op["writes"]:
                _fail("CONDITIONAL_WRITE_UNSUPPORTED", "conditional result production needs branch merge contract", oid)
        params = op["params"]
        if not isinstance(params, dict):
            _fail("BAD_PARAMS", "params must be an object", oid)
        kind, arity = op["kind"], len(op["qubits"])
        if kind == "gate":
            name = params.get("name")
            if name not in {"H", "X", "Y", "Z", "S", "SDG", "T", "TDG", "CX", "CZ", "RZ"}:
                _fail("UNSUPPORTED_GATE", f"unsupported gate {name}", oid)
            if arity != (2 if name in {"CX", "CZ"} else 1) or op["writes"]:
                _fail("BAD_GATE", "gate arity or writes invalid", oid)
            if name == "RZ" and (params.get("angle_unit") != "rad" or
                    type(params.get("angle")) not in (int, float) or not isfinite(params["angle"])):
                _fail("BAD_ANGLE", "RZ needs finite angle and angle_unit=rad", oid)
        elif kind == "permute":
            dest = params.get("destination_indices")
            if (arity < 2 or op["reads"] or op["writes"] or condition is not None or
                    set(params) != {"destination_indices"} or not isinstance(dest, list) or
                    any(type(i) is not int for i in dest) or sorted(dest) != list(range(arity))):
                _fail("BAD_PERMUTATION", "permute requires an unconditional bijection of addressed code sites", oid)
        elif kind == "measure":
            if arity != 1 or len(op["writes"]) != 1 or params.get("basis") != "Z":
                _fail("BAD_MEASURE", "measure requires one qubit, one write, Z basis", oid)
        elif kind == "reset":
            if arity != 1 or op["writes"] or params.get("basis") != "Z":
                _fail("BAD_RESET", "reset requires one qubit, no writes, Z basis", oid)
        elif kind == "wait":
            duration = params.get("duration_us")
            if type(duration) not in (int, float) or not isfinite(duration) or duration < 0 or op["writes"]:
                _fail("BAD_WAIT", "wait requires nonnegative finite duration_us and no writes", oid)
        elif kind == "classical":
            if (arity != 0 or len(op["writes"]) != 1 or not op["reads"]
                    or params.get("operation") not in {"xor", "all_zero"}
                    or set(params) != {"operation"} or condition is not None):
                _fail("BAD_CLASSICAL", "classical supports unconditional xor/all_zero with reads and one write", oid)
        else:
            _fail("UNSUPPORTED_OPERATION", f"unsupported kind {kind}", oid)
        seen.add(oid)
        writers.update(op["writes"])


def iter_physical_ops(program: dict) -> Iterator[dict]:
    """Yield concrete operations. Caller must keep input immutable during iteration.

    Memory is O(stored templates + body + qubits + largest local template), not
    O(expanded rounds). A partially consumed generator is NOT a complete program.
    """
    if not isinstance(program, dict) or program.get("schema_version") != "physical-program/0.2.0-draft":
        _fail("UNSUPPORTED_SCHEMA", "expected physical-program/0.2.0-draft")
    for key in ("artifact_id", "provenance", "qubits", "templates", "body"):
        if key not in program:
            _fail("BAD_PROGRAM", f"missing {key}")
    if not isinstance(program["qubits"], list) or not isinstance(program["templates"], dict) or not isinstance(program["body"], list):
        _fail("BAD_PROGRAM", "qubits/body must be lists and templates an object")
    qubits = set()
    for q in program["qubits"]:
        if not isinstance(q, dict) or not {"id", "block_id", "role", "aod_group"} <= q.keys():
            _fail("BAD_QUBIT", "qubit descriptor incomplete")
        if not isinstance(q["id"], str) or not q["id"] or q["id"] in qubits or q["aod_group"] not in {"data", "magic"}:
            _fail("BAD_QUBIT", "duplicate/invalid qubit or AOD group", resource=q.get("id"))
        qubits.add(q["id"])
    templates = program["templates"]
    for tid, template in templates.items():
        if (not _id(tid) or not isinstance(template, dict) or template.get("template_id") != tid
                or not _strings(template.get("qubits")) or len(set(template["qubits"])) != len(template["qubits"])
                or not isinstance(template.get("metadata"), dict)):
            _fail("BAD_TEMPLATE", "invalid template identity, formals, or metadata", tid)
        _check_ops(template.get("body"), set(template["qubits"]))
    seen_calls = set()
    direct_nodes = []
    for node in program["body"]:
        if not isinstance(node, dict):
            _fail("BAD_NODE", "body node must be object")
        if node.get("kind") == "op":
            direct_nodes.append(node)
            continue
        if node.get("kind") != "call":
            _fail("UNSUPPORTED_NODE", "only op/call nodes supported")
        if not set(node) <= {"kind", "id", "template_id", "bindings", "repeat", "source_ids"}:
            _fail("UNSUPPORTED_CALL_FIELD", "call fields cannot be silently ignored", node.get("id"))
        cid, tid, bindings, repeat = (node.get(k) for k in ("id", "template_id", "bindings", "repeat"))
        if not _id(cid) or cid in seen_calls:
            _fail("BAD_CALL_ID", "call ID must be unique and namespace-safe", cid)
        if not isinstance(tid, str) or tid not in templates:
            _fail("UNKNOWN_TEMPLATE", "template missing", cid, tid)
        if (not isinstance(bindings, dict) or set(bindings) != set(templates[tid]["qubits"])
                or not all(isinstance(q, str) for q in bindings.values())
                or not set(bindings.values()) <= qubits or len(set(bindings.values())) != len(bindings)):
            _fail("BAD_BINDINGS", "bindings require exact formals, known distinct physical qubits", cid)
        if type(repeat) is not int or repeat < 1:
            _fail("BAD_REPEAT", "repeat must be positive integer", cid)
        if "source_ids" in node and (not _strings(node["source_ids"]) or not node["source_ids"]):
            _fail("BAD_SOURCE", "call source_ids must be nonempty", cid)
        seen_calls.add(cid)
    _check_ops(direct_nodes, qubits)
    last_on_qubit = {}
    direct_writers = {}

    def expand(nodes, bindings, prefix, extra_sources, writers):
        for node in nodes:
            op = deepcopy(node["op"])
            local_id = op["id"]
            op["id"] = prefix + local_id
            op["qubits"] = [bindings[q] for q in op["qubits"]]
            op["reads"] = [prefix + bit for bit in op["reads"]]
            op["writes"] = [prefix + bit for bit in op["writes"]]
            op["after"] = [prefix + oid for oid in op["after"]]
            if op["condition"] is not None:
                op["condition"]["bit"] = prefix + op["condition"]["bit"]
            predecessors = list(op["after"])
            predecessors += [last_on_qubit[q] for q in op["qubits"] if q in last_on_qubit]
            predecessors += [writers[bit] for bit in op["reads"]]
            op["after"] = list(dict.fromkeys(predecessors))
            op["source_ids"] = list(dict.fromkeys(op["source_ids"] + extra_sources + [op["id"]]))
            for q in op["qubits"]:
                last_on_qubit[q] = op["id"]
            for bit in op["writes"]:
                writers[bit] = op["id"]
            yield op

    identity = {q: q for q in qubits}
    for node in program["body"]:
        if node["kind"] == "op":
            yield from expand([node], identity, "", [program["artifact_id"]], direct_writers)
        else:
            for repeat_index in range(node["repeat"]):
                prefix = f"{node['id']}/r{repeat_index}/"
                sources = node.get("source_ids", []) + [node["id"], node["template_id"], program["artifact_id"]]
                yield from expand(templates[node["template_id"]]["body"], node["bindings"], prefix, sources, {})

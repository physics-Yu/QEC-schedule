"""Source-only qualification of a proposed two-qubit projection window.

This is a conservative dependency guard, not Enola execution or an atom-plan
validator. It does not alter the existing physical program or strategy key.
"""

from .program import iter_physical_ops


def check_projection_window(program, source_op_ids, *, commutable=True):
    """Return errors for an unsafe CX/CZ-only window.

    A commutable window must be a disjoint-qubit dependency antichain. More
    permissive commutation proofs are deliberately outside this profile.
    Every non-pair operation between selected source positions is a boundary;
    ordered mode must split there too, instead of silently dropping that op.
    The caller must still preserve the full source stream and source records.
    """
    errors = []
    def fail(code, message, **details):
        errors.append({"code": code, "message": message, **details})
    if (not isinstance(source_op_ids, list) or not source_op_ids
            or not all(isinstance(s, str) and s for s in source_op_ids)
            or len(set(source_op_ids)) != len(source_op_ids) or type(commutable) is not bool):
        return [{"code": "PROJECTION_FIELDS", "message": "nonempty unique source IDs and a bool commutable flag required"}]
    try:
        ops = list(iter_physical_ops(program))
    except (ValueError, TypeError, KeyError) as exc:
        return [{"code": "PROJECTION_SOURCE_INVALID", "message": str(exc)}]
    by_id = {op["id"]: op for op in ops}
    positions = {op["id"]: i for i, op in enumerate(ops)}
    missing = [sid for sid in source_op_ids if sid not in by_id]
    if missing:
        return [{"code": "PROJECTION_SOURCE_MISSING", "message": "source operation absent", "source_op_ids": missing}]
    def eligible(op):
        return (op["kind"] == "gate" and op["params"].get("name") in {"CX", "CZ"}
                and set(op["params"]) == {"name"}
                and len(op["qubits"]) == 2 and op["condition"] is None and not op["reads"] and not op["writes"])
    for sid in source_op_ids:
        if not eligible(by_id[sid]):
            fail("PROJECTION_OPERATION_UNSUPPORTED", "window accepts unconditional CX/CZ source operations only", source_id=sid)
    low, high = min(positions[s] for s in source_op_ids), max(positions[s] for s in source_op_ids)
    boundaries = [op["id"] for op in ops[low:high + 1] if not eligible(op)]
    if boundaries:
        fail("NON_PAIR_BOUNDARY_CROSSED", "split before/after 1q, measure/reset, classical, wait or conditional source operations",
             boundary_source_ids=boundaries)
    if not commutable and source_op_ids != sorted(source_op_ids, key=positions.get):
        fail("PROJECTION_ORDER_CHANGED", "ordered mode must preserve original source order")
    if commutable:
        ancestors = {}
        for op in ops:
            parents = set(op["after"])
            ancestors[op["id"]] = parents | set().union(*(ancestors[parent] for parent in parents))
        for i, a in enumerate(source_op_ids):
            for b in source_op_ids[i + 1:]:
                if a in ancestors[b] or b in ancestors[a]:
                    fail("DEPENDENT_PAIR_OPERATIONS", "a source dependency cannot be declared a commutable pair set", source_op_ids=[a, b])
                if set(by_id[a]["qubits"]) & set(by_id[b]["qubits"]):
                    fail("SHARED_QUBIT_COMMUTATION_UNPROVEN", "shared-qubit commutation needs a separate proof outside this profile", source_op_ids=[a, b])
    return errors

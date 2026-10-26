"""Conservative dependency-local cancellations and initializer folding."""

from dataclasses import replace
from fractions import Fraction

from ..model import Guard, Operation

_PHASE = {"t": 1, "s": 2, "z": 4, "sdg": 6, "tdg": 7}
_PHASE_WORDS = {
    0: (),
    1: ("t",),
    2: ("s",),
    3: ("s", "t"),
    4: ("z",),
    5: ("z", "t"),
    6: ("sdg",),
    7: ("tdg",),
}
_SELF_INVERSE = {"h", "x", "y", "z", "cx"}
_ROTATIONS = {"rx", "ry", "rz", "p"}


def simplify(operations: tuple[Operation, ...]) -> tuple[Operation, ...]:
    """Cancel exact local inverses and fold H into unguarded initializers.

    Only operations adjacent on every participating quantum wire can combine.
    Measurements, barriers and different guards therefore block cancellation.
    """
    output: list[Operation | None] = []
    stacks: dict[int, list[int]] = {}

    def append(op: Operation) -> None:
        index = len(output)
        output.append(op)
        for qubit in op.qubits:
            stacks.setdefault(qubit, []).append(index)

    def remove(index: int, op: Operation) -> None:
        output[index] = None
        for qubit in op.qubits:
            stacks[qubit].pop()

    for op in operations:
        if op.guard is not None:
            constants = tuple(
                p for p in op.guard.predicates if all(r is None for r in p.bits)
            )
            if any(not p.evaluate({}) for p in constants):
                continue
            remaining = tuple(p for p in op.guard.predicates if p not in constants)
            op = replace(op, guard=Guard(remaining) if remaining else None)
        if op.name == "id":
            continue
        previous = [stacks.get(q, [])[-1] if stacks.get(q) else -1 for q in op.qubits]
        index = previous[0] if previous and len(set(previous)) == 1 else -1
        old = output[index] if index >= 0 else None
        if old is not None and old.qubits == op.qubits and old.guard == op.guard:
            sources = tuple(sorted(set(old.source_ids + op.source_ids)))
            if op.name in _SELF_INVERSE and old.name == op.name:
                remove(index, old)
                continue
            if op.name in _ROTATIONS and old.name == op.name:
                exact = Fraction(old.params[0]) + Fraction(op.params[0])
                try:
                    angle = float(exact)
                except OverflowError:
                    angle = None
                if angle is not None and Fraction(angle) == exact:
                    remove(index, old)
                    if angle:
                        append(replace(op, params=(angle,), source_ids=sources))
                    continue
            if old.name in _PHASE and op.name in _PHASE:
                power = (_PHASE[old.name] + _PHASE[op.name]) % 8
                remove(index, old)
                for name in _PHASE_WORDS[power]:
                    append(replace(op, name=name, source_ids=sources))
                continue
            if old.guard is None and old.name in ("initialize_0", "initialize_plus"):
                if op.name == "h":
                    output[index] = replace(
                        old,
                        name="initialize_plus"
                        if old.name == "initialize_0"
                        else "initialize_0",
                        source_ids=sources,
                    )
                    continue
                if (old.name == "initialize_0" and op.name in _PHASE) or (
                    old.name == "initialize_plus" and op.name == "x"
                ):
                    output[index] = replace(old, source_ids=sources)
                    continue
        append(op)
    return tuple(op for op in output if op is not None)

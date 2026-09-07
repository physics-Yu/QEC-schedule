"""Hardware-independent logical instructions. Compilation is a later milestone."""
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


class LogicalOp(str, Enum):
    PREPARE_0 = "LogicalPrepare0"
    PREPARE_PLUS = "LogicalPreparePlus"
    X = "LogicalX"
    Z = "LogicalZ"
    H = "LogicalH"
    CNOT = "LogicalCNOT"
    MEASURE_X = "LogicalMeasureX"
    MEASURE_Z = "LogicalMeasureZ"
    QEC_BARRIER = "LogicalQECBarrier"
    MEASURE_LOGICAL = "LogicalMeasure"
    IDLE = "LogicalIdle"


@dataclass(frozen=True)
class LogicalInstruction:
    id: str
    operation: LogicalOp
    logical_qubits: tuple[str, ...]
    dependencies: tuple[str, ...] = ()
    rounds: int = 1
    metadata: Mapping[str, str | int] = None

    def __post_init__(self):
        object.__setattr__(self, "operation", LogicalOp(self.operation))
        object.__setattr__(self, "logical_qubits", tuple(self.logical_qubits))
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        metadata = {} if self.metadata is None else self.metadata
        if not isinstance(metadata, Mapping) or any(
                not isinstance(key, str) or type(value) not in (str, int)
                for key, value in metadata.items()):
            raise ValueError("Logical instruction metadata needs string keys and string/integer values")
        object.__setattr__(self, "metadata", MappingProxyType(dict(metadata)))
        if self.operation == LogicalOp.CNOT:
            arity = 2
            valid_arity = len(self.logical_qubits) == arity
        elif self.operation in (LogicalOp.QEC_BARRIER, LogicalOp.MEASURE_LOGICAL):
            arity = None
            valid_arity = len(self.logical_qubits) >= 1
        else:
            arity = 1
            valid_arity = len(self.logical_qubits) == arity
        if not self.id or not valid_arity:
            raise ValueError("Instruction needs an ID and the correct qubit arity")
        if len(set(self.logical_qubits)) != len(self.logical_qubits) or any(not q for q in self.logical_qubits):
            raise ValueError("Logical qubit IDs must be nonempty and distinct")
        if type(self.rounds) is not int or self.rounds < 1:
            raise ValueError("rounds must be a positive integer")
        if self.operation not in (LogicalOp.IDLE, LogicalOp.QEC_BARRIER) and self.rounds != 1:
            raise ValueError("Only LogicalIdle accepts a round count")

    def to_dict(self):
        return {"id": self.id, "operation": self.operation.value,
                "logical_qubits": list(self.logical_qubits),
                "dependencies": list(self.dependencies), "rounds": self.rounds,
                "metadata": dict(self.metadata)}


@dataclass(frozen=True)
class LogicalProgram:
    logical_qubits: tuple[str, ...]
    instructions: tuple[LogicalInstruction, ...]

    def __post_init__(self):
        object.__setattr__(self, "logical_qubits", tuple(self.logical_qubits))
        object.__setattr__(self, "instructions", tuple(self.instructions))
        declared = set(self.logical_qubits)
        if len(declared) != len(self.logical_qubits) or any(not q for q in declared):
            raise ValueError("Logical qubit declarations must be unique and nonempty")
        seen = set()
        for instruction in self.instructions:
            if instruction.id in seen:
                raise ValueError("Duplicate logical instruction ID")
            if not set(instruction.logical_qubits) <= declared:
                raise ValueError("Undeclared logical qubit")
            if not set(instruction.dependencies) <= seen:
                raise ValueError("Dependencies must reference earlier instructions")
            seen.add(instruction.id)

    def to_dict(self):
        return {"schema_version": 1, "kind": "logical_program",
                "logical_qubits": list(self.logical_qubits),
                "instructions": [instruction.to_dict() for instruction in self.instructions]}

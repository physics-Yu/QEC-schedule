"""Hardware-independent logical instructions. Compilation is a later milestone."""
from dataclasses import dataclass
from enum import Enum


class LogicalOp(str, Enum):
    PREPARE_0 = "LogicalPrepare0"
    PREPARE_PLUS = "LogicalPreparePlus"
    X = "LogicalX"
    Z = "LogicalZ"
    H = "LogicalH"
    CNOT = "LogicalCNOT"
    MEASURE_X = "LogicalMeasureX"
    MEASURE_Z = "LogicalMeasureZ"
    IDLE = "LogicalIdle"


@dataclass(frozen=True)
class LogicalInstruction:
    id: str
    operation: LogicalOp
    logical_qubits: tuple[str, ...]
    dependencies: tuple[str, ...] = ()
    rounds: int = 1

    def __post_init__(self):
        object.__setattr__(self, "operation", LogicalOp(self.operation))
        object.__setattr__(self, "logical_qubits", tuple(self.logical_qubits))
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        arity = 2 if self.operation == LogicalOp.CNOT else 1
        if not self.id or len(self.logical_qubits) != arity:
            raise ValueError("Instruction needs an ID and the correct qubit arity")
        if len(set(self.logical_qubits)) != arity or any(not q for q in self.logical_qubits):
            raise ValueError("Logical qubit IDs must be nonempty and distinct")
        if type(self.rounds) is not int or self.rounds < 1:
            raise ValueError("rounds must be a positive integer")
        if self.operation != LogicalOp.IDLE and self.rounds != 1:
            raise ValueError("Only LogicalIdle accepts a round count")


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

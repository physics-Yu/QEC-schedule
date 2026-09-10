from dataclasses import dataclass
from .models import Position2D


@dataclass(frozen=True)
class ConstraintViolation:
    code: str
    message: str
    atom_ids: tuple[str, ...] = ()
    holder_id: str | None = None
    position: Position2D | None = None


class ValidationError(ValueError):
    """Machine-readable diagnostics shared with visualization."""
    def __init__(self, code, message, *, atom_ids=(), holder_id=None, position=None):
        self.violation = ConstraintViolation(code, message, tuple(atom_ids),
            str(holder_id) if holder_id is not None else None, position)
        super().__init__(f'{code}: {message}')

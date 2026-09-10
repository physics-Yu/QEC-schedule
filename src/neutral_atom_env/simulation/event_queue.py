from dataclasses import dataclass
from neutral_atom_env.domain.models import SimulationEvent


@dataclass(frozen=True)
class EventQueue:
    """Persistent queue; deriving a queue cannot alter a live state."""
    entries: tuple[tuple[float, int, SimulationEvent], ...] = ()
    next_sequence: int = 0

    def __post_init__(self):
        object.__setattr__(self, 'entries', tuple(sorted(tuple(e) for e in self.entries)))
        ids = [seq for _, seq, _ in self.entries]
        if (type(self.next_sequence) is not int or self.next_sequence < 0 or
                len(ids) != len(set(ids)) or any(type(i) is not int or i < 0 or i >= self.next_sequence for i in ids) or
                any(t != event.time_us for t, _, event in self.entries)):
            raise ValueError('Invalid event queue ordering')

    def push(self, event: SimulationEvent) -> 'EventQueue':
        return EventQueue(self.entries + ((event.time_us, self.next_sequence, event),), self.next_sequence + 1)

    def peek(self) -> SimulationEvent:
        if not self.entries:
            raise IndexError('Event queue is empty')
        return self.entries[0][2]

    def pop(self) -> tuple[SimulationEvent, 'EventQueue']:
        return self.peek(), EventQueue(self.entries[1:], self.next_sequence)

    def __bool__(self):
        return bool(self.entries)

    def snapshot(self):
        return {'next_sequence': self.next_sequence, 'pending': self.entries}

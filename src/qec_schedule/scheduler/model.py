from dataclasses import dataclass, field
from enum import Enum
from collections import Counter


class TaskState(str, Enum):
    WAITING = 'WAITING'
    READY = 'READY'
    RUNNING = 'RUNNING'
    DONE = 'DONE'
    BLOCKED = 'BLOCKED'


class Pool(str, Enum):
    MOVE = 'P_MOVE'
    SINGLE = 'P_1Q'
    ENTANGLE = 'P_ENTANGLE'
    MEASURE = 'P_MEASURE'
    REFILL = 'P_REFILL'


@dataclass(frozen=True, order=True)
class Priority:
    critical_path: float = 0
    age: float = 0


@dataclass
class Task:
    task_id: str
    pool: Pool
    actions: tuple
    dependencies: tuple
    estimated_duration: float
    priority_vector: Priority = field(default_factory=Priority)
    status: TaskState = TaskState.WAITING
    ready_time: float | None = None

    @property
    def atoms(self):
        return tuple(dict.fromkeys(atom for a in self.actions for atom in a.atoms))

    @property
    def required_resources(self):
        return {r.resource: r.units for a in self.actions for r in a.required_resources}


class ResourceLock:
    """Atomic owner-based capacity accounting; no partial acquisition on failure."""
    def __init__(self, capacities):
        if any(type(v) is not int or v < 1 for v in capacities.values()):
            raise ValueError('Resource capacities must be positive integers')
        self.capacities = dict(capacities)
        self.owners = {}

    def can_acquire(self, requests):
        used = Counter()
        for owner, resources in {**self.owners, **requests}.items():
            if owner in self.owners and owner in requests and resources != self.owners[owner]:
                raise ValueError('Cannot change an active resource owner')
            if any(type(v) is not int or v < 1 for v in resources.values()):
                raise ValueError('Resource units must be positive integers')
            used.update(resources)
        return all(k in self.capacities and v <= self.capacities[k] for k, v in used.items())

    def acquire(self, requests):
        if not self.can_acquire(requests):
            return False
        self.owners.update({k: dict(v) for k, v in requests.items()})
        return True

    def release(self, owner):
        return self.owners.pop(owner)

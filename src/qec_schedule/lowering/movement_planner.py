"""Group ready transports into compatible, unscheduled AOD movement epochs."""
from collections.abc import Iterable
from dataclasses import dataclass
import math

from ..hardware.aod import AODController, Translation
from ..hardware.timing import ActionTiming
from .experimental_ir import ExperimentalAction, ExperimentalPlan, Reservation, ResourceRequirement, SiteRef


def _same_timing(left, right):
    return all(math.isclose(a, b, rel_tol=1e-12, abs_tol=0) for a, b in zip(left, right))


@dataclass(frozen=True)
class MoveRequest:
    id: str
    pickup: ExperimentalAction
    move: ExperimentalAction
    dropoff: ExperimentalAction
    reservation: Reservation
    additional_reservation_ids: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "additional_reservation_ids", tuple(self.additional_reservation_ids))
        actions = (self.pickup, self.move, self.dropoff)
        if tuple(a.action_type.value for a in actions) != ("PICKUP", "MOVE", "DROPOFF"):
            raise ValueError("MoveRequest needs PICKUP -> MOVE -> DROPOFF")
        if len({a.id for a in actions}) != 3 or len({a.gate_id for a in actions}) != 1 or len({a.atoms for a in actions}) != 1:
            raise ValueError("Transport actions must be distinct and share gate/atom")
        if any(a.metadata.get("transport_id") != self.id for a in actions):
            raise ValueError("Transport IDs must match")
        if self.move.dependencies != (self.pickup.id,) or self.dropoff.dependencies != (self.move.id,):
            raise ValueError("Invalid transport chain dependencies")
        if self.pickup.targets != self.move.sources or self.move.targets != self.dropoff.sources:
            raise ValueError("Transport endpoints are discontinuous")
        if set(self.dependencies) & set(self.action_ids):
            raise ValueError("Transport entry cannot depend on its own actions")
        expected = {"device/aod": 1, f"atom_lock/{self.atom}": 1}
        if any({r.resource: r.units for r in a.required_resources} != expected for a in actions):
            raise ValueError("Transport actions require exactly AOD and atom custody")
        if (self.reservation.id != self.id or self.reservation.acquire_before != (self.pickup.id,)
                or self.reservation.release_after != (self.dropoff.id,)
                or {r.resource: r.units for r in self.reservation.required_resources} != expected):
            raise ValueError("Transport reservation must span pickup through dropoff")

    @property
    def atom(self): return self.move.atoms[0]

    @property
    def translation(self): return Translation(self.atom, self.move.sources[0].position, self.move.targets[0].position)

    @property
    def action_ids(self): return (self.pickup.id, self.move.id, self.dropoff.id)

    @property
    def dependencies(self): return self.pickup.dependencies

    @property
    def phase_durations(self): return (self.pickup.duration, self.move.duration, self.dropoff.duration)

    @classmethod
    def translation_request(cls, request_id: str, atom: str, source: SiteRef, target: SiteRef,
                            timing: ActionTiming, *, dependencies=()):
        """Construct a standalone transport, e.g. for controller acceptance cases."""
        resources = (ResourceRequirement("device/aod"), ResourceRequirement(f"atom_lock/{atom}"))
        metadata = {"transport_id": request_id}
        def action(suffix, kind, sources, targets, duration, parents):
            return ExperimentalAction(f"{request_id}/{suffix}", request_id, kind, (atom,), duration,
                                      (sources,), (targets,), tuple(parents), resources, metadata)
        pickup = action("pickup", "PICKUP", source, source, timing.pickup_duration, dependencies)
        move = action("move", "MOVE", source, target, source.position.distance_to(target.position)/timing.move_speed, (pickup.id,))
        dropoff = action("dropoff", "DROPOFF", target, target, timing.dropoff_duration, (move.id,))
        return cls(request_id, pickup, move, dropoff, Reservation(request_id, resources, (pickup.id,), (dropoff.id,)))


class TransportCatalog:
    """Extract complete transport chains and determine readiness from the action DAG."""
    def __init__(self, plan: ExperimentalPlan):
        self.plan = plan
        self._actions = {a.id: a for a in plan.actions}
        groups = {}
        for action in plan.actions:
            if action.action_type in ("PICKUP", "MOVE", "DROPOFF"):
                key = action.metadata.get("transport_id")
                if not isinstance(key, str) or not key:
                    raise ValueError("Every transport action requires transport_id")
                groups.setdefault(key, []).append(action)
        leases = {r.id: r for r in plan.reservations}
        requests = []
        for key, actions in groups.items():
            if len(actions) != 3 or key not in leases:
                raise ValueError(f"Incomplete transport chain or lease: {key}")
            by_type = {a.action_type.value: a for a in actions}
            if set(by_type) != {"PICKUP", "MOVE", "DROPOFF"}:
                raise ValueError("Transport must contain exactly one of each phase")
            additional = tuple(r.id for r in plan.reservations if r.id != key
                               and set(r.acquire_before) & {a.id for a in actions})
            requests.append(MoveRequest(key, by_type["PICKUP"], by_type["MOVE"], by_type["DROPOFF"], leases[key], additional))
        self.requests = tuple(requests)
        self.transport_action_ids = frozenset(a for request in requests for a in request.action_ids)

    def ready_requests(self, completed_actions: Iterable[str], *, in_flight: Iterable[str] = ()):
        completed, active = set(completed_actions), set(in_flight)
        if not completed <= self._actions.keys() or not active <= {r.id for r in self.requests}:
            raise ValueError("Unknown completed action or in-flight transport")
        if any(not set(self._actions[a].dependencies) <= completed for a in completed):
            raise ValueError("Completed action set violates dependencies")
        ready = []
        for request in self.requests:
            partial = completed & set(request.action_ids)
            if len(partial) == 3:
                if request.id in active:
                    raise ValueError("Completed transport cannot remain in flight")
                continue
            if partial and request.id not in active:
                raise ValueError("Partially completed transport must be marked in_flight")
            if request.id in active:
                if not set(request.dependencies) <= completed:
                    raise ValueError("In-flight transport has unfinished entry dependencies")
                continue
            if set(request.dependencies) <= completed:
                ready.append(request)
        return tuple(ready)


@dataclass(frozen=True)
class AODMovementEpoch:
    id: str
    requests: tuple[MoveRequest, ...]
    controller: AODController

    def __post_init__(self):
        object.__setattr__(self, "requests", tuple(self.requests))
        reason = self.controller.incompatibility(r.translation for r in self.requests)
        if reason:
            raise ValueError(f"Incompatible epoch: {reason}")
        if len({r.id for r in self.requests}) != len(self.requests):
            raise ValueError("Duplicate epoch request")
        if any(not _same_timing(a.phase_durations, b.phase_durations) for i, a in enumerate(self.requests) for b in self.requests[i + 1:]):
            raise ValueError("Synchronized transport phases require equal durations")
        if set(self.dependencies) & {a for r in self.requests for a in r.action_ids}:
            raise ValueError("Dependent transports cannot share an epoch")

    @property
    def dependencies(self): return tuple(sorted({d for r in self.requests for d in r.dependencies}))

    @property
    def atoms(self): return tuple(r.atom for r in self.requests)

    @property
    def phase_durations(self): return tuple(max(r.phase_durations[i] for r in self.requests) for i in range(3))

    @property
    def duration(self): return sum(self.phase_durations)

    @property
    def reservation(self):
        # One controller, all atom locks. The original leases are REPLACED.
        resources = (ResourceRequirement("device/aod"), *(ResourceRequirement(f"atom_lock/{a}") for a in self.atoms))
        return Reservation(self.id + "/custody", resources, tuple(r.pickup.id for r in self.requests), tuple(r.dropoff.id for r in self.requests))

    @property
    def additional_reservation_ids(self):
        return tuple(sorted({k for r in self.requests for k in r.additional_reservation_ids}))

    def to_dict(self):
        return {"id": self.id, "primitive": "TRANSLATE", "scheduled": False, "start_time": None,
                "request_ids": [r.id for r in self.requests], "atoms": list(self.atoms),
                "displacements": [list(r.translation.displacement) for r in self.requests],
                "sources": [r.move.sources[0].to_dict() for r in self.requests],
                "targets": [r.move.targets[0].to_dict() for r in self.requests],
                "phase_action_ids": {phase: [getattr(r, phase).id for r in self.requests] for phase in ("pickup", "move", "dropoff")},
                "phase_durations": dict(zip(("pickup", "move", "dropoff"), self.phase_durations)),
                "duration": self.duration, "dependencies": list(self.dependencies),
                "tone_counts": dict(zip(("x", "y"), self.controller.tone_counts(r.translation for r in self.requests))),
                "reservation": self.reservation.to_dict(), "replaces_reservation_ids": [r.reservation.id for r in self.requests],
                "additional_reservation_ids": list(self.additional_reservation_ids)}


class MovementPlanner:
    def __init__(self, controller: AODController):
        self.controller = controller

    def plan(self, requests: Iterable[MoveRequest], *, completed_actions: Iterable[str] = ()) -> tuple[AODMovementEpoch, ...]:
        """Stable first-fit grouping of a caller-selected ready frontier.

        Site/zone leases are retained for the future scheduler to check. This
        planner does not lock resources, set priority, or advance time.
        """
        requests, completed = tuple(requests), set(completed_actions)
        if len({r.id for r in requests}) != len(requests):
            raise ValueError("Duplicate move request IDs")
        if len({r.atom for r in requests}) != len(requests):
            raise ValueError("A ready frontier cannot contain two transports for the same atom")
        all_ids = [a for r in requests for a in r.action_ids]
        if len(set(all_ids)) != len(all_ids):
            raise ValueError("Move requests cannot share action IDs")
        if set(all_ids) & completed:
            raise ValueError("Completed/partial transports cannot be replanned")
        for request in requests:
            if not set(request.dependencies) <= completed:
                raise ValueError(f"Transport is not ready: {request.id}")
            reason = self.controller.incompatibility((request.translation,))
            if reason:
                raise ValueError(f"Unserviceable transport {request.id}: {reason}")
        batches = []
        for request in requests:
            for batch in batches:
                if all(_same_timing(r.phase_durations, request.phase_durations) for r in batch) and self.controller.compatible(r.translation for r in (*batch, request)):
                    batch.append(request)
                    break
            else:
                batches.append([request])
        return tuple(AODMovementEpoch(f"epoch/{batch[0].id}", tuple(batch), self.controller) for batch in batches)

    def plan_ready(self, catalog: TransportCatalog, completed_actions: Iterable[str], *, in_flight: Iterable[str] = ()):
        completed = tuple(completed_actions)
        return self.plan(catalog.ready_requests(completed, in_flight=in_flight), completed_actions=completed)

"""Deterministic RESST-style scheduler with persistent spatial leases.

Transport is an indivisible task with three timed trace phases. Only completion
events advance the clock; phase boundaries have no dispatch opportunity because
the AOD remains in custody until dropoff.
"""
from dataclasses import replace
import heapq

from .model import Task, TaskState, Pool, Priority, ResourceLock
from ..lowering.movement_planner import TransportCatalog, MovementPlanner
from ..hardware.atom import AtomState


def build_tasks(plan):
    catalog = TransportCatalog(plan)
    by_entry = {r.pickup.id: r for r in catalog.requests}
    tasks = []
    pools = {'ENTANGLE': Pool.ENTANGLE, 'MEASURE': Pool.MEASURE}
    for action in plan.actions:
        if action.id in by_entry:
            r = by_entry[action.id]
            tasks.append(Task(r.id, Pool.MOVE, (r.pickup, r.move, r.dropoff),
                              r.dependencies, sum(r.phase_durations)))
        elif action.id not in catalog.transport_action_ids:
            tasks.append(Task(action.id, pools.get(action.action_type.value, Pool.SINGLE),
                              (action,), action.dependencies, action.duration))
    owner = {a.id: t.task_id for t in tasks for a in t.actions}
    tails = {}
    for task in reversed(tasks):
        tails[task.task_id] = task.estimated_duration + max(
            (tails[t.task_id] for t in tasks if task.task_id in {owner[d] for d in t.dependencies}), default=0)
        task.priority_vector = Priority(tails[task.task_id])
    return tasks, catalog


class Scheduler:
    def __init__(self, config, *, device_capacities=None):
        self.config = config
        self.device_capacities = dict(config.device_capacities)
        if device_capacities:
            if set(device_capacities) - self.device_capacities.keys():
                raise ValueError('Unknown device capacity')
            self.device_capacities.update(device_capacities)

    def run(self, plan, initial_state):
        tasks, catalog = build_tasks(plan)
        requests = {r.id: r for r in catalog.requests}
        transport_leases = set(requests)
        leases = {r.id: r for r in plan.reservations if r.id not in transport_leases}
        capacities = dict(self.device_capacities)
        for atom in initial_state.atoms:
            capacities[f'atom_lock/{atom.atom_id}'] = 1
        for zone in initial_state.zones:
            if zone.capacity:
                capacities[f'zone/{zone.id}'] = zone.capacity
            capacities.update({f'site/{s.id}': 1 for s in zone.sites})
            capacities.update({f'pair/{zone.id}/{p.id}': 1 for p in zone.pair_slots})
        locks = ResourceLock(capacities)
        active_leases, completed, events, records, spans, decisions = {}, set(), [], [], [], []
        positions = {a.atom_id: plan.home_sites.get(a.atom_id) for a in initial_state.atoms}
        now, serial = 0.0, 0
        planner = MovementPlanner(self.config.aod)

        def acquisition(batch, batch_id):
            entries = {t.actions[0].id for t in batch}
            new = {k: {r.resource: r.units for r in lease.required_resources}
                   for k, lease in leases.items()
                   if k not in active_leases and entries.intersection(lease.acquire_before)}
            resources = {}
            for t in batch:
                for resource, units in t.required_resources.items():
                    resources[resource] = max(resources.get(resource, 0), units)
            return {**new, batch_id: resources}, tuple(new)

        while any(t.status != TaskState.DONE for t in tasks):
            while events and events[0][0] <= now:
                _, _, batch_id, batch = heapq.heappop(events)
                for task in batch:
                    task.status = TaskState.DONE
                    completed.update(a.id for a in task.actions)
                    for atom, target in zip(task.actions[-1].atoms, task.actions[-1].targets):
                        positions[atom] = target
                locks.release(batch_id)
                for key in list(active_leases):
                    if leases[key].release_after and set(leases[key].release_after) <= completed:
                        span = active_leases.pop(key)
                        span['end_time'] = now
                        locks.release(key)
            ready = []
            for task in tasks:
                if task.status in (TaskState.WAITING, TaskState.BLOCKED, TaskState.READY) and set(task.dependencies) <= completed:
                    task.status = TaskState.READY
                    if task.ready_time is None:
                        task.ready_time = now
                    ready.append(task)
            ready.sort(key=lambda t: (-t.priority_vector.critical_path, t.ready_time, t.task_id))
            started = 0
            for first in ready:
                if first.status != TaskState.READY:
                    continue
                batch_id = f'batch/{serial:06d}'
                batch = [first]
                req, new_leases = acquisition(batch, batch_id)
                if not locks.can_acquire(req):
                    first.status = TaskState.BLOCKED
                    continue
                if first.pool in (Pool.MOVE, Pool.ENTANGLE, Pool.MEASURE):
                    for candidate in ready:
                        if candidate is first or candidate.status != TaskState.READY or candidate.pool != first.pool:
                            continue
                        if set(candidate.atoms).intersection(a for t in batch for a in t.atoms):
                            continue
                        trial = batch + [candidate]
                        if first.pool == Pool.MOVE:
                            epochs = planner.plan([requests[t.task_id] for t in trial], completed_actions=completed)
                            if len(epochs) != 1:
                                continue
                        elif (candidate.actions[0].source_zone != first.actions[0].source_zone
                              or candidate.estimated_duration != first.estimated_duration):
                            continue
                        trial_req, trial_leases = acquisition(trial, batch_id)
                        if locks.can_acquire(trial_req):
                            batch, req, new_leases = trial, trial_req, trial_leases
                if first.pool == Pool.MOVE:
                    planner.plan([requests[t.task_id] for t in batch], completed_actions=completed)
                locks.acquire(req)
                for key in new_leases:
                    span = {'owner': key, 'resources': req[key], 'start_time': now, 'end_time': None}
                    spans.append(span)
                    active_leases[key] = span
                duration = max(t.estimated_duration for t in batch)
                spans.append({'owner': batch_id, 'resources': req[batch_id], 'start_time': now, 'end_time': now + duration})
                for task in batch:
                    task.status = TaskState.RUNNING
                    offset = 0.0
                    for action in task.actions:
                        for atom, source in zip(action.atoms, action.sources):
                            if offset == 0 and positions[atom] != source:
                                raise RuntimeError(f'Atom source mismatch: {action.id}')
                        record = action.to_dict()
                        record.update(start_time=now + offset, end_time=now + offset + action.duration,
                                      batch_id=batch_id, task_id=task.task_id,
                                      ready_time=task.ready_time, pool=task.pool.value)
                        records.append(record)
                        offset += action.duration
                heapq.heappush(events, (now + duration, serial, batch_id, batch))
                serial += 1
                started += len(batch)
            decisions.append({'time': now, 'ready_tasks': len(ready), 'started_tasks': started,
                              'blocked_tasks': sum(t.status == TaskState.BLOCKED for t in ready)})
            if events:
                now = events[0][0]
            elif any(t.status != TaskState.DONE for t in tasks):
                blocked = [t.task_id for t in tasks if t.status != TaskState.DONE]
                raise RuntimeError(f'Scheduler deadlock at {now}: {blocked[:8]}')
        for key, span in active_leases.items():
            span['end_time'] = now
            locks.release(key)
        final_atoms = tuple(replace(atom, position=positions[atom.atom_id].position,
                                    zone=positions[atom.atom_id].zone, site_id=positions[atom.atom_id].site,
                                    state=AtomState.IDLE) if positions[atom.atom_id] else atom
                            for atom in initial_state.atoms)
        final_state = replace(initial_state, atoms=final_atoms, current_time=now)
        if any(positions[k] != v for k, v in plan.planned_final_sites.items()):
            raise RuntimeError('Final placement differs from lowered plan')
        return {'schema_version': 1, 'kind': 'execution_trace', 'units': {'length': 'um', 'time': 'us'},
                'initial_state': initial_state.to_dict(), 'final_state': final_state.to_dict(),
                'duration': now, 'actions': sorted(records, key=lambda a: (a['start_time'], a['id'])),
                'resource_spans': spans, 'resource_capacities': capacities, 'decisions': decisions,
                'reservations': [r.to_dict() for r in leases.values()], 'aod': self.config.aod.to_dict(),
                'gate_completion': {k: list(v) for k, v in plan.gate_completion.items()},
                'model_limits': ['Straight-line transport; continuous collision/obstacle avoidance is not modeled.',
                                 'No quantum state, noise, loss or decoder simulation.']}

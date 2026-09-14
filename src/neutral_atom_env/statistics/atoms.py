"""Derived accounting, independent of the planner, Executor and viewer.

Consume a complete ordered committed trace exactly once. Predictions, reserved
resources and skipped classical slots are not physical atom activity. This is
accounting over validated execution, not a replacement physical validator.
"""
from collections import Counter
import csv
import json
from math import hypot, isclose, isfinite
from pathlib import Path

from neutral_atom_env.replay.serializer import primitive

LOAD = {'aod_load', 'aod_recapture'}
OFFLOAD = {'aod_offload', 'aod_park'}
EFFECTS = {'raman_rotation', 'entangling_pulse', 'measurement', 'reset'}


def _union(intervals):
    total = 0.0
    last = float('-inf')
    for left, right in sorted(intervals):
        total += max(0.0, right - max(left, last))
        last = max(last, right)
    return total


class AtomStatistics:
    """Incremental trace consumer. report() returns detached, JSON-ready data.

    Counts commit at operation completion. An in-flight move contributes its
    observed linear/cubic displacement; in-flight activity contributes elapsed
    time. Waiting includes holding still in SLM/AOD and untriggered control slots.
    """

    def __init__(self, atom_ids, gates, *, start_time_us=0.0):
        ids = tuple(atom_ids)
        if len(ids) != len(set(ids)) or not isfinite(start_time_us):
            raise ValueError('Unique atom IDs and a finite start time are required')
        self.start_time_us = float(start_time_us)
        self.time_us = self.start_time_us
        self.processed_records = 0
        self._gates = {g['id']: g for g in primitive(tuple(gates))}
        self._rows = {q: {'distance_um': 0.0, 'load_count': 0, 'offload_count': 0,
                         'gate_counts': Counter(), 'intervals': []} for q in ids}
        self._plan = None
        self._operations = {}
        self._mobile = {}
        self._active = {}
        self._reported = {}

    def observe(self, state, event=None):
        """Read-only callback for a committed Executor/scheduler state.

        Repeated observation is harmless; only new trace entries are consumed.
        Use a new accumulator for a different run or a forked history.
        """
        if len(state.trace.records) < self.processed_records:
            raise ValueError('Cannot reuse statistics after rewinding execution')
        for raw in state.trace.records[self.processed_records:]:
            self.consume(raw)
        if not state.trace.records:
            if state.time_us < self.time_us:
                raise ValueError('Observation time regressed')
            self.time_us = state.time_us

    @classmethod
    def from_state(cls, state, *, start_time_us=0.0):
        stats = cls(state.atoms, state.dag.circuit.gates, start_time_us=start_time_us)
        stats.observe(state)
        return stats

    def consume(self, record):
        """Accept the next committed trace record, never a planned future event."""
        r = json.loads(record) if isinstance(record, str) else record
        event = r['event']
        time = float(event['time_us'])
        if r['sequence'] != self.processed_records:
            raise ValueError('Trace must be complete and consumed exactly once in sequence')
        if not isfinite(time) or time < self.time_us:
            raise ValueError('Trace time must be finite and monotonic')
        kind = event['event_type']
        if kind == 'plan_started':
            if self._plan is not None or self._active:
                raise ValueError('Previous plan has not completed')
            self._plan = event['plan']
            self._operations = {o['id']: o for o in self._plan['operations']}
            self._mobile = {q: h['holder_id'] for q, h in (self._plan.get('initial_placement') or ())
                            if h['holder_type'] == 'mobile'}
            self._reported.update(dict(self._plan.get('initial_measurement_results') or ()))
        elif kind in {'operation_started', 'operation_completed'}:
            if self._plan is None or event['plan_id'] != self._plan['id']:
                raise ValueError('Operation has no matching committed plan')
            op = self._operations[event['operation_id']]
            if kind == 'operation_started':
                self._start(op, r, time)
            else:
                self._complete(op, r, time)
        elif kind == 'plan_completed':
            if self._plan is None or event['plan_id'] != self._plan['id'] or self._active:
                raise ValueError('Plan completion has unfinished operations')
            self._plan = None
            self._operations = {}
        elif kind not in {'wait_completed', 'rng_draw'}:
            raise ValueError('Unsupported execution event for physical atom statistics: ' + kind)
        self.processed_records += 1
        self.time_us = time

    def _start(self, op, record, time):
        key = op['id']
        if key in self._active:
            raise ValueError('Duplicate operation start')
        kind = op['operation_type']
        duration = float(op['duration_us'])
        bindings = op.get('transfer_bindings') or ()
        if not bindings and self._plan.get('execution_mode') != 'scheduled':
            bindings = self._plan.get('bindings', ())
        entry = {'start': time, 'duration': duration, 'kind': kind, 'bindings': bindings,
                 'distances': {}, 'busy': set(), 'gates': (), 'applied': {}}
        if kind == 'aod_move':
            source = record['source_configuration']
            target = record['target_configuration']
            # Each cell follows its own row/column displacement; never divide
            # aggregate atom distance by the number of captured atoms.
            for q in record.get('moving_atom_ids', self._mobile):
                if q not in self._mobile:
                    raise ValueError('Moving atom lacks a committed load or initial mobile holder: ' + q)
                cell = self._mobile[q]
                distance = hypot(target['x_um'][cell['column']] - source['x_um'][cell['column']],
                                 target['y_um'][cell['row']] - source['y_um'][cell['row']])
                entry['distances'][q] = distance
                if distance > 0:
                    entry['busy'].add(q)
            entry['profile'] = record.get('motion_profile', 'linear')
            if entry['profile'] not in {'linear', 'cubic'}:
                raise ValueError('Unsupported movement profile')
        elif kind in LOAD | OFFLOAD:
            entry['busy'] = {b['atom_id'] for b in bindings}
        elif kind in EFFECTS:
            ids = (op.get('gate_ids') or record.get('effect_gate_ids') or record.get('gate_ids')
                   or ((op.get('gate_id') or record.get('gate_id'),)
                       if op.get('gate_id') or record.get('gate_id') else ()))
            if not ids:
                intent = self._plan['intent']
                ids = intent.get('gate_ids') or intent.get('gate_effects') or ()
            if not ids:
                raise ValueError('Effect has no gate IDs')
            entry['gates'] = tuple(ids)
            for gid in ids:
                gate = self._gates[gid]
                condition = gate.get('condition', ())
                if any(g not in self._reported for g, _ in condition):
                    raise ValueError('Conditional gate needs previously committed reported bits')
                applied = all(self._reported[g] == bit for g, bit in condition)
                applied = record.get('applied_by_gate', {}).get(gid, record.get('applied', applied))
                # A batch's aggregate flag cannot override an individual condition.
                if condition:
                    applied = all(self._reported[g] == bit for g, bit in condition)
                entry['applied'][gid] = applied
                if applied:
                    entry['busy'].update(gate['qubit_ids'])
        elif kind != 'trap_switch':
            raise ValueError('Unsupported physical operation: ' + kind)
        if not entry['busy'] <= self._rows.keys():
            raise ValueError('Operation references an unknown atom')
        self._active[key] = entry

    def _complete(self, op, record, time):
        entry = self._active[op['id']]
        if not isclose(time - entry['start'], entry['duration'], rel_tol=0, abs_tol=1e-7):
            raise ValueError('Operation completion time disagrees with start')
        for q in entry['busy']:
            self._rows[q]['intervals'].append((entry['start'], time))
        for q, distance in entry['distances'].items():
            self._rows[q]['distance_um'] += distance
        if entry['kind'] in LOAD | OFFLOAD:
            loading = entry['kind'] in LOAD
            for b in entry['bindings']:
                q = b['atom_id']
                self._rows[q]['load_count' if loading else 'offload_count'] += 1
                if loading:
                    self._mobile[q] = b['cell']
                else:
                    self._mobile.pop(q, None)
        for gid in entry['gates']:
            applied = entry['applied'][gid]
            if 'applied_gate_ids' in record:
                actual = gid in record['applied_gate_ids']
                if actual != applied:
                    raise ValueError('Committed effect differs from reported condition')
            if applied:
                gate = self._gates[gid]
                for q in gate['qubit_ids']:
                    self._rows[q]['gate_counts'][gate['gate_type']] += 1
        self._reported.update(record.get('measurement_results', {}))
        del self._active[op['id']]

    def report(self, *, end_time_us=None):
        """Summarize through the latest observation; never extrapolate the future."""
        end = self.time_us if end_time_us is None else float(end_time_us)
        if not isfinite(end) or end != self.time_us:
            raise ValueError('Report end must equal the latest committed observation')
        elapsed = end - self.start_time_us
        atoms = {}
        for q, row in sorted(self._rows.items()):
            intervals = list(row['intervals'])
            distance = row['distance_um']
            for op in self._active.values():
                observed_end = min(end, op['start'] + op['duration'])
                if q in op['busy']:
                    intervals.append((op['start'], observed_end))
                if q in op['distances']:
                    u = min(1.0, max(0.0, (end - op['start']) / op['duration'])) if op['duration'] else 1.0
                    if op['profile'] == 'cubic':
                        u = u*u*(3-2*u)
                    distance += op['distances'][q] * u
            busy = _union(intervals)
            atoms[q] = {'distance_um': distance, 'load_count': row['load_count'],
                        'offload_count': row['offload_count'],
                        'gate_counts': dict(sorted(row['gate_counts'].items())),
                        'busy_time_us': busy, 'waiting_time_us': max(0.0, elapsed - busy)}
        return {'format': 'neutral-atom-statistics/1', 'window_start_us': self.start_time_us,
                'window_end_us': end, 'elapsed_us': elapsed, 'processed_records': self.processed_records,
                'pending_operations': len(self._active),
                'waiting_definition': 'elapsed minus union of actual movement, transfer and applied effect intervals',
                'counts_commit_at': 'operation_completed', 'atoms': atoms}


def summarize_atoms(state, *, start_time_us=0.0):
    """Rebuild from a state's committed trace without modifying/checkpointing it."""
    return AtomStatistics.from_state(state, start_time_us=start_time_us).report()


def write_atom_statistics(report, directory):
    """Export the same summary as JSON and one CSV row per atom."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'atom_statistics.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    gates = sorted({g for row in report['atoms'].values() for g in row['gate_counts']})
    fields = ['atom_id', 'distance_um', 'load_count', 'offload_count', 'busy_time_us', 'waiting_time_us']
    with (directory / 'atom_statistics.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields + ['gate_' + g for g in gates])
        writer.writeheader()
        for q, row in report['atoms'].items():
            writer.writerow({'atom_id': q, **{f: row[f] for f in fields[1:]},
                             **{'gate_' + g: row['gate_counts'].get(g, 0) for g in gates}})
    return directory / 'atom_statistics.json', directory / 'atom_statistics.csv'

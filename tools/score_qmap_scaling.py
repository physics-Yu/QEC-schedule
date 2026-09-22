"""Figure-2 post-hoc score of audited native QMAP CZ instructions.

Author native operation-time model, not the local continuous-path Executor.
"""
import json
import math
from pathlib import Path
from time import perf_counter

from audit_qmap_hcz import audit, parser_module


def loss_score(n, gates, transfers, spectators, active_us, execution_us):
    idle = [max(0.0, execution_us - value) for value in active_us]
    valid = all(value < 1_500_000.0 for value in idle)
    losses = dict(two_qubit=-gates * math.log(.995) - spectators * math.log(.9975),
                  transfer=-transfers * math.log(.999),
                  decoherence=-sum(math.log1p(-v / 1_500_000.0) for v in idle) if valid else None)
    log_f = -sum(losses.values()) if valid else None
    return dict(losses=losses, log_fidelity=log_f,
                fidelity=math.exp(log_f) if valid else None,
                model_valid=valid, model_status='valid' if valid else 'model_out_of_domain',
                idle_us=idle, execution_us=execution_us, transfers=transfers,
                spectator_excitations=spectators)


def score(directory):
    directory = Path(directory)
    start = perf_counter()
    checks = audit(directory)
    if checks['h_count']:
        raise ValueError('This experiment scores the CZ-only subcircuit; 1Q is not silently removed')
    native = json.loads((directory / 'native.json').read_text(encoding='utf-8'))
    positions, instructions = parser_module.parse((directory / 'program.naviz').read_text())
    n = len(positions)
    arch = native['architecture']
    batches = {layer['source_line']: layer['pairs']
               for layer in json.loads((directory / 'cz-layers.json').read_text())}
    active = [0.0] * n
    transfers = spectators = 0
    t = rearrangement = 0.0
    events = []
    for op in instructions:
        atoms = []
        event = dict(kind=op.kind, source_line=op.line, start_us=t)
        if op.kind in ('load', 'store'):
            dt = arch['operation_duration']['atom_transfer']
            atoms = [int(q[4:]) for q in op.atoms]
            transfers += len(atoms)
            event['atoms'] = atoms
        elif op.kind == 'move':
            # Mirrors the pinned author's Evaluator; exact total checked below.
            if any(v != int(v) for _, point in op.moves for v in point):
                raise ValueError('Fractional coordinates need review against author truncation')
            distance = max((math.dist(positions[q], point) for q, point in op.moves), default=0)
            dt = 2 * (4 * distance / .00044) ** (1 / 3) if distance <= 110 else 200 + (distance - 110) / 1.1
            positions.update(op.moves)
        elif op.kind == 'cz':
            dt = arch['operation_duration']['rydberg_gate']
            atoms = [int(q[4:]) for q, (x, y) in positions.items() if any(
                a[0] <= x <= b[0] and a[1] <= y <= b[1] for a, b in arch['rydberg_range'])]
            pairs = batches[op.line]
            if not {q for pair in pairs for q in pair} <= set(atoms):
                raise AssertionError('CZ outside exposed zone')
            spectators += len(atoms) - 2 * len(pairs)
            event.update(pairs=pairs, exposed_atoms=atoms)
        else:
            raise ValueError(f'Unexpected gate {op.kind}')
        if op.kind != 'cz':
            rearrangement += dt
        for q in atoms:
            active[q] += dt
        t += dt
        event['end_us'] = t
        events.append(event)
    if not math.isclose(rearrangement, native['author_metrics']['rearrangement_us'], rel_tol=1e-10, abs_tol=1e-6):
        raise AssertionError('Native author time mismatch')
    result = loss_score(n, checks['cz_count'], transfers, spectators, active, t)
    result.update(pulses=checks['cz_layers'], max_parallel_cz=checks['max_parallel_cz'],
                  exposure='actual EZ residents', rearrangement_us=rearrangement,
                  time_model='Pinned QMAP author Evaluator movement + architecture transfer/CZ durations')
    (directory / 'score-events.json').write_text(json.dumps(events), encoding='utf-8')
    (directory / 'score.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    checks['author_rearrangement_time_equal'] = True
    return dict(score=result, checks=checks, scoring_seconds=perf_counter()-start)

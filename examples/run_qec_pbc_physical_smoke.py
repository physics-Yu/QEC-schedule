"""One genuine native Z-boundary-check smoke, with preserved physical evidence.

This checks upstream IR -> CZ/H/reset/readout -> physical Executor. It is not
an encoded memory experiment, a complete syndrome round or an FT validation.
"""
import argparse
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def main():
    from neutral_atom_env import NeutralAtomEnv
    from neutral_atom_env.program.task_validation import validate_target
    from neutral_atom_env.replay.serializer import canonical_json
    from neutral_atom_env.visualization import VisualRecorder
    from neutral_atom_experiments.qec_pbc.ir import PBCProgram
    from neutral_atom_experiments.qec_pbc.neutral_atom import build_native_qec_inputs
    from neutral_atom_experiments.qec_pbc.surface import patch_roles, syndrome_round
    from neutral_atom_strategies.scheduling.m3 import initial_terminal
    from neutral_atom_strategies.scheduling.qec import run_qec

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='artifacts/qec-pbc-2026-10-01/physical-smoke')
    args = parser.parse_args()
    output = Path(args.output)
    # Retain previous evidence while making the documented command repeatable.
    attempt = 2
    while output.exists():
        output = Path(args.output).with_name(Path(args.output).name + f'-attempt{attempt}')
        attempt += 1
    output.mkdir(parents=True, exist_ok=False)
    check = replace(syndrome_round()[6], depends_on=())  # A.Z2 = Z0 Z3
    program = PBCProgram(patch_roles('A'), (check,), name='d3-single-Z-boundary-physical-smoke')
    inputs = build_native_qec_inputs(program)
    base = inputs.create_environment()
    plans = []

    class RecordingEnvironment(NeutralAtomEnv):
        def submit(self, plan):
            result = super().submit(plan)
            plans.append(plan)
            return result

    env = RecordingEnvironment(base.state)
    initial = env.snapshot()
    terminal = initial_terminal(env.state)
    recorder = VisualRecorder(env.state)
    (output / 'compiled.json').write_text(canonical_json(inputs.compiled.to_dict()), encoding='utf-8')
    (output / 'platform.json').write_text(canonical_json(inputs.platform), encoding='utf-8')
    (output / 'initial.json').write_text(initial, encoding='utf-8')
    started = perf_counter()
    result = None
    error = None
    audit = {}

    def observe(state, event):
        recorder.observe(state, event)
        if event.event_type.value == 'plan_completed':
            progress = {'plans': len(plans), 'completed_gates': state.metrics()['completed_gate_count'],
                        'total_gates': len(inputs.circuit.gates), 'simulation_time_us': state.time_us,
                        'wall_seconds': perf_counter() - started}
            (output / 'progress.json').write_text(canonical_json(progress), encoding='utf-8')
            print(canonical_json(progress), flush=True)

    try:
        result = run_qec(env, terminal=terminal, on_event=observe,
                         max_decisions=40, candidate_budget=256, route_expansions=50000)
        if result.status != 'completed':
            raise AssertionError(f'Native physical compilation {result.status}: {result.diagnostics}')
        validate_target(terminal, env.state)
        semantic = inputs.compiled.semantic_results(env.state.measurement_results)
        ancilla = dict(inputs.compiled.bindings)[check.ancilla]
        rows = [json.loads(row) for row in env.state.trace.records]
        effect_counts = Counter(g for row in rows if row.get('effect_completed') for g in
            (row.get('effect_gate_ids') or ([row['effect_gate_id']] if row.get('effect_gate_id') else [])))
        audit = {'semantic_results': semantic, 'raw_measurements': dict(env.state.measurement_results),
                 'raw_parity_zero': semantic[check.id] == 0,
                 'ancilla_reset_zero': env.state.quantum_state.expectation({ancilla: 'Z'}) == 1,
                 'dag_complete': env.state.dag.completed,
                 'effects_exactly_once': effect_counts == Counter(g.id for g in inputs.circuit.gates),
                 'terminal_verified': True,
                 'pending_events': bool(env.pending)}
        if not all(audit[key] for key in ('raw_parity_zero', 'ancilla_reset_zero', 'dag_complete',
                                         'effects_exactly_once', 'terminal_verified')) or audit['pending_events']:
            raise AssertionError(f'Physical smoke audit failed: {audit}')
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}

    # Re-submit the actual accepted plans to an independently restored state.
    # This also retains evidence if the original attempt ended in a partial state.
    try:
        replay = NeutralAtomEnv.restore(initial)
        for plan in plans:
            replay.submit(plan)
            replay.run()
        audit['independent_plan_replay_equal'] = replay.snapshot() == env.snapshot()
        if not audit['independent_plan_replay_equal']:
            raise AssertionError('Independent native plan replay differs')
    except Exception as exc:
        audit['independent_plan_replay_equal'] = False
        if error is None:
            error = {'type': type(exc).__name__, 'message': str(exc)}
        else:
            audit['replay_error'] = {'type': type(exc).__name__, 'message': str(exc)}

    evidence = {'status': 'failed' if error else 'completed', 'error': error,
                'output_directory': str(output.resolve()), 'seed': inputs.seed,
                'scope': 'Single Z0 Z3 check on all-zero input; 34 physical atoms, 17 bound roles, '
                         'spectators retained; no encoded memory or circuit-noise FT claim',
                'strategy': 'existing run_qec', 'native_gate_count': len(inputs.circuit.gates),
                'native_cz_count': sum(g.gate_type == 'CZ' for g in inputs.circuit.gates),
                'plans': len(plans), 'wall_seconds': perf_counter() - started,
                'metrics': env.state.metrics(), 'audit': audit,
                'diagnostics': getattr(result, 'diagnostics', ()),
                'candidate_rejections': getattr(result, 'candidate_rejections', ())}
    for filename, data in [('result.json', evidence), ('plans.json', plans),
                           ('recording.json', recorder.payload()),
                           ('decisions.json', getattr(result, 'decision_log', ()) )]:
        (output / filename).write_text(canonical_json(data), encoding='utf-8')
    (output / 'checkpoint.json').write_text(env.snapshot(), encoding='utf-8')
    env.state.trace.write(output / 'trace.jsonl')
    recorder.write(output / 'animation.html')
    print(canonical_json(evidence), flush=True)
    return 1 if error else 0


if __name__ == '__main__':
    raise SystemExit(main())

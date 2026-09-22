"""Coordinate-free interaction requests lowered to validated AOD execution.

Run from the repository root: ``python examples/interaction_ir_demo.py``.
This is an architecture acceptance example, not a performance comparison or a
proof that the bounded IDS resolver finds every physically possible placement.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
from time import perf_counter

from neutral_atom_app.visualization.workbench import build_inputs, initialize_input
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.operations import OperationType
from neutral_atom_env.replay.operation_codec import plan_from_dict
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_strategies.ir import InteractionBlock
from neutral_atom_strategies.zoned.codegen import PhysicalCodegen
from neutral_atom_strategies.zoned.interaction import InteractionCompiler
from neutral_atom_strategies.zoned.placement import IDSPlacer


def demo_input():
    return dict(
        studio={'mode': 'custom'}, circuit_profile='physical',
        atom_count=6, layout='row', seed=13, ez_policy='adaptive',
        ez_neighbor_guard_enabled=True, aod_backend='row_column_orthogonal',
        aod_rows=1, aod_columns=2,
        aod_row_offsets_um=[0], aod_column_offsets_um=[0, 20],
        compilation={'strategy': 'legacy', 'implementation': 'zoned_ids'},
        gates=[dict(id=f'cz{i}', gate_type='CZ',
                    qubit_ids=[f'Q{2*i:03d}', f'Q{2*i+1:03d}'], column=0)
               for i in range(2)])


def run(output, timeout=90):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)

    def write(name, value):
        (output / name).write_text(json.dumps(primitive(value), indent=2,
                                             ensure_ascii=False, allow_nan=False) + '\n',
                                   encoding='utf-8')

    started = perf_counter()
    report = {'status': 'running', 'scope': 'interaction IR architecture acceptance',
              'atom_count': 6, 'gate_count': 2, 'spectators': ['Q004', 'Q005'],
              'optimality_claim': False, 'terminal_contract': 'stable; no original-layout restoration',
              'gui_acceptance': 'not performed; shared viewer artifact only'}
    write('report.json', report)
    env = recorder = lowerer = None
    phase = 'initialize'
    attempts = []
    try:
        value, circuit, platform, placement = build_inputs(demo_input())
        env = NeutralAtomEnv(initialize_input(value, circuit, platform, placement))
        initial = env.snapshot()
        (output / 'initial.json').write_text(initial, encoding='utf-8')
        write('input.json', value)
        recorder = VisualRecorder(env.state)
        block = InteractionBlock.for_gates(circuit.gates, id='demo/cz-pairs')
        intent = block.to_dict()
        write('intent.json', intent)
        # The external request survives serialization without coordinates or
        # trap IDs. Only the separately saved resolved representation has them.
        block = InteractionBlock.from_dict(json.loads(json.dumps(intent)))
        initial_holders = dict(env.state.placement.atom_to_holder)
        initial_positions = {q: env.state.placement.position(q, env.state.world, env.state.aod)
                             for q in report['spectators']}
        deadline = started + timeout
        resolver = IDSPlacer(trials=4, queue_capacity=64, site_limit=8)
        lowerer = PhysicalCodegen(deadline, route_budget=128)
        compiler = InteractionCompiler(resolver, lowerer, deadline)

        phase = 'resolve'
        tick = perf_counter()
        bindings = compiler.resolve(env.state, block.move)
        report['resolve_seconds'] = perf_counter() - tick
        assert env.snapshot() == initial, 'Resolution mutated the live environment'
        write('resolved.json', {'candidates': [b.to_dict() for b in bindings],
                                'selected_index': None})
        phase = 'lower'
        lowered = None
        for index, binding in enumerate(bindings):
            try:
                lowered = compiler.lower(env.state, binding, block.apply)
            except ValidationError as error:
                attempts.append({'candidate': index, 'code': error.violation.code,
                                 'message': error.violation.message})
                continue
            write('resolved.json', {'candidates': [b.to_dict() for b in bindings],
                                    'selected_index': index})
            report['codegen_seconds'] = lowered.codegen_seconds
            report['audit_seconds'] = lowered.audit_seconds
            break
        if lowered is None:
            raise RuntimeError('No candidate lowered successfully; see failed_attempts and route_rejections')
        assert env.snapshot() == initial, 'Lowering mutated the live environment'
        plans = [primitive(lowered.plan)]
        write('plans.json', plans)
        effects = Counter(g for op in lowered.plan.operations
                          if op.operation_type == OperationType.ENTANGLING_PULSE
                          for g in op.effect_gate_ids)
        assert effects == Counter({g.id: 1 for g in circuit.gates}), effects

        def observe(state, event):
            for q in report['spectators']:
                assert state.placement.atom_to_holder[q] == initial_holders[q], q
                assert state.placement.position(q, state.world, state.aod) == initial_positions[q], q
            recorder.observe(state, event)

        phase = 'execute'
        env.submit(lowered.plan)
        env.run(observe)
        assert env.state.dag.completed and not env.pending
        assert not env.state.placement.mobile_occupancy
        (output / 'final.json').write_text(env.snapshot(), encoding='utf-8')

        phase = 'independent_replay'
        replay = NeutralAtomEnv.restore((output / 'initial.json').read_text(encoding='utf-8'))
        for saved in json.loads((output / 'plans.json').read_text(encoding='utf-8')):
            replay.submit(plan_from_dict(saved))
            replay.run()
        assert replay.snapshot() == env.snapshot(), 'Independent replay differs'
        recorder.write_json(output / 'recording.json')
        recorder.write(output / 'replay.html')
        report.update(status='passed', coordinate_free_ir_roundtrip=True,
                      planner_did_not_mutate_env=True, exact_gate_effect_counts=dict(effects),
                      spectators_unchanged_at_every_event=True, independent_replay_equal=True,
                      stable_terminal=True, metrics=env.state.metrics(),
                      physical_operation_count=len(lowered.plan.operations))
    except Exception as error:
        violation = getattr(error, 'violation', None)
        report.update(status='failed', phase=phase,
                      error={'code': violation.code if violation else type(error).__name__,
                             'message': violation.message if violation else str(error)})
        if env is not None:
            (output / 'final.json').write_text(env.snapshot(), encoding='utf-8')
    report.update(wall_seconds=perf_counter() - started, failed_attempts=attempts,
                  codegen_stats=lowerer.stats if lowerer else {},
                  route_rejections=lowerer.rejections if lowerer else [])
    write('report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('artifacts/interaction-ir-demo'))
    parser.add_argument('--timeout', type=float, default=90)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    report = run(args.output, args.timeout)
    print(json.dumps({k: report[k] for k in ('status', 'scope', 'wall_seconds')}, ensure_ascii=False))
    raise SystemExit(0 if report['status'] == 'passed' else 1)


if __name__ == '__main__':
    main()

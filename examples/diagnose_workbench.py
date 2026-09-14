"""Reproduce an exported workbench input with phase timings, outside HTTP timeout.

Instrumentation wraps calls without changing candidates, budgets or physics.
Run only as an offline diagnostic; the live workbench job is never replaced.
"""
import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from neutral_atom_strategies.scheduling import m4
from neutral_atom_strategies.motion.multi_trap import MultiTrapGreedyCompiler
from neutral_atom_strategies.motion.greedy import GreedyCompiler
from neutral_atom_app.visualization.workbench import compile_input
from neutral_atom_env.visualization.viewer import write_html
from neutral_atom_env.replay.serializer import canonical_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    value = json.loads(Path(args.input).read_text(encoding='utf-8'))
    output = Path(args.output); output.mkdir(parents=True, exist_ok=True)
    start = perf_counter()
    stream = (output/'timings.jsonl').open('w', encoding='utf-8')

    def emit(kind, **fields):
        data = dict(kind=kind, elapsed_s=round(perf_counter()-start, 3), **fields)
        line = canonical_json(data)
        stream.write(line+'\n'); stream.flush()
        print(line, flush=True)

    def context(state):
        return dict(simulation_us=state.time_us,
                    completed=[g for g,n in state.dag.nodes.items() if n.status.value=='completed'],
                    ready=[g.id for g in state.dag.ready_gates()])

    compiler_type = MultiTrapGreedyCompiler if value.get('aod_traps', 1)>1 else GreedyCompiler
    original_alternatives = compiler_type.alternatives
    original_select = m4.select_candidate

    def alternatives(compiler, gate_id, state, **options):
        stamp = perf_counter(); emit('candidates_start', gate_id=gate_id, **context(state))
        result = original_alternatives(compiler, gate_id, state, **options)
        emit('candidates_end', gate_id=gate_id, wall_s=round(perf_counter()-stamp, 3),
             legal=len(result[0]), rejected=len(result[1]), omitted=result[2])
        return result

    def select(candidates, state, *rest, **options):
        stamp = perf_counter(); emit('policy_start', candidates=len(candidates), **context(state))
        (output/'last-policy-checkpoint.json').write_text(state.snapshot(), encoding='utf-8')
        result = original_select(candidates, state, *rest, **options)
        emit('policy_end', wall_s=round(perf_counter()-stamp, 3), selected=result[0].key,
             nodes=result[1]['nodes_used'])
        return result

    compiler_type.alternatives = alternatives
    m4.select_candidate = select
    try:
        result, state = compile_input(value, lambda progress: emit('progress', **progress))
        for name, data in [('input', result['input']), ('recording', result['recording']),
                           ('result', {k:v for k,v in result.items() if k!='recording'} | {'metrics':state.metrics()})]:
            (output/(name+'.json')).write_text(canonical_json(data), encoding='utf-8')
        (output/'checkpoint.json').write_text(state.snapshot(), encoding='utf-8')
        (output/'trace.jsonl').write_text('\n'.join(state.trace.records)+'\n', encoding='utf-8')
        write_html(result['recording'], output/'index.html')
        emit('finished', status=result['status'], **context(state), metrics=state.metrics())
        return 0 if result['status']=='completed' else 1
    finally:
        compiler_type.alternatives = original_alternatives
        m4.select_candidate = original_select
        stream.close()


if __name__=='__main__':
    raise SystemExit(main())

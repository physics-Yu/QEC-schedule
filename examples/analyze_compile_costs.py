"""Read-only evidence analysis and bounded, exact replay profiling.

Does not modify the compiler, physics, input, or accepted recordings. The sample
is a prefix, not a full compile benchmark. cProfile timings include overhead.
"""
import argparse
from collections import Counter
import cProfile
import hashlib
import json
from pathlib import Path
import pstats
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=ROOT / 'artifacts/qec-roadmap/step4C-resumed-attempt3')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--plans', type=int, default=3)
    args = parser.parse_args()
    assert 1 <= args.plans <= 8
    args.output.mkdir(parents=True, exist_ok=False)
    source_before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in (ROOT / 'src').rglob('*.py')}
    sizes = Counter(); counts = Counter(); fields = Counter(); selected = []
    current = None; total_ops = 0; first_dag = None
    with (args.source / 'trace.jsonl').open(encoding='utf-8') as stream:
        for raw in stream:
            record = json.loads(raw); event = record['event']; kind = event['event_type']
            sizes[kind] += len(raw.encode('utf-8')); counts[kind] += 1
            if kind == 'plan_started':
                plan = event['plan']; total_ops += len(plan['operations'])
                for key, value in plan.items():
                    fields[key] += len(json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))
                if first_dag is None:
                    first_dag = len(plan['initial_dag'].encode('utf-8'))
                current = [] if len(selected) < args.plans else None
            if current is not None:
                current.append(raw.rstrip('\r\n'))
                if kind == 'plan_completed':
                    selected.append(current); current = None
    rejections = json.loads((args.source / 'candidate_rejections.json').read_text(encoding='utf-8'))
    summary = dict(scope='all accepted trace; suffix-only rejection log',
                   trace_bytes=sum(sizes.values()), counts=dict(counts), bytes_by_event=dict(sizes),
                   plan_field_json_bytes=dict(fields.most_common()), operations=total_ops,
                   first_plan_dag_raw_bytes=first_dag,
                   suffix_rejections=dict(Counter(r.get('violation', {}).get('code') for r in rejections)))
    dump(args.output / 'trace-analysis.json', summary)
    print(json.dumps({k: summary[k] for k in ('trace_bytes', 'counts', 'operations', 'suffix_rejections')}), flush=True)

    from neutral_atom_app.visualization.workbench import build_inputs, initialize_input
    from neutral_atom_env.replay.operation_codec import plan_from_dict
    from neutral_atom_env.simulation.executor import Executor
    raw = json.loads((args.source / 'input.json').read_text(encoding='utf-8'))
    value, circuit, platform, placement = build_inputs(raw)
    state = initialize_input(value, circuit, platform, placement)
    executor = Executor(state); measurements = []
    for index, records in enumerate(selected):
        plan = plan_from_dict(json.loads(records[0])['event']['plan'])
        profiler = cProfile.Profile(); started = perf_counter()
        profiler.enable()
        executor.submit(plan)
        while state.event_queue:
            executor.step()
        profiler.disable()
        seconds = perf_counter() - started
        assert tuple(state.trace.records[-len(records):]) == tuple(records), 'Accepted trace prefix changed'
        profiler.dump_stats(str(args.output / f'plan-{index}.pstats'))
        with (args.output / f'plan-{index}.txt').open('w', encoding='utf-8') as output:
            pstats.Stats(profiler, stream=output).sort_stats('cumulative').print_stats(45)
            pstats.Stats(profiler, stream=output).sort_stats('tottime').print_stats(30)
        stats = pstats.Stats(profiler)
        entries = [dict(file=f, line=line, function=name, primitive_calls=v[0], calls=v[1],
                        self_seconds=v[2], cumulative_seconds=v[3])
                   for (f, line, name), v in stats.stats.items()]
        measurements.append(dict(index=index, planner=plan.planner_id, operations=len(plan.operations),
                                 events=len(records), elapsed_seconds=seconds,
                                 exact_trace_match=True, top=sorted(entries, key=lambda v:-v['cumulative_seconds'])[:45]))
        dump(args.output / 'profile.json', dict(scope='first accepted plans, compiler-free, cProfile overhead included',
                                               atoms=len(state.atoms), gates=len(circuit.gates), samples=measurements))
        print(json.dumps({k:v for k,v in measurements[-1].items() if k != 'top'}), flush=True)
    after = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in (ROOT / 'src').rglob('*.py')}
    assert after == source_before, 'Production source changed during analysis'
    dump(args.output / 'verification.json', dict(status='PASS', source_unchanged=True,
         exact_prefix_events=state.version, plans=len(selected), full_compile_run=False))


if __name__ == '__main__':
    main()

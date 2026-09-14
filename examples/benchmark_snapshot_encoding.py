"""Checkpoint-only encoding microbenchmark; does not compile or execute gates."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from neutral_atom_env.replay.serializer import canonical_json, primitive
from neutral_atom_env.replay.snapshot_encoding import TraceEncodingCache, encode_snapshot, snapshot_digest
from neutral_atom_env.simulation.state import SimulationState


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    timings = {}

    def timed(name, fn):
        start = perf_counter()
        result = fn()
        timings[name] = perf_counter() - start
        print(f'{name}: {timings[name]:.6f}s', flush=True)
        return result

    original = timed('read_file', lambda: args.checkpoint.read_text(encoding='utf-8'))
    state = timed('restore_and_existing_audits', lambda: SimulationState.restore(original))
    payload = timed('fresh_payload', state.snapshot_data)
    converted = timed('reference_primitive', lambda: primitive(payload))
    reference = timed('reference_json_dumps', lambda: json.dumps(converted, sort_keys=True, ensure_ascii=False,
                                                                allow_nan=False, separators=(',', ':')))
    assert reference == original
    del converted
    reference_bytes = timed('reference_utf8', lambda: reference.encode('utf-8'))
    expected = timed('reference_sha256', lambda: sha256(reference_bytes).hexdigest())
    byte_count = len(reference_bytes)
    del reference_bytes, reference
    # A direct oracle call additionally checks the staged baseline above.
    assert timed('reference_canonical_total', lambda: canonical_json(state.snapshot_data())) == original
    cache = TraceEncodingCache()
    cold = timed('new_cold_snapshot', lambda: encode_snapshot(state.snapshot_data(), cache=cache))
    assert cold == original
    del cold
    cold_stats = cache.stats()
    warm = timed('new_warm_snapshot', lambda: encode_snapshot(state.snapshot_data(), cache=cache))
    assert warm == original
    warm_bytes = timed('new_warm_snapshot_utf8', lambda: warm.encode('utf-8'))
    assert timed('new_warm_snapshot_sha256', lambda: sha256(warm_bytes).hexdigest()) == expected
    del warm, warm_bytes
    assert timed('new_warm_stream_hash', lambda: snapshot_digest(state.snapshot_data(), cache=cache)) == expected
    warm_stats = cache.stats()
    cache.clear()
    assert timed('new_cold_stream_hash', lambda: snapshot_digest(state.snapshot_data(), cache=cache)) == expected
    repo = Path(__file__).resolve().parents[1]
    files = ['src/neutral_atom_env/simulation/state.py', 'src/neutral_atom_env/replay/snapshot_encoding.py',
             'src/neutral_atom_env/replay/serializer.py', 'src/neutral_atom_strategies/motion/compiler.py',
             'examples/benchmark_snapshot_encoding.py']
    result = dict(status='PASS', checkpoint=str(args.checkpoint.resolve()), checkpoint_bytes=byte_count,
                  checkpoint_sha256=expected, trace_records=len(state.trace.records), timings_seconds=timings,
                  cache_cold=cold_stats, cache_warm=warm_stats, cache_after_cold_hash=cache.stats(),
                  python=sys.version, platform=platform.platform(),
                  source_sha256={f: sha256((repo / f).read_bytes()).hexdigest() for f in files},
                  scope='One saved checkpoint; exact original JSON and SHA256; no compiler run.',
                  limitations='Single process sample, other agents may be active; not an isolated end-to-end speed comparison.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()

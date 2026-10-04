"""Run in the pinned QMAP interpreter; no legacy ENV execution."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_experiments.qec_pbc.native_kernel_memory import run
from neutral_atom_app.native_kernel_view import export_native_kernel_view

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rounds', type=int, default=2)
    parser.add_argument('--wall-budget', type=float, default=120)
    args = parser.parse_args()
    result, evidence = run(args.output, rounds=args.rounds, wall_budget=args.wall_budget)
    started = perf_counter()
    result['visualization'] = export_native_kernel_view(evidence, args.output)
    result['timings_seconds']['visualization_export'] = perf_counter()-started
    (args.output/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    root = Path(__file__).resolve().parents[1]
    source_paths = [Path(__file__).resolve()]
    for package in ('neutral_atom_kernel', 'neutral_atom_strategies/native_kernel'):
        source_paths.extend((root/'src'/package).glob('*.py'))
    source_paths.extend(root/path for path in (
        'src/neutral_atom_experiments/qec_pbc/native_kernel_memory.py',
        'src/neutral_atom_experiments/qec_pbc/canonical.py',
        'src/neutral_atom_experiments/qec_pbc/ir.py',
        'src/neutral_atom_experiments/qec_pbc/surface.py',
        'src/neutral_atom_app/native_kernel_view.py',
        'src/neutral_atom_env/visualization/viewer.py',
        'src/neutral_atom_env/visualization/viewer.js',
        'src/neutral_atom_env/visualization/viewer-shell.html',
        'src/neutral_atom_env/visualization/summary.py',
        'src/neutral_atom_env/visualization/theme.py',
    ) if (root/path).is_file())
    for module in tuple(sys.modules.values()):
        name = getattr(module, '__file__', None)
        if name:
            path = Path(name).resolve()
            if path.suffix == '.py' and path.is_relative_to(root/'src'):
                source_paths.append(path)
    manifest = {'schema': 'native-kernel-evidence-manifest/1',
        'source_sha256': {p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest() for p in sorted(set(source_paths))},
        'artifact_sha256': {p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(args.output.iterdir())
                            if p.is_file() and p.name != 'manifest.json'},
        'scope': 'Original GateSpec contracts and native request bindings remain in initial.json and unitary-*.native.json; hashes are provenance, not an authenticity signature.'}
    (args.output/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    if result['offline_physical_status'] != 'PASS':
        raise SystemExit(1)

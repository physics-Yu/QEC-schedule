"""Check package dependency direction without importing or running the simulator."""
import argparse
import ast
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ('neutral_atom_env', 'neutral_atom_strategies', 'neutral_atom_experiments', 'neutral_atom_app')
FORBIDDEN = {
    'neutral_atom_env': PACKAGES[1:],
    'neutral_atom_strategies': ('neutral_atom_experiments', 'neutral_atom_app'),
    'neutral_atom_experiments': ('neutral_atom_app',),
    'neutral_atom_app': (),
}


def audit(root=ROOT):
    counts = {}; edges = {}; violations = []
    for package in PACKAGES:
        files = sorted((root/'src'/package).rglob('*.py'))
        counts[package] = len(files)
        for path in files:
            module = '.'.join(path.relative_to(root/'src').with_suffix('').parts)
            parent = module.removesuffix('.__init__') if path.name == '__init__.py' else module.rpartition('.')[0]
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node, ast.Import):
                    targets = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    target = node.module or ''
                    if node.level:
                        target = importlib.util.resolve_name('.'*node.level+target, parent)
                    targets = [target]
                else:
                    continue
                for target in targets:
                    destination = target.partition('.')[0]
                    if destination in PACKAGES and destination != package:
                        key = package+' -> '+destination
                        edges[key] = edges.get(key, 0)+1
                    if destination in FORBIDDEN[package]:
                        violations.append({'file': str(path.relative_to(root)), 'line': node.lineno,
                                           'import': target, 'reason': 'reverse package dependency'})
                    if package == 'neutral_atom_strategies' and (
                        target == 'neutral_atom_env.simulation.executor' or
                        isinstance(node, ast.ImportFrom) and target == 'neutral_atom_env.simulation'
                        and any(a.name == 'Executor' for a in node.names)
                    ):
                        violations.append({'file': str(path.relative_to(root)), 'line': node.lineno,
                                           'import': target, 'reason': 'strategy bypasses environment execution interface'})
    return {'status': 'passed' if not violations else 'failed', 'python_modules': counts,
            'cross_package_import_statements': edges, 'violations': violations}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = audit()
    content = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding='utf-8')
    print(content)
    raise SystemExit(bool(report['violations']))

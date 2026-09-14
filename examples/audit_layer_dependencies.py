"""Static import inventory for architecture review; no production imports run."""
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'src' / 'neutral_atom_env'


def main():
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=False)
    edges = []
    manifest = {}
    for path in sorted(BASE.rglob('*.py')):
        relative = path.relative_to(BASE)
        parts = ['neutral_atom_env', *relative.with_suffix('').parts]
        package = parts[:-1]
        module = '.'.join(parts[:-1] if parts[-1] == '__init__' else parts)
        raw = path.read_bytes()
        manifest[str(path.relative_to(ROOT))] = hashlib.sha256(raw).hexdigest()
        tree = ast.parse(raw, filename=str(relative))
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    prefix = package[:len(package) - node.level + 1]
                    targets = ['.'.join(prefix + (node.module.split('.') if node.module else []))]
                else:
                    targets = [node.module or '']
            for target in targets:
                if not target.startswith('neutral_atom_env.'):
                    continue
                source_layer = relative.parts[0] if len(relative.parts) > 1 else '(root)'
                target_layer = target.split('.')[1]
                if source_layer != target_layer:
                    edges.append(dict(source=module, source_layer=source_layer, target=target,
                                      target_layer=target_layer, line=node.lineno,
                                      file=str(path.relative_to(ROOT))))
    counts = Counter((e['source_layer'], e['target_layer']) for e in edges)
    result = dict(scope='Static import statements, including local imports and test-only code; not a runtime call graph. '
                        'from-package imports are recorded at their declared module; dynamic imports excluded.',
                  python_files=len(manifest), cross_layer_import_statements=len(edges),
                  layer_edges=[dict(source=a, target=b, statements=n) for (a,b),n in sorted(counts.items())],
                  imports=edges)
    (output / 'dependencies.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    (output / 'source-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    focus = [e for e in result['layer_edges'] if (e['source'],e['target']) in {
        ('hardware','simulation'), ('motion','simulation'), ('simulation','motion'),
        ('simulation','visualization'), ('visualization','simulation'), ('simulation','experiments')}]
    print(json.dumps(dict(python_files=len(manifest), focus=focus)))


if __name__ == '__main__':
    main()

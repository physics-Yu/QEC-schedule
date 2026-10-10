"""Reproduce this build's native identity from its verified source snapshot."""
from pathlib import Path
import ast
import hashlib
import json
import tarfile


def frozen_native_sources(dispatch):
    record = json.loads(dispatch.read_bytes())
    inventory = json.loads(dispatch.with_name('source-inventory.json').read_bytes())
    assert inventory == record['snapshot_byte_sha256'], 'DISPATCH_INVENTORY_CHANGED'
    bundle = dispatch.with_name('source.tar.gz')
    assert hashlib.sha256(bundle.read_bytes()).hexdigest() == record['bundle_sha256'], 'FROZEN_BUNDLE_CHANGED'
    prefix = 'src/na_pipeline/'; excluded = {'compiled_modules.py', 'module_graph.py', 'logical_components.py'}
    paths = [p for p in inventory if p.startswith(prefix) and Path(p).parent.as_posix() in
             (prefix+'backend', prefix+'device') and p.endswith('.py') and Path(p).name not in excluded]
    sources = {}
    with tarfile.open(bundle) as archive:
        for p in paths:
            raw = archive.extractfile(p).read()
            value = hashlib.sha256(raw).hexdigest(); assert value == inventory[p], p
            sources[p.removeprefix(prefix)] = value
        name = prefix+'backend/compiled_modules.py'; raw = archive.extractfile(name).read()
        assert hashlib.sha256(raw).hexdigest() == inventory[name]
    tree = ast.parse(raw.decode('utf-8'))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('_translate', '_identity')]
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'CompiledModuleLibrary')
    nodes += [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'compile_module']
    assert len(nodes) == 3
    sources['backend/compiled_modules.py::template_emission'] = hashlib.sha256(ast.dump(ast.Module(body=nodes, type_ignores=[]), include_attributes=False).encode()).hexdigest()
    return sources

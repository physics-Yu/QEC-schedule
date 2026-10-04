"""Call the released QMAP C++ compiler in its pinned Python environment.

This module has no dependency on the legacy evaluator, adapter, or planner.
Bindings and architecture objects are retained across calls; each request still
invokes a fresh RoutingAwareCompiler.compile. Global barriers encode protocol
frontiers, while the original dependency sidecar survives the native format.
"""
from hashlib import sha256
from importlib.metadata import version
import json
from math import ceil, isfinite
from pathlib import Path
from time import perf_counter


_BINDINGS = None
_ARCHITECTURES = {}
OUTPUT_SCHEMA = 'neutral-atom-native-output/1'
REQUEST_SCHEMA = 'neutral-atom-native-request/1'
PINNED_QMAP_VERSION = '3.5.0'
ENGINE = 'mqt.qmap.native.C++'
TIMING_PROFILE = 'project-enola-sqrt-maxaxis-us/v1'
ARCHITECTURE_SOURCE = 'explicit-request-experimental-platform'


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _source_sha256():
    return sha256(Path(__file__).read_bytes()).hexdigest()


def _native_configuration(routing, reuse_level):
    if routing not in {'strict', 'relaxed'}:
        raise ValueError('routing must be strict or relaxed')
    reuse_level = float(reuse_level)
    if not isfinite(reuse_level) or reuse_level < 0:
        raise ValueError('reuse_level must be finite and nonnegative')
    config = dict(log_level='error', max_filling_factor=.9, use_window=True,
        window_min_width=16, window_ratio=1., window_share=.8,
        placement_method='ids', deepening_factor=.01, deepening_value=0.,
        lookahead_factor=.4, reuse_level=reuse_level, trials=4, queue_capacity=100,
        warn_unsupported_gates=False, routing_method=routing)
    if routing == 'relaxed':
        config['prefer_split'] = 1.
    return config


def _request_manifest(*, block_id, atom_ids, contracts, architecture, external,
                      boundaries, dependency_mode, routing, reuse_level,
                      versions, compiler_source_sha256, native_gate_order):
    """Complete canonical compilation request, including its implementation."""
    return dict(schema=REQUEST_SCHEMA, block_id=block_id, atom_ids=list(atom_ids),
        gates=contracts, architecture=architecture, architecture_source=ARCHITECTURE_SOURCE,
        completed_dependencies=list(external), barrier_before=sorted(boundaries),
        dependency_mode=dependency_mode, native_gate_order=list(native_gate_order),
        routing=routing, reuse_level=float(reuse_level),
        native_configuration=_native_configuration(routing, reuse_level),
        engine=ENGINE, versions=dict(versions), compiler_source_sha256=compiler_source_sha256,
        timing_profile=TIMING_PROFILE)


def paired_architecture(atom_count, *, rows=8, columns=16):
    """Declared experimental paired-SLM profile, with 5 um EZ partners.

    SZ pitch is 10 um, EZ column pitch 20 um, and EZ row pitch 10 um. This is
    neither the historical factory geometry nor the paper's 4 um storage grid.
    Measurement zones are supplied separately by the controller.
    """
    if type(atom_count) is not int or atom_count < 1:
        raise ValueError('atom_count must be positive')
    cols = max(4, min(16, ceil(atom_count / 2)))
    sz_rows = max(3, ceil(atom_count / cols) + 1)
    ez_rows = max(2, ceil(ceil(atom_count / 2) / cols))
    ez_y = sz_rows * 10 + 30
    width = max(120, 20 * cols + 30)
    return {
        'name': 'experimental-QMAP-paired-SLM-SZ10-EZ5-column20-row10/v1',
        'operation_duration': {'rydberg_gate': .36, 'single_qubit_gate': 1, 'atom_transfer': 15},
        'operation_fidelity': {'rydberg_gate': .995, 'single_qubit_gate': .9997, 'atom_transfer': .999},
        'qubit_spec': {'T': 1.5e6},
        'storage_zones': [{'zone_id': 0, 'slms': [{'id': 0, 'site_separation': [10, 10],
            'r': sz_rows, 'c': cols, 'location': [0, 0]}], 'offset': [0, 0],
            'dimension': [(cols - 1) * 10, (sz_rows - 1) * 10]}],
        'entanglement_zones': [{'zone_id': 0, 'slms': [{'id': i + 1,
            'site_separation': [20, 10], 'r': ez_rows, 'c': cols,
            'location': [5 * i, ez_y]} for i in range(2)], 'offset': [0, ez_y],
            'dimension': [(cols - 1) * 20 + 5, (ez_rows - 1) * 10]}],
        'aods': [{'id': 0, 'site_separation': 2, 'r': rows, 'c': columns}],
        'arch_range': [[-20, -20], [width, ez_y + (ez_rows - 1) * 10 + 50]],
        'rydberg_range': [[[-20, ez_y - 10], [width, ez_y + (ez_rows - 1) * 10 + 50]]],
    }


def _contracts(gates, atom_ids):
    index = {q: i for i, q in enumerate(atom_ids)}
    if len(index) != len(atom_ids) or not atom_ids or any(not isinstance(q, str) or not q for q in atom_ids):
        raise ValueError('atom_ids must bijectively identify the native wires')
    rows, ids = [], set()
    for i, gate in enumerate(gates):
        if isinstance(gate, dict):
            gid = gate['id']; kind = gate.get('kind', gate.get('type', '')).upper()
            atoms = tuple(gate.get('atoms', gate.get('qubit_ids', ())))
            if not atoms and 'qubits' in gate:
                atoms = tuple(atom_ids[q] for q in gate['qubits'])
            deps = tuple(gate.get('depends_on', ()))
        else:
            gid, kind, atoms, deps = gate.id, gate.kind.upper(), tuple(gate.atoms), tuple(gate.depends_on)
        if not isinstance(gid, str) or not gid or gid in ids:
            raise ValueError('Gate IDs must be unique nonempty strings')
        if kind not in {'H', 'X', 'Y', 'Z', 'T', 'CZ'}:
            raise ValueError(f'{gid}: unsupported unitary gate {kind}; use an explicit physical service boundary')
        if len(atoms) != (2 if kind == 'CZ' else 1) or len(set(atoms)) != len(atoms) or any(q not in index for q in atoms):
            raise ValueError(f'{gid}: invalid native atoms or arity')
        if len(set(deps)) != len(deps) or any(not isinstance(p, str) or not p for p in deps) or gid in deps:
            raise ValueError(f'{gid}: invalid dependencies')
        if isinstance(gate, dict) and gate.get('condition'):
            raise ValueError(f'{gid}: unresolved condition requires a committed report boundary')
        ids.add(gid)
        rows.append({'id': gid, 'type': kind, 'atoms': list(atoms),
            'qubits': [index[q] for q in atoms], 'depends_on': list(deps), 'source_index': i})
    return rows


def _frontiers(contracts, completed_dependencies, barrier_before):
    """O(G+E) direct predecessor ranks; never construct ancestor sets."""
    external = set(completed_dependencies)
    ranks, previous = {}, {}
    for row in contracts:
        parents = set(row['depends_on']) | {previous[q] for q in row['atoms'] if q in previous}
        unresolved = parents - ranks.keys() - external
        if unresolved:
            raise ValueError(f"{row['id']}: dependencies must be in the earlier source prefix or committed: {sorted(unresolved)}")
        ranks[row['id']] = 1 + max((ranks[p] for p in parents if p in ranks), default=-1)
        for q in row['atoms']:
            previous[q] = row['id']
    if barrier_before is not None:
        requested = set(barrier_before)
        if requested - ranks.keys():
            raise ValueError('barrier_before contains unknown gate IDs')
        return contracts, requested, 'explicit-global-frontiers'
    ordered = sorted(contracts, key=lambda row: (ranks[row['id']], row['source_index']))
    boundaries = {row['id'] for previous_row, row in zip(ordered, ordered[1:])
                  if ranks[previous_row['id']] != ranks[row['id']]}
    return ordered, boundaries, 'direct-dependency-rank-global-frontiers'


def compile_native(gates, *, atom_ids, architecture, block_id='native-unitary',
                   completed_dependencies=(), barrier_before=None, routing='strict',
                   reuse_level=0.):
    """Return source NAViz and identity/provenance; do not advance live state."""
    global _BINDINGS
    started = perf_counter()
    atom_ids = tuple(atom_ids)
    contracts = _contracts(tuple(gates), atom_ids)
    external = tuple(completed_dependencies)
    if len(set(external)) != len(external) or any(not isinstance(g, str) or not g for g in external):
        raise ValueError('completed_dependencies must contain unique nonempty gate IDs')
    if not isinstance(block_id, str) or not block_id:
        raise ValueError('block_id must be a nonempty string')
    ordered, boundaries, dependency_mode = _frontiers(contracts, external, barrier_before)
    config = _native_configuration(routing, reuse_level)
    import_started = perf_counter()
    if _BINDINGS is None:
        from mqt.core import load
        from mqt.qmap.na.zoned import (PlacementMethod, RoutingAwareCompiler,
                                     RoutingMethod, ZonedNeutralAtomArchitecture)
        from qiskit import QuantumCircuit
        versions = {name: version(name) for name in ('mqt.qmap', 'mqt.core', 'qiskit')}
        if versions['mqt.qmap'] != PINNED_QMAP_VERSION:
            raise RuntimeError(f'Pinned native compiler requires mqt.qmap 3.5.0: {versions}')
        _BINDINGS = (load, PlacementMethod, RoutingAwareCompiler, RoutingMethod,
                     ZonedNeutralAtomArchitecture, QuantumCircuit, versions)
    load, PlacementMethod, Compiler, RoutingMethod, Architecture, QuantumCircuit, versions = _BINDINGS
    import_seconds = perf_counter() - import_started
    front_started = perf_counter()
    arch_json = _canonical(architecture)
    arch_hash = sha256(arch_json.encode()).hexdigest()
    if arch_hash not in _ARCHITECTURES:
        if len(_ARCHITECTURES) >= 8:
            _ARCHITECTURES.pop(next(iter(_ARCHITECTURES)))
        _ARCHITECTURES[arch_hash] = Architecture.from_json_string(arch_json)
    arch = _ARCHITECTURES[arch_hash]
    qc = QuantumCircuit(len(atom_ids))
    for row in ordered:
        if row['id'] in boundaries:
            qc.barrier(*range(len(atom_ids)))
        getattr(qc, row['type'].lower())(*row['qubits'])
    circuit = load(qc)
    config['placement_method'] = getattr(PlacementMethod, config['placement_method'])
    config['routing_method'] = getattr(RoutingMethod, config['routing_method'])
    compiler = Compiler(arch, **config)
    frontend_seconds = perf_counter() - front_started
    native_started = perf_counter()
    code = compiler.compile(circuit)
    native_seconds = perf_counter() - native_started
    from .lowering import parse_naviz
    native_initial, _ = parse_naviz(code)
    mapping = {f'atom{i}': q for i, q in enumerate(atom_ids)}
    if set(native_initial) != set(mapping):
        raise ValueError('Native output atom declarations do not match requested wire identities')
    source_sha = _source_sha256()
    request = _request_manifest(block_id=block_id, atom_ids=atom_ids, contracts=contracts,
        architecture=architecture, external=external, boundaries=boundaries,
        dependency_mode=dependency_mode, routing=routing, reuse_level=reuse_level,
        versions=versions, compiler_source_sha256=source_sha,
        native_gate_order=(row['id'] for row in ordered))
    return dict(schema=OUTPUT_SCHEMA, status='compiled',
        engine=ENGINE, block_id=block_id, versions=dict(versions), request_manifest=request,
        request_sha256=sha256(_canonical(request).encode()).hexdigest(),
        compiler_source_sha256=source_sha,
        architecture_sha256=arch_hash, architecture=architecture,
        architecture_source=ARCHITECTURE_SOURCE,
        gate_contract=contracts, gate_contract_sha256=sha256(_canonical(contracts).encode()).hexdigest(),
        atom_mapping=mapping, initial_positions={mapping[q]: point for q, point in native_initial.items()},
        completed_dependencies=list(external), barrier_before=sorted(boundaries),
        dependency_mode=dependency_mode, routing=routing, reuse_level=float(reuse_level), code=code,
        naviz_sha256=sha256(code.encode()).hexdigest(), stats=dict(compiler.stats()),
        import_seconds=import_seconds, frontend_seconds=frontend_seconds,
        native_call_seconds=native_seconds, compile_wall_seconds=perf_counter() - started,
        capabilities=dict(external_initial_mapping=False, continuous_placement_input=False,
            nonunitary=False, global_barriers=True, native_aod_assignment=False),
        timing_profile=TIMING_PROFILE, physical_validation='pending')

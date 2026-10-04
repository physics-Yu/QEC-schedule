"""Translate pinned NAViz to compact operations without planning trajectories.

Source IDs are aligned with per-wire queues built once. Protocol dependencies
are checked at effect boundaries, including dependencies between disjoint
wires. A CZ is a zone pulse, so its actual geometric pairs are checked once
while lowering rather than inferred from a repeated global READY scan.
"""
from collections import deque
from dataclasses import dataclass, replace
from hashlib import sha256
from itertools import combinations
import json
from math import hypot, isclose, isfinite, pi, sqrt
import re
from types import MappingProxyType
from typing import Mapping

from neutral_atom_kernel import Operation
from neutral_atom_kernel.model import thaw


_NUMBER = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
_POINT = re.compile(rf'\(({_NUMBER}),\s*({_NUMBER})\)\s+(\w+)$')


@dataclass(frozen=True)
class NativeInstruction:
    kind: str
    atoms: tuple[str, ...] = ()
    moves: tuple[tuple[str, tuple[float, float]], ...] = ()
    parameters: tuple[float, ...] = ()
    zones: tuple[str, ...] = ()
    line: int = 0


@dataclass(frozen=True)
class LoweredProgram:
    initial_positions: Mapping[str, tuple[float, float]]
    final_positions: Mapping[str, tuple[float, float]]
    operations: tuple[Operation, ...]
    native_instructions: tuple[Mapping, ...]
    provenance: Mapping


def _numbers(values, line):
    result = tuple(float(value) for value in values)
    if not all(isfinite(v) for v in result):
        raise ValueError(f'NAViz line {line}: nonfinite coordinates or parameters')
    return result


def parse_naviz(code):
    """Read only pinned compiler syntax; unknown/nonunitary input is an error."""
    initial, out = {}, []
    lines = iter(enumerate(code.splitlines(), 1))
    for number, raw in lines:
        line = raw.strip()
        if not line or line.startswith('//'):
            continue
        if line.startswith('atom '):
            m = _POINT.fullmatch(line[5:])
            if not m or m[3] in initial or out:
                raise ValueError(f'NAViz line {number}: invalid/duplicate/late atom declaration')
            initial[m[3]] = _numbers((m[1], m[2]), number)
            continue
        if not line.startswith('@+ '):
            raise ValueError(f'NAViz line {number}: unsupported syntax {line}')
        kind, _, rest = line[3:].partition(' ')
        if kind not in {'load', 'move', 'store', 'u', 'rz', 'cz'}:
            raise ValueError(f'NAViz line {number}: unsupported operation {kind}; nothing is stripped')
        parameters = []
        for _ in range(3 if kind == 'u' else 1 if kind == 'rz' else 0):
            value, separator, rest = rest.partition(' ')
            if not separator:
                raise ValueError(f'NAViz line {number}: missing parameters/targets')
            parameters.append(value)
        parameters = _numbers(parameters, number)
        entries = [rest]
        if rest == '[':
            entries = []
            for _, item in lines:
                item = item.strip()
                if item == ']':
                    break
                entries.append(item)
            else:
                raise ValueError(f'NAViz line {number}: unclosed block')
        if not entries or any(not item for item in entries):
            raise ValueError(f'NAViz line {number}: empty operation targets')
        if kind == 'move':
            moves = []
            for item in entries:
                m = _POINT.fullmatch(item)
                if not m or m[3] not in initial:
                    raise ValueError(f'NAViz line {number}: invalid move {item}')
                moves.append((m[3], _numbers((m[1], m[2]), number)))
            if len({q for q, _ in moves}) != len(moves):
                raise ValueError(f'NAViz line {number}: duplicate move atom')
            out.append(NativeInstruction(kind, moves=tuple(moves), line=number))
        elif kind == 'cz':
            if len(set(entries)) != len(entries) or any(re.fullmatch(r'zone_cz\d+', z) is None for z in entries):
                raise ValueError(f'NAViz line {number}: invalid CZ zones')
            out.append(NativeInstruction(kind, zones=tuple(entries), line=number))
        else:
            if len(set(entries)) != len(entries) or any(q not in initial for q in entries):
                raise ValueError(f'NAViz line {number}: unknown or duplicate atom')
            out.append(NativeInstruction(kind, atoms=tuple(entries), parameters=parameters, line=number))
    if not initial:
        raise ValueError('NAViz has no initial atoms')
    return initial, tuple(out)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _expected_rotation(kind):
    return {'H': (pi / 2, 0., pi), 'X': (pi, 0., pi),
            'Y': (pi, pi / 2, pi / 2), 'Z': (0., 0., pi),
            'T': (0., 0., pi / 4)}[kind]


def _validate_native_identity(result, gates):
    """Rebuild the complete request; hashes alone are not a source contract."""
    from .compiler import (ARCHITECTURE_SOURCE, ENGINE, OUTPUT_SCHEMA, PINNED_QMAP_VERSION,
        TIMING_PROFILE, _contracts, _frontiers, _request_manifest, _source_sha256)
    required = ('schema', 'status', 'engine', 'block_id', 'versions', 'request_manifest',
        'request_sha256', 'compiler_source_sha256', 'architecture', 'architecture_source',
        'architecture_sha256', 'gate_contract', 'gate_contract_sha256', 'atom_mapping',
        'initial_positions', 'completed_dependencies', 'barrier_before', 'dependency_mode',
        'routing', 'reuse_level', 'timing_profile', 'code', 'naviz_sha256')
    missing = tuple(key for key in required if key not in result)
    if missing:
        raise ValueError(f'Native identity requires all provenance fields; missing {missing}')
    if result['schema'] != OUTPUT_SCHEMA:
        raise ValueError('Unsupported native output schema')
    if result['status'] != 'compiled' or result['engine'] != ENGINE:
        raise ValueError('Expected a completed native C++ compilation')
    if not isinstance(result['block_id'], str) or not result['block_id']:
        raise ValueError('Native block identity must be nonempty')
    versions = result['versions']
    if not isinstance(versions, Mapping) or any(not isinstance(versions.get(key), str) or not versions[key]
                                               for key in ('mqt.qmap', 'mqt.core', 'qiskit')):
        raise ValueError('Native versions must identify every runtime dependency')
    if versions['mqt.qmap'] != PINNED_QMAP_VERSION:
        raise ValueError(f'This native contract requires pinned QMAP {PINNED_QMAP_VERSION}')
    for key in ('request_sha256', 'compiler_source_sha256', 'architecture_sha256',
                'gate_contract_sha256', 'naviz_sha256'):
        if not isinstance(result[key], str) or re.fullmatch('[0-9a-f]{64}', result[key]) is None:
            raise ValueError(f'Native {key} must be a nonempty SHA256 digest')
    if result['compiler_source_sha256'] != _source_sha256():
        raise ValueError('Native compiler source digest differs from the current implementation')
    if result['architecture_source'] != ARCHITECTURE_SOURCE or result['timing_profile'] != TIMING_PROFILE:
        raise ValueError('Native platform/timing provenance differs from this contract')
    code = result['code']
    if not isinstance(code, str) or not code or sha256(code.encode()).hexdigest() != result['naviz_sha256']:
        raise ValueError('Native NAViz digest mismatch')
    architecture = result['architecture']
    if not isinstance(architecture, Mapping) or not architecture or sha256(_canonical(architecture).encode()).hexdigest() != result['architecture_sha256']:
        raise ValueError('Native architecture digest mismatch')
    contracts = result['gate_contract']
    if sha256(_canonical(contracts).encode()).hexdigest() != result['gate_contract_sha256']:
        raise ValueError('Native gate-contract digest mismatch')
    mapping = result['atom_mapping']
    if not isinstance(mapping, Mapping) or not mapping or set(mapping) != {f'atom{i}' for i in range(len(mapping))}:
        raise ValueError('Pinned native wire names must encode every original index')
    atom_ids = tuple(mapping[f'atom{i}'] for i in range(len(mapping)))
    try:
        rebuilt_contracts = _contracts(contracts, atom_ids)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('Malformed native source gate contract') from exc
    if rebuilt_contracts != contracts:
        raise ValueError('Native gate contract does not canonically bind every atom/index/source ID')
    if gates is not None and _contracts(tuple(gates), atom_ids) != rebuilt_contracts:
        raise ValueError('Requested source gates differ from native source contract')
    external = tuple(result['completed_dependencies'])
    if len(set(external)) != len(external) or any(not isinstance(g, str) or not g for g in external):
        raise ValueError('Native completed dependencies must be unique original IDs')
    mode = result['dependency_mode']
    if mode not in {'explicit-global-frontiers', 'direct-dependency-rank-global-frontiers'}:
        raise ValueError('Unknown native dependency encoding')
    barriers = result['barrier_before']
    if not isinstance(barriers, (tuple, list)) or len(set(barriers)) != len(barriers):
        raise ValueError('Native global barriers must identify unique source gates')
    ordered, boundaries, rebuilt_mode = _frontiers(rebuilt_contracts, external,
        barriers if mode == 'explicit-global-frontiers' else None)
    if rebuilt_mode != mode or sorted(boundaries) != list(barriers):
        raise ValueError('Native global barriers differ from reconstructed source dependencies')
    rebuilt_request = _request_manifest(block_id=result['block_id'], atom_ids=atom_ids,
        contracts=rebuilt_contracts, architecture=architecture, external=external,
        boundaries=boundaries, dependency_mode=mode, routing=result['routing'],
        reuse_level=result['reuse_level'], versions=versions,
        compiler_source_sha256=result['compiler_source_sha256'],
        native_gate_order=(row['id'] for row in ordered))
    manifest = result['request_manifest']
    if not isinstance(manifest, Mapping) or not manifest or _canonical(manifest) != _canonical(rebuilt_request):
        raise ValueError('Native request manifest differs from reconstructed source/platform/configuration')
    if sha256(_canonical(rebuilt_request).encode()).hexdigest() != result['request_sha256']:
        raise ValueError('Native request digest mismatch after independent reconstruction')
    return rebuilt_contracts


def lower_native(result, gates=None, *, initial_positions=None,
                 completed_dependencies=None, aod_id='AOD_0',
                 interaction_distance_um=6., nonpartner_minimum_um=10.):
    """Bind native source to operations; the caller binds the live state version.

    Extra initial atoms are preserved as spectators and included in zone-pulse
    pairing. Initial native positions must match live positions; mismatches
    require an explicit transport block before this function is called.
    """
    contracts = _validate_native_identity(result, gates)
    code = result['code']
    architecture = result['architecture']
    initial, instructions = parse_naviz(code)
    names = result['atom_mapping']
    if set(names) != set(initial) or len(set(names.values())) != len(names):
        raise ValueError('Native atom mapping must be a complete bijection')
    native_start = {names[q]: point for q, point in initial.items()}
    supplied_start = result['initial_positions']
    if not isinstance(supplied_start, Mapping) or {q: tuple(point) for q, point in supplied_start.items()} != native_start:
        raise ValueError('Native initial-position metadata differs from raw atom declarations')
    positions = dict(native_start if initial_positions is None else initial_positions)
    for q, point in native_start.items():
        if q not in positions or not all(isclose(a, b, abs_tol=1e-7, rel_tol=0.) for a, b in zip(positions[q], point)):
            raise ValueError(f'Native initial placement mismatch at {q}; explicit transport is required')
    starting = dict(positions)
    by_id, wire_queues = {}, {q: deque() for q in names.values()}
    for row in contracts:
        if row['id'] in by_id:
            raise ValueError('Duplicate source gate identity')
        by_id[row['id']] = row
        for q in row['atoms']:
            if q not in wire_queues:
                raise ValueError('Source gate targets an unmapped atom')
            wire_queues[q].append(row['id'])
    completed = set(result.get('completed_dependencies', ()) if completed_dependencies is None else completed_dependencies)
    if completed.intersection(by_id):
        raise ValueError('A requested native gate has already completed')
    for row in contracts:
        if set(row['depends_on']) - by_id.keys() - completed:
            raise ValueError(f"{row['id']}: external report/gate dependency is not committed")
    zones = {f'zone_cz{i}': (tuple(bounds[0]), tuple(bounds[1]))
             for i, bounds in enumerate(architecture['rydberg_range'])}
    loaded, operations, bound = set(), [], []

    def finish_gate_batch(ids, line):
        if len(set(ids)) != len(ids):
            raise ValueError(f'NAViz line {line}: repeated gate identity in a pulse')
        # Check every gate against the state before this pulse, not against
        # a partially completed batch. This forbids illegal cross-frontier merges.
        for gid in ids:
            row = by_id[gid]
            if set(row['depends_on']) - completed:
                raise ValueError(f'NAViz line {line}: unmet dependency for {gid}')
            if any(not wire_queues[q] or wire_queues[q][0] != gid for q in row['atoms']):
                raise ValueError(f'NAViz line {line}: source per-wire order mismatch for {gid}')
        for gid in ids:
            for q in by_id[gid]['atoms']:
                wire_queues[q].popleft()
        completed.update(ids)

    for index, native in enumerate(instructions):
        atoms = tuple(names[q] for q in native.atoms)
        moves = tuple((names[q], point) for q, point in native.moves)
        metadata = {'source_line': native.line, 'native_kind': native.kind}
        gids, duration, kind = (), 0., native.kind.upper()
        affected = atoms if native.kind != 'move' else tuple(q for q, _ in moves)
        if native.kind == 'cz':
            if any(z not in zones for z in native.zones):
                raise ValueError(f'NAViz line {native.line}: unknown illuminated CZ zone')
            def inside(q):
                x, y = positions[q]
                return any(lo[0] <= x <= hi[0] and lo[1] <= y <= hi[1]
                           for lo, hi in (zones[z] for z in native.zones))
            affected = tuple(q for q in positions if inside(q))
        before = tuple((q, positions[q]) for q in affected)
        if native.kind == 'load':
            if loaded.intersection(atoms):
                raise ValueError(f'NAViz line {native.line}: atom already loaded')
            loaded.update(atoms); duration = 15.
        elif native.kind == 'move':
            if set(affected) - loaded:
                raise ValueError(f'NAViz line {native.line}: moving an atom without AOD support')
            delta = max((abs(b - a) for q, point in moves for a, b in zip(positions[q], point)), default=0.)
            duration = 200 * sqrt(delta / 110)
            positions.update(moves)
        elif native.kind == 'store':
            if set(atoms) - loaded:
                raise ValueError(f'NAViz line {native.line}: storing an atom outside the AOD')
            loaded.difference_update(atoms); duration = 15.
        elif native.kind in {'u', 'rz'}:
            parameters = native.parameters if native.kind == 'u' else (0., 0., native.parameters[0])
            ids = []
            for q in atoms:
                if not wire_queues[q]:
                    raise ValueError(f'NAViz line {native.line}: no source gate for native rotation on {q}')
                gid = wire_queues[q][0]; row = by_id[gid]
                if row['type'] == 'CZ' or not all(isclose(a, b, rel_tol=0., abs_tol=1e-5)
                                                  for a, b in zip(parameters, _expected_rotation(row['type']))):
                    raise ValueError(f'NAViz line {native.line}: native rotation/source parameter mismatch at {gid}')
                ids.append(gid)
            if len({by_id[gid]['type'] for gid in ids}) != 1:
                raise ValueError(f'NAViz line {native.line}: mixed gate types in a local pulse')
            gids = tuple(ids); finish_gate_batch(gids, native.line)
            kind, duration = 'GATE', 1.
            metadata.update(gate_kind=by_id[gids[0]]['type'], u_parameters=parameters,
                            depends_on=tuple((gid, tuple(by_id[gid]['depends_on'])) for gid in gids))
        else:
            pairs, ids = [], []
            for a, b in combinations(sorted(affected), 2):
                distance = hypot(positions[a][0] - positions[b][0], positions[a][1] - positions[b][1])
                if distance <= interaction_distance_um + 1e-9:
                    if not wire_queues.get(a) or not wire_queues.get(b):
                        raise ValueError(f'NAViz line {native.line}: unintended CZ pair {(a, b)}')
                    ga, gb = wire_queues[a][0], wire_queues[b][0]
                    if ga != gb or by_id[ga]['type'] != 'CZ' or set(by_id[ga]['atoms']) != {a, b}:
                        raise ValueError(f'NAViz line {native.line}: unintended/not-ready CZ pair {(a, b)}')
                    pairs.append((a, b)); ids.append(ga)
                elif distance + 1e-9 < nonpartner_minimum_um:
                    raise ValueError(f'NAViz line {native.line}: CZ nonpartner separation below {nonpartner_minimum_um} um for {(a, b)}')
            if not pairs:
                raise ValueError(f'NAViz line {native.line}: CZ pulse has no intended physical pairs')
            gids = tuple(ids); finish_gate_batch(gids, native.line)
            atoms = tuple(dict.fromkeys(q for pair in pairs for q in pair))
            kind, duration = 'CZ', .36
            metadata.update(zone_ids=native.zones, zone_bounds={z: zones[z] for z in native.zones},
                cz_pairs=tuple(pairs), gate_kind='CZ', interaction_distance_um=interaction_distance_um,
                nonpartner_minimum_um=nonpartner_minimum_um,
                depends_on=tuple((gid, tuple(by_id[gid]['depends_on'])) for gid in gids))
        metadata['bound_positions_before'] = before
        metadata['bound_positions_after'] = tuple((q, positions[q]) for q in affected)
        bound.append(dict(metadata, instruction_index=index, atoms=atoms,
                          native_parameters=native.parameters, native_zones=native.zones))
        operations.append(Operation(id=f"{result['block_id']}:native:{index:06d}", kind=kind,
            atoms=atoms if native.kind != 'move' else affected, duration_us=duration,
            positions=moves if native.kind == 'move' else (), gate_ids=gids,
            aod_id=aod_id, metadata=metadata))
    if loaded:
        raise ValueError('Native terminal contract leaves AOD atoms loaded')
    missing = set(by_id) - completed
    if missing or any(wire_queues.values()):
        raise ValueError(f'Native source gates were not executed exactly once: {sorted(missing)}')
    provenance = {key: result[key] for key in ('schema', 'engine', 'versions', 'block_id',
        'request_sha256', 'architecture_sha256', 'gate_contract_sha256', 'naviz_sha256',
        'dependency_mode', 'timing_profile', 'architecture_source', 'reuse_level') if key in result}
    if 'compiler_source_sha256' in result:
        provenance['compiler_source_sha256'] = result['compiler_source_sha256']
    provenance.update(physical_validation='lowering-CZ-pairs-only; offline-audit-pending',
        aod_id=aod_id, movement_timing='200*sqrt(max_axis_displacement_um/110) us',
        native_instruction_count=len(instructions), operation_count=len(operations))
    return LoweredProgram(MappingProxyType(starting), MappingProxyType(dict(positions)),
        tuple(operations), tuple(bound), MappingProxyType(provenance))


def _axis_slots(snapshots, dimension):
    """Keep shared axis identities and monotone order across one loaded interval."""
    atoms = sorted({q for snapshot in snapshots for q in snapshot})
    parents = {q: q for q in atoms}
    def root(q):
        while parents[q] != q:
            parents[q] = parents[parents[q]]
            q = parents[q]
        return q
    for snapshot in snapshots:
        values = {}
        for q, point in snapshot.items():
            coordinate = point[dimension]
            if coordinate in values:
                parents[root(q)] = root(values[coordinate])
            else:
                values[coordinate] = q
    edges = {root(q): set() for q in atoms}
    for snapshot in snapshots:
        values = {}
        for q, point in snapshot.items():
            key, coordinate = root(q), point[dimension]
            if key in values and values[key] != coordinate:
                raise ValueError('Native transport splits a shared AOD axis')
            values[key] = coordinate
        order = sorted(values, key=values.get)
        for a, b in zip(order, order[1:]):
            edges[b].add(a)
    order = []
    while edges:
        ready = sorted(q for q, deps in edges.items() if not deps)
        if not ready:
            raise ValueError('Native transport crosses AOD axes')
        q = ready[0]; order.append(q); del edges[q]
        for deps in edges.values():
            deps.discard(q)
    ranks = {q: index for index, q in enumerate(order)}
    return {q: ranks[root(q)] for q in atoms}


def _transport_slots(operations, initial_positions, initial_holders):
    positions = dict(initial_positions)
    loaded = {}
    for q, holder in initial_holders.items():
        if holder != 'slm':
            loaded.setdefault(holder, set()).add(q)
    if any(loaded.values()):
        raise ValueError('Axis finalization requires a service/native boundary with empty AODs')
    starts, snapshots, assignments = {}, {}, {}
    for index, op in enumerate(operations):
        device = op.aod_id
        carried = loaded.setdefault(device, set())
        if op.kind == 'LOAD':
            if not carried:
                starts[device], snapshots[device] = index, []
            if carried.intersection(op.atoms):
                raise ValueError('Axis finalization found duplicate LOAD')
            carried.update(op.atoms)
        elif op.kind == 'MOVE':
            if set(op.atoms) - carried:
                raise ValueError('Axis finalization found unsupported MOVE atoms')
            positions.update(op.positions)
        if carried:
            snapshots[device].append({q: positions[q] for q in carried})
        if op.kind == 'STORE':
            if set(op.atoms) - carried:
                raise ValueError('Axis finalization found unsupported STORE atoms')
            carried.difference_update(op.atoms)
            if not carried:
                axes = (_axis_slots(snapshots[device], 0), _axis_slots(snapshots[device], 1))
                for item in range(starts[device], index + 1):
                    if operations[item].aod_id == device:
                        assignments[item] = axes
    if any(loaded.values()):
        raise ValueError('Axis finalization needs a complete LOAD/STORE interval')
    return assignments


def _fill_slots(fixed, current, lower, upper, gap):
    count = len(current)
    if not count or any(i < 0 or i >= count for i in fixed):
        raise ValueError('Native transport exceeds declared physical RF axis capacity')
    anchors = [(-1, lower - gap), *sorted(fixed.items()), (count, upper + gap)]
    result = list(current)
    for (left, lo), (right, hi) in zip(anchors, anchors[1:]):
        if hi - lo + 1e-8 < gap * (right - left):
            raise ValueError('Native active axes and disabled RF spares do not fit declared bounds/spacing')
        previous = lo
        for i in range(left + 1, right):
            result[i] = max(previous + gap, min(result[i], hi - gap * (right - i)))
            previous = result[i]
        if right < count:
            result[right] = hi
    return tuple(result)


def finalize_operations(operations, initial_positions, *, initial_axes,
                        initial_holders=None, bounds, minimum_axis_spacing_um=2.):
    """Add explicit empty-AOD positioning and full RF-axis timing, without routing.

    ``initial_axes`` maps each device to full ordered ``x_um``/``y_um`` arrays
    (``columns``/``rows`` are also accepted, matching executor.observe.aod_axes).
    ``bounds`` is (xmin, ymin, xmax, ymax). The returned immutable tuple preserves
    every input operation ID and endpoint, inserting CONFIGURE before empty
    LOADs as required. Repeated calls use the committed observation's axes.
    Disabled spare axes are recorded explicitly and obey the same bounds and
    minimum spacing. No active-only timing or zero-cost device reset is used.
    """
    operations = tuple(operations)
    positions = dict(initial_positions)
    holders = {q: 'slm' for q in positions}
    holders.update(initial_holders or {})
    axes = {}
    for device, vectors in initial_axes.items():
        columns = tuple(vectors.get('x_um', vectors.get('columns', ())))
        rows = tuple(vectors.get('y_um', vectors.get('rows', ())))
        if not columns or not rows or not all(isfinite(v) for v in columns + rows):
            raise ValueError('Axis finalization requires explicit finite nonempty initial RF arrays')
        axes[device] = (columns, rows)
    assignments = _transport_slots(operations, positions, holders)
    loaded, out = {}, []
    xmin, ymin, xmax, ymax = bounds
    gap = float(minimum_axis_spacing_um)
    if not isfinite(gap) or gap <= 0:
        raise ValueError('minimum_axis_spacing_um must be positive')
    def axis_payload(value):
        return {'columns': value[0], 'rows': value[1]}
    def duration(a, b):
        d = max((abs(y - x) for av, bv in zip(a, b) for x, y in zip(av, bv)), default=0.)
        return 200 * sqrt(d / 110)
    def target_axes(index, atoms):
        device = operations[index].aod_id
        if device not in axes:
            raise ValueError(f'{device}: initial RF axes are required to charge empty positioning')
        bindings = assignments[index]
        fixed = ({}, {})
        for q in atoms:
            for dimension in (0, 1):
                slot, coordinate = bindings[dimension][q], positions[q][dimension]
                if slot in fixed[dimension] and fixed[dimension][slot] != coordinate:
                    raise ValueError('Native transport splits shared RF axes')
                fixed[dimension][slot] = coordinate
        return (_fill_slots(fixed[0], axes[device][0], xmin, xmax, gap),
                _fill_slots(fixed[1], axes[device][1], ymin, ymax, gap))
    for index, op in enumerate(operations):
        device = op.aod_id
        carried = loaded.setdefault(device, set())
        metadata = thaw(op.metadata)
        if op.kind == 'CONFIGURE':
            if carried:
                raise ValueError('Explicit CONFIGURE occurs while AOD is loaded')
            values = metadata['target_axes']
            target = (tuple(values['columns']), tuple(values['rows']))
            if device not in axes or len(target[0]) != len(axes[device][0]) or len(target[1]) != len(axes[device][1]):
                raise ValueError('Explicit CONFIGURE changes declared RF axis capacity')
            metadata['source_axes'] = axis_payload(axes[device])
            out.append(replace(op, duration_us=duration(axes[device], target), metadata=metadata))
            axes[device] = target
            continue
        if op.kind == 'LOAD':
            if any(holders.get(q) != 'slm' for q in op.atoms):
                raise ValueError('LOAD must use committed SLM holders')
            target = target_axes(index, carried | set(op.atoms))
            if not carried and target != axes[device]:
                out.append(Operation(id=op.id + ':empty-configure', kind='CONFIGURE',
                    duration_us=duration(axes[device], target), aod_id=device,
                    metadata={'source_axes': axis_payload(axes[device]), 'target_axes': axis_payload(target),
                        'source_line': metadata.get('source_line'), 'before_operation': op.id,
                        'reason': 'Explicit empty RF positioning before unchanged native/service LOAD'}))
                axes[device] = target
            elif carried and target != axes[device]:
                # NAViz omits unoccupied RF lines. Position these explicit
                # disabled lines while keeping every carried atom fixed.
                # This is a timed support operation, not a new atom route.
                out.append(Operation(id=op.id + ':spare-positioning', kind='MOVE',
                    atoms=tuple(sorted(carried)), positions=tuple((q, positions[q]) for q in sorted(carried)),
                    duration_us=duration(axes[device], target), aod_id=device,
                    metadata={'source_axes': axis_payload(axes[device]), 'target_axes': axis_payload(target),
                        'source_line': metadata.get('source_line'), 'before_operation': op.id,
                        'native_kind': 'explicit-disabled-rf-positioning',
                        'active_rows': tuple(sorted({positions[q][1] for q in carried})),
                        'active_columns': tuple(sorted({positions[q][0] for q in carried})),
                        'rf_axis_scope': 'full-capacity-with-explicit-disabled-spares',
                        'reason': 'Position unused RF lines for native partial LOAD; carried atoms stay fixed'}))
                axes[device] = target
            carried.update(op.atoms)
            holders.update({q: device for q in op.atoms})
            metadata.update(source_axes=axis_payload(axes[device]), target_axes=axis_payload(axes[device]))
        elif op.kind == 'MOVE':
            positions.update(op.positions)
            target = target_axes(index, carried)
            metadata.update(source_axes=axis_payload(axes[device]), target_axes=axis_payload(target))
            op = replace(op, duration_us=duration(axes[device], target))
            axes[device] = target
        elif op.kind == 'STORE':
            carried.difference_update(op.atoms)
            holders.update({q: 'slm' for q in op.atoms})
            metadata.update(source_axes=axis_payload(axes[device]), target_axes=axis_payload(axes[device]))
        if op.kind in {'LOAD', 'MOVE', 'STORE'}:
            metadata['rf_axis_scope'] = 'full-capacity-with-explicit-disabled-spares'
            metadata['active_rows'] = tuple(sorted({positions[q][1] for q in carried}))
            metadata['active_columns'] = tuple(sorted({positions[q][0] for q in carried}))
        out.append(replace(op, metadata=metadata))
    return tuple(out)

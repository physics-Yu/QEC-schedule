"""Bounded, provenance-checked Clifford prefix from a saved encoded Shor run.

Only the first twelve RESET/CSS/canonical pairs are admitted. The exported
writer's global serial chain is replaced by the original encoder and canonical
template dependencies, keeping syndrome phase barriers and every raw readout.
This adapter does not reschedule adaptive injections or synthesize magic states.
"""
from collections import Counter
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import (GridCoord, PhysicalGate, Position2D,
    Rectangle, StaticTrap, Zone, ZoneType)
from neutral_atom_env.domain.operations import HardwareConfig
from neutral_atom_env.platform import Platform, initialize
from neutral_atom_env.quantum.stabilizer import StabilizerState
from neutral_atom_env.world import AODRuntimeState, WorldState

from .canonical import canonical_memory_program
from .encoded_resource_reference import build_css_isometry
from .surface import patch_roles


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _rows(path, count):
    raw, rows = [], []
    with Path(path).open('rb') as stream:
        for _ in range(count):
            line = stream.readline()
            if not line:
                raise ValueError('Saved prefix is truncated')
            raw.append(line)
            rows.append(json.loads(line))
    return rows, raw


def _source_manifest(directory):
    raw = (directory / 'manifest.json').read_bytes()
    value = json.loads(raw)
    if value.get('schema') != 'encoded-native-prefix-packet/1':
        return raw, value
    expected_names = {'mother-manifest.json', 'roles.json', 'functions.jsonl',
                      'native_gates.jsonl', 'native_projections.jsonl'}
    if (value.get('complete_packet') is not True or
            value.get('whole_native_stream_included') is not False or
            set(value.get('files', {})) != expected_names):
        raise ValueError('Invalid bounded source packet contract')
    for name, descriptor in value['files'].items():
        content = (directory/name).read_bytes()
        if len(content) != descriptor['bytes'] or _digest(content) != descriptor['sha256']:
            raise ValueError('Bounded source packet bytes/hash changed: ' + name)
    raw = (directory/'mother-manifest.json').read_bytes()
    if _digest(raw) != value['source_manifest_sha256']:
        raise ValueError('Bounded packet source manifest identity changed')
    return raw, json.loads(raw)


@dataclass(frozen=True)
class NativeParallelPrefix:
    circuit: PhysicalCircuit
    patches: tuple[str, ...]
    bindings: tuple[tuple[str, str], ...]
    source: dict
    phases: tuple[dict, ...]

    def circuit_dict(self):
        return {'schema': 'encoded-native-parallel-prefix-circuit/1',
            'gates': [asdict(gate) for gate in self.circuit.gates]}


def load_native_parallel_prefix(directory, *, patch_count=12, include_magic=False):
    """Validate the complete fixed prefix before selecting 1/2/4/12 patches.

    Full multi-GB suffixes are neither loaded nor claimed to have been executed.
    Selected function spans are authenticated using the immutable manifest and
    each function's original byte-span hashes, then checked against templates.
    """
    if type(patch_count) is not int or patch_count not in (1, 2, 4, 12):
        raise ValueError('This bounded platform supports 1, 2, 4 or 12 patches')
    directory = Path(directory)
    manifest_raw, manifest = _source_manifest(directory)
    if manifest.get('schema') != 'encoded-native-run-manifest/1' or not manifest.get('complete'):
        raise ValueError('A completed saved encoded-native source is required')
    roles_raw = (directory / 'roles.json').read_bytes()
    if _digest(roles_raw) != manifest['artifacts']['roles.json']['sha256']:
        raise ValueError('Saved roles differ from the source manifest')
    roles = json.loads(roles_raw)
    patches = tuple(roles['algorithm_patches'])
    if patches != (*tuple(f'phase{i}' for i in range(8)), *tuple(f'work{i}' for i in range(4))):
        raise ValueError('Only the fixed complete 8-phase/4-work source is admitted')
    binding = {row['role']: row['id'] for row in roles['roles']}
    if len(binding) != len(roles['roles']) or len(set(binding.values())) != len(binding):
        raise ValueError('Saved physical role identities must be unique')
    functions, function_raw = _rows(directory / 'functions.jsonl', 24)
    if functions[-1]['gate_end'] != 2988:
        raise ValueError('Expected twelve complete 249-native initialization blocks')
    original, native_raw = _rows(directory / 'native_gates.jsonl', 2988)
    projections, projection_raw = _rows(directory / 'native_projections.jsonl', 396)
    projection_by_id = {row['native_gate_id']: row for row in projections}
    if len(projection_by_id) != 396:
        raise ValueError('Every saved raw projection needs a distinct actual native gate')
    rewritten, phases = [], []
    for patch_index, patch in enumerate(patches):
        namespace = f'shot0.encode.{patch}'
        reset = tuple(PhysicalGate(f'{namespace}.reset{i}', 'RESET', (binding[role.id],))
            for i, role in enumerate(patch_roles(patch)))
        reset_frontier = tuple(g.id for g in reset)
        encoder = build_css_isometry(patch=patch,
            data_qubits=tuple(binding[f'{patch}.d{i}'] for i in range(9)), namespace=namespace)
        encoded = tuple(replace(g, depends_on=g.depends_on or reset_frontier)
            for g in encoder.isometry_circuit.gates)
        template = canonical_memory_program(patch=patch, rounds=1)
        retained = {key for phase in template.phases if phase.round_index is not None for key in phase.gate_ids}
        canonical = []
        for operation in template.program.operations:
            if operation.id not in retained:
                continue
            deps = tuple(namespace + '.check.' + parent for parent in operation.depends_on if parent in retained)
            canonical.append(PhysicalGate(namespace + '.check.' + operation.id, operation.gate_type,
                tuple(binding[role] for role in operation.targets), depends_on=deps or (encoded[-1].id,)))
        expected_groups = (reset + encoded, tuple(canonical))
        for within, (kind, expected) in enumerate(zip(('data_encode', 'canonical_check'), expected_groups)):
            function = functions[2 * patch_index + within]
            start, end = function['gate_start'], function['gate_end']
            rows = original[start:end]
            ps = function['projection_start']
            pe = ps + function['projection_count']
            if (function['index'] != 2 * patch_index + within or function['kind'] != kind or
                    function['shot_index'] != 0 or function['injection_index'] is not None or
                    function['context']['patch'] != patch or len(rows) != len(expected) or
                    _digest(b''.join(native_raw[start:end])) != function['native_sha256'] or
                    _digest(b''.join(projection_raw[ps:pe])) != function['projection_sha256']):
                raise ValueError('Saved function span or protocol metadata was altered')
            for row, gate in zip(rows, expected):
                i = row['index']
                if (i != start or row['id'] != gate.id or row['gate_type'] != gate.gate_type or
                        tuple(row['qubit_ids']) != gate.qubit_ids or row['condition'] or
                        row['depends_on'] != ([original[i - 1]['id']] if i else [])):
                    raise ValueError('Source is not the unchanged serial native initialization prefix')
                if tuple(binding[role] for role in row['role_ids']) != gate.qubit_ids:
                    raise ValueError('Saved atom and role targets disagree')
                if gate.gate_type in ('RESET', 'MEASURE'):
                    report = projection_by_id.get(gate.id)
                    if not report or report['kind'] != gate.gate_type or report['outcome'] != 0 or report['conditional_probability'] != 1.:
                        raise ValueError('Initial +1-sector prefix requires its saved deterministic zero reports')
                start += 1
        if patch_index < patch_count:
            rewritten.extend(reset + encoded + tuple(canonical))
            phases.append({'id': namespace + '.reset', 'patch': patch, 'kind': 'initialize_reset',
                'gate_ids': list(reset_frontier), 'source_function': functions[2 * patch_index]['function_id']})
            phases.extend({'id': g.id, 'patch': patch, 'kind': 'css_encoding', 'gate_ids': [g.id],
                'source_function': functions[2 * patch_index]['function_id']} for g in encoded)
            phases.extend({'id': namespace + '.check.' + phase.id, 'patch': patch, 'kind': phase.kind,
                'gate_ids': [namespace + '.check.' + gid for gid in phase.gate_ids],
                'source_function': functions[2 * patch_index + 1]['function_id']} for phase in template.phases
                if phase.round_index is not None)
    cut = 249 * patch_count
    selected_ids = {gate.id for gate in rewritten}
    selected_reports = [report for report in projections if report['native_gate_id'] in selected_ids]
    chosen_rows = list(original[:cut])
    chosen_functions = list(functions[:2 * patch_count])
    selected_bindings = [(role.id, binding[role.id]) for patch in patches[:patch_count] for role in patch_roles(patch)]
    partial_functions = []
    if include_magic:
        all_functions, _ = _rows(directory / 'functions.jsonl', 25)
        producer = all_functions[-1]
        if producer['kind'] != 'resource_prepare' or producer['gate_start'] != 2988:
            raise ValueError('The first saved resource producer must immediately follow the fixed algorithm prefix')
        producer_rows, producer_raw = _rows(directory / 'native_gates.jsonl', producer['gate_end'])
        all_projections, all_projection_raw = _rows(directory / 'native_projections.jsonl',
            producer['projection_start'] + producer['projection_count'])
        if (_digest(b''.join(producer_raw[2988:])) != producer['native_sha256'] or
                _digest(b''.join(all_projection_raw[producer['projection_start']:])) != producer['projection_sha256']):
            raise ValueError('Saved first resource producer no longer matches its authenticated function spans')
        namespace = 'shot0.resource00000.producer'
        resets = tuple(PhysicalGate(namespace + f'.reset{i}', 'RESET', (binding[role.id],))
            for i, role in enumerate(patch_roles('resource')))
        first_h = PhysicalGate(namespace + '.logical_input.h', 'H', (binding['resource.d0'],),
            depends_on=tuple(g.id for g in resets))
        magic = (*resets, first_h)
        selected_magic_rows = producer_rows[2988:3006]
        for gate, row in zip(magic, selected_magic_rows):
            if (gate.id != row['id'] or gate.gate_type != row['gate_type'] or list(gate.qubit_ids) != row['qubit_ids']
                    or row['condition']):
                raise ValueError('The saved resource Clifford prefix differs from actual 17 RESETs followed by H')
        if producer_rows[3006]['gate_type'] != 'T' or producer_rows[3006]['qubit_ids'] != [binding['resource.d0']]:
            raise ValueError('Stop boundary must be immediately before the first actual resource T')
        magic_ids = {g.id for g in resets}
        magic_reports = [r for r in all_projections if r['native_gate_id'] in magic_ids]
        if len(magic_reports) != 17 or any(r['outcome'] != 0 or r['conditional_probability'] != 1. for r in magic_reports):
            raise ValueError('Resource Clifford reset prefix requires all actual known-zero raw projections')
        rewritten.extend(magic)
        chosen_rows.extend(selected_magic_rows)
        chosen_functions.append(producer)
        selected_reports.extend(magic_reports)
        selected_bindings.extend((role.id, binding[role.id]) for role in patch_roles('resource'))
        partial_functions.append({'function_id': producer['function_id'], 'executed_gate_span': [2988, 3006],
            'authenticated_full_function_gate_span': [2988, producer['gate_end']],
            'stop_before_native_gate_id': producer_rows[3006]['id'],
            'state_at_stop': 'unencoded |+> on resource.d0 with the other16 carriers zero; no magic state yet'})
        phases.append({'id': namespace + '.reset', 'patch': 'resource', 'kind': 'resource_clifford_reset',
            'gate_ids': [g.id for g in resets], 'source_function': producer['function_id']})
        phases.append({'id': first_h.id, 'patch': 'resource', 'kind': 'resource_before_first_t',
            'gate_ids': [first_h.id], 'source_function': producer['function_id']})
    source = {'schema': 'encoded-native-parallel-prefix-source/1',
        'source_manifest_sha256': _digest(manifest_raw),
        'whole_source_suffix_execution_claimed': False,
        'complete_bound_native_prefix_sha256': _digest(b''.join(native_raw)),
        'complete_bound_projection_prefix_sha256': _digest(b''.join(projection_raw)),
        'selected_native_prefix_sha256': _digest(b''.join(native_raw[:cut]) +
            (b''.join(producer_raw[2988:3006]) if include_magic else b'')),
        'selected_gate_span': [0, cut], 'selected_function_span': [0, 2 * patch_count],
        'original_functions': chosen_functions, 'original_native_gates': chosen_rows,
        'original_native_projections': selected_reports, 'roles': roles,
        'selected_gate_spans': [[0, cut]] + ([[2988, 3006]] if include_magic else []),
        'partial_functions': partial_functions, 'resource_clifford_prefix_included': include_magic,
        'rewritten_dependency_policy': 'Keep original CSS sequence and canonical phase barriers; remove exported cross-patch serial edges; parallelize initial RESETs',
        'gate_counts': dict(Counter(g.gate_type for g in rewritten)),
        'native_gate_ids_preserved': True, 'classical_adaptive_injection_included': False,
        'input': 'all selected physical carriers initially zero',
        'ideal_expected_output': 'each patch logical zero in complete +1 stabilizer sector; all8 auxiliaries zero'}
    return NativeParallelPrefix(PhysicalCircuit(tuple(rewritten)), patches[:patch_count],
        tuple(selected_bindings),
        source, tuple(phases))


def _rect(x0, y0, x1, y1):
    return Rectangle(Position2D(x0, y0), Position2D(x1, y1))


@dataclass(frozen=True)
class ParallelPrefixPlatform(Platform):
    additional_aods: tuple[AODRuntimeState, ...] = ()


def build_parallel_prefix_platform(prefix):
    """One compute permission, actual MZ, finite 6 um CZ and 5 um SLM sites.

    The occupied subset uses 10 um separation. Geometry is an explicitly
    declared research model, not a device calibration or implicit movement.
    Including the authenticated pre-T resource prefix adds the same actual
    carriers and a separate right-side device, both on the global state.
    """
    if not isinstance(prefix, NativeParallelPrefix):
        raise TypeError('NativeParallelPrefix required')
    columns = {1: 1, 2: 2, 4: 2, 12: 3}[len(prefix.patches)]
    rows = (len(prefix.patches) + columns - 1) // columns
    local = {f'd{i}': (10 * (i % 3), 10 * (i // 3)) for i in range(9)}
    local.update({f'{kind}{i}': (40 + 10 * offset, 10 * i)
        for offset, kind in enumerate(('X', 'Z')) for i in range(4)})
    x_max, y_max = 80 * (columns - 1) + 75, 60 * (rows - 1) + 55
    include_magic = prefix.source.get('resource_clifford_prefix_included', False)
    magic_x = x_max + 45
    world_x_max = magic_x + 75 if include_magic else x_max
    # The World still defines every 5 um candidate lattice point. This bounded
    # return-to-source compiler instantiates only its actual occupied holders;
    # every omitted unused support would otherwise remain disabled forever.
    # MZ visits are stationary AOD readouts and do not invent SLM offload sites.
    traps = {}
    binding = dict(prefix.bindings)
    placement, atom_roles = {}, {}
    all_patches = (*prefix.patches, 'resource') if include_magic else prefix.patches
    for block, patch in enumerate(all_patches):
        bx, by = (magic_x, 0) if patch == 'resource' else (80 * (block % columns), 60 * (block // columns))
        for role in patch_roles(patch):
            x, y = local[role.id.removeprefix(patch + '.')]
            key = f'SLM_{bx + x}_{by + y}'
            traps[key] = StaticTrap(key, GridCoord((bx + x) // 5, (by + y) // 5),
                Position2D(bx + x, by + y), True)
            q = binding[role.id]
            placement[q] = key
            atom_roles[q] = {'patch': patch, 'role': role.id, 'kind': role.kind,
                'aod_id': 'AOD_MAGIC' if patch == 'resource' else 'AOD_0'}
    envelope = _rect(-15, -330, x_max + 10, y_max + 10)
    world = WorldState(_rect(-20, -335, world_x_max + 15, y_max + 15), traps, (
        Zone('COMPUTE', ZoneType.ENTANGLEMENT, _rect(-10, -15, world_x_max + 5, y_max + 5)),
        Zone('MZ', ZoneType.MEASUREMENT, _rect(-10, -320, world_x_max + 5, -40))), 5)
    magic = (AODRuntimeState(rows=4, columns=6, spacing_um=10, pose=Position2D(magic_x - 5, -5),
        aod_id='AOD_MAGIC', envelope=_rect(magic_x - 20, -330, magic_x + 70, y_max + 10)),) if include_magic else ()
    algorithm_aod = AODRuntimeState(rows=rows, columns=columns, spacing_um=5,
            pose=Position2D(-5, -5), column_offsets_um=tuple(80 * c for c in range(columns)),
            row_offsets_um=tuple(60 * r for r in range(rows)), envelope=envelope)
    platform = ParallelPrefixPlatform(world, HardwareConfig(ez_neighbor_guard_enabled=False,
        interaction_distance_um=6., interaction_offset=Position2D(-3, -3)), algorithm_aod,
        aods={'AOD_0': algorithm_aod, **{aod.aod_id: aod for aod in magic}} if include_magic else None,
        additional_aods=magic)
    metadata = {'atom_roles': atom_roles, 'patches': [
        {'id': patch, 'label': patch, 'bounds': _rect(80 * (block % columns) - 5,
            60 * (block // columns) - 5, 80 * (block % columns) + 55,
            60 * (block // columns) + 35)} for block, patch in enumerate(prefix.patches)],
        'zone_labels': {'COMPUTE': '统一工作区', 'MZ': '实际测量与复位区'},
        'aod_labels': {'AOD_0': '算法 AOD'}}
    if include_magic:
        metadata['patches'].append({'id': 'resource', 'label': 'resource · 首 T 前停止',
            'bounds': _rect(magic_x - 5, -5, magic_x + 55, 35)})
        metadata['aod_labels']['AOD_MAGIC'] = '魔态资源独立 AOD（仅首 T 前 Clifford 前缀）'
    return platform, placement, metadata


def create_parallel_prefix_environment(prefix, *, seed=0):
    platform, placement, metadata = build_parallel_prefix_platform(prefix)
    state = initialize(prefix.circuit, platform, placement, seed=seed)
    state = replace(state, quantum_state=StabilizerState.zero(tuple(sorted(state.atoms))),
        aods={'AOD_0': platform.aod, **{aod.aod_id: aod for aod in platform.additional_aods}})
    return NeutralAtomEnv(state), platform, placement, metadata

"""Immutable interleaved patch platform, keeping the authenticated circuit."""
from dataclasses import replace
import hashlib
import json
from math import hypot
from pathlib import Path

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.models import GridCoord, Position2D, StaticTrap, Zone, ZoneType
from neutral_atom_env.platform import initialize
from neutral_atom_env.quantum.stabilizer import StabilizerState
from neutral_atom_env.world import AODRuntimeState, WorldState

from .canonical import canonical_memory_program
from .parallel_prefix import ParallelPrefixPlatform, _rect, build_parallel_prefix_platform


def build_interleaved_platform(prefix):
    """10 um coordinate grid; all homes >=10 um, CZ partners 3 um apart.

    The canonical integer geometry has data on odd/odd sites and checks on
    even/even sites. A 3x3 local AOD footprint is copied across independent
    blocks (108 cells for twelve blocks). Cartesian closure still limits which
    subsets of a canonical layer can actually be captured together.
    """
    old, old_placement, metadata = build_parallel_prefix_platform(prefix)
    columns = {1: 1, 2: 2, 4: 2, 12: 3}[len(prefix.patches)]
    rows = (len(prefix.patches) + columns - 1) // columns
    # Even disabled spare axes must fit while the origin follows a boundary
    # role at coordinate 60. Reserve its full 40 um local footprint up front.
    x_max, y_max = 80*(columns-1)+125, 80*(rows-1)+125
    magic_x = x_max+45
    has_magic = bool(old.additional_aods)
    world_x_max = magic_x+75 if has_magic else x_max
    traps, placement = {}, {}
    binding = dict(prefix.bindings)
    patches = []
    coords = dict(canonical_memory_program(patch='local', rounds=1).role_coordinates)
    for block, patch in enumerate(prefix.patches):
        bx, by = 80*(block % columns), 80*(block // columns)
        for role, (x, y) in coords.items():
            x, y = bx+10*x, by+10*y
            key = f'SLM_{x}_{y}'
            traps[key] = StaticTrap(key, GridCoord(x//5, y//5), Position2D(x, y), True)
            placement[binding[patch+'.'+role.split('.')[-1]]] = key
        patches.append({'id': patch, 'label': patch,
                        'bounds': _rect(bx-5, by-5, bx+65, by+65)})
    if has_magic:
        old_magic_x = 80*(columns-1)+75+45
        magic_dx = magic_x-old_magic_x
        for q, item in metadata['atom_roles'].items():
            if item['patch'] == 'resource':
                previous = old.world.traps[old_placement[q]]
                x, y = previous.position.x_um+magic_dx, previous.position.y_um
                key = f'SLM_{int(x)}_{int(y)}'
                traps[key] = StaticTrap(key, GridCoord(int(x)//5, int(y)//5), Position2D(x, y), True)
                placement[q] = key
        patches.append({'id': 'resource', 'label': 'resource · 首 T 前停止',
                        'bounds': _rect(magic_x-5, -5, magic_x+55, 35)})
    world = WorldState(_rect(-20, -435, world_x_max+15, y_max+15), traps, (
        Zone('COMPUTE', ZoneType.ENTANGLEMENT, _rect(-10, -15, world_x_max+5, y_max+5)),
        Zone('MZ', ZoneType.MEASUREMENT, _rect(-10, -420, world_x_max+5, -40))), 5)
    aod = AODRuntimeState(rows=3*rows, columns=3*columns, spacing_um=20,
        pose=Position2D(-5, -5),
        column_offsets_um=tuple(80*c+20*i for c in range(columns) for i in range(3)),
        row_offsets_um=tuple(80*r+20*i for r in range(rows) for i in range(3)),
        envelope=_rect(-15, -430, x_max+10, y_max+10))
    magic = tuple(replace(a, pose=Position2D(a.pose.x_um+magic_dx, a.pose.y_um),
                         envelope=_rect(magic_x-20, -430, magic_x+70, y_max+10))
                  for a in old.additional_aods)
    hardware = replace(old.hardware, interaction_offset=Position2D(-3, 0))
    platform = ParallelPrefixPlatform(world, hardware, aod,
        aods={'AOD_0': aod, **{a.aod_id: a for a in magic}} if magic else None,
        additional_aods=magic)
    metadata = {**metadata, 'patches': patches, 'layout_contract': {
        'id': 'canonical-interleaved-10um-grid-v1', 'grid_step_um': 10,
        'minimum_home_spacing_um': 10, 'minimum_nonpair_cz_spacing_um': 10,
        'cz_pair_offset_um': [-3, 0], 'mz_translation_um': -400,
        'local_aod_shape': [3, 3], 'aod_capacity': aod.rows*aod.columns,
        'protocol_reordered': False}}
    return platform, placement, metadata


def create_interleaved_environment(prefix, *, seed=0):
    platform, placement, metadata = build_interleaved_platform(prefix)
    state = initialize(prefix.circuit, platform, placement, seed=seed)
    state = replace(state, quantum_state=StabilizerState.zero(tuple(sorted(state.atoms))),
        aods={'AOD_0': platform.aod, **{a.aod_id: a for a in platform.additional_aods}})
    return NeutralAtomEnv(state), platform, placement, metadata


def create_enola_environment(prefix, proposal, *, seed=0):
    """Use a frozen author's SA proposal as homes, never as physical evidence."""
    raw = Path(proposal).read_bytes()
    value = json.loads(raw)
    if value.get('schema') != 'enola-single-patch-placement-proposal/1':
        raise ValueError('A frozen Enola patch proposal is required')
    if value['source']['placer_sha256'] != 'd256c84490bd72d525515f24acb081d7b21bcd5f7bbc31302a3bbf79a16997cf':
        raise ValueError('Proposal does not declare the fixed official placer')
    commit = '2944dbf4e163e8d2eeeec607add0d9139edce689'
    if value['source'].get('expected_commit') != commit or value['source'].get('native_source_modified') is not False:
        raise ValueError('Proposal source version or modification declaration differs')
    def digest(obj):
        return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'),
            ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()
    roles = value['role_order']
    if not roles or not isinstance(roles[0], str):
        raise ValueError('Proposal role order must be canonical')
    source_patch = roles[0].rsplit('.', 1)[0]
    memory = canonical_memory_program(patch=source_patch, rounds=1)
    expected_roles = [r.id for r in memory.program.roles]
    index = {r: i for i, r in enumerate(expected_roles)}
    expected_layers = [[[index[c.ancilla_role], index[c.data_role]] for c in memory.couplings
                        if c.layer_index == layer] for layer in range(1, 5)]
    if (roles != expected_roles or value['layers'] != expected_layers or
            value['protocol']['template_sha256'] != digest(memory.to_dict()) or
            value['protocol']['source'] != memory.to_dict()['source'] or
            value['protocol']['protocol_reordered'] is not False or value['protocol']['gate_count'] != 24):
        raise ValueError('Proposal canonical protocol provenance differs')
    if (value['site_rectangle'] != [5, 5] or value['home_spacing_um'] != 10 or
            value['slm_grid_spacing_um'] != 5 or type(value['seed']) is not int or
            value['seed'] < 0 or value['l2'] is not False):
        raise ValueError('Unsupported proposal grid, seed or SA distance model')
    expected_input = {'roles': roles, 'layers': expected_layers,
        'template_sha256': value['protocol']['template_sha256'], 'width': 5, 'height': 5,
        'seed': value['seed'], 'home_spacing_um': 10.0,
        'placer_sha256': value['source']['placer_sha256']}
    if digest(expected_input) != value['input_sha256']:
        raise ValueError('Proposal input hash differs')
    names = [r.id.split('.')[-1] for r in canonical_memory_program(patch='local', rounds=1).program.roles]
    coords = value['coordinates_um']
    local = {role.split('.')[-1]: tuple(point) for role, point in coords.items()}
    canonical_bytes = json.dumps(coords, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    if (set(coords) != set(expected_roles) or
            hashlib.sha256(canonical_bytes).hexdigest() != value['placement_sha256'] or
            len(local) != 17 or set(local) != set(names)):
        raise ValueError('Proposal placement hash or canonical role set differs')
    for p in local.values():
        if len(p) != 2 or any(type(v) not in (int, float) or not 0 <= v <= 40 or v % 10 for v in p):
            raise ValueError('This bounded proposal adapter requires a 5x5 / 10 um home grid')
    if (set(value['site_coordinates']) != set(expected_roles) or
            set(value['slm_grid_coordinates']) != set(expected_roles) or
            any(coords[r] != [10.0*v for v in value['site_coordinates'][r]] or
                value['slm_grid_coordinates'][r] != [2*v for v in value['site_coordinates'][r]]
                for r in expected_roles)):
        raise ValueError('Proposal site / world / SLM coordinates disagree')
    points = list(local.values())
    if min(hypot(a[0]-b[0], a[1]-b[1]) for i, a in enumerate(points) for b in points[i+1:]) < 10:
        raise ValueError('Proposal homes overlap or violate 10 um spacing')
    platform, original_placement, metadata = build_interleaved_platform(prefix)
    columns = {1: 1, 2: 2, 4: 2, 12: 3}[len(prefix.patches)]
    binding = dict(prefix.bindings)
    placement = {q: key for q, key in original_placement.items()
                 if metadata['atom_roles'][q]['patch'] == 'resource'}
    traps = {key: platform.world.traps[key] for key in placement.values()}
    for block, patch in enumerate(prefix.patches):
        bx, by = 80*(block % columns), 80*(block // columns)
        for role, (x, y) in local.items():
            x, y = int(bx+x), int(by+y)
            key = f'SLM_{x}_{y}'
            traps[key] = StaticTrap(key, GridCoord(x//5, y//5), Position2D(x, y), True)
            placement[binding[patch+'.'+role]] = key
    platform = replace(platform, world=replace(platform.world, traps=traps))
    metadata['layout_contract'] = {**metadata['layout_contract'],
        'id': 'enola-sa-10um-proposal-v1', 'proposal_sha256': hashlib.sha256(raw).hexdigest(),
        'placement_sha256': value['placement_sha256'], 'cz_pair_offset_um': 'searched finite candidates',
        'official_placer_commit': value['source']['expected_commit']}
    state = initialize(prefix.circuit, platform, placement, seed=seed)
    state = replace(state, quantum_state=StabilizerState.zero(tuple(sorted(state.atoms))),
        aods={'AOD_0': platform.aod, **{a.aod_id: a for a in platform.additional_aods}})
    return NeutralAtomEnv(state), platform, placement, metadata


def create_collective_environment(prefix, *, layout='enola', proposal=None, seed=0):
    """Declare real disabled MZ supports before any collection operation.

    Preserve all home positions, source gates, device footprints and physical
    thresholds. For each device, translate its complete home footprint to the
    nearest grid-aligned vertical placement within the existing MZ rectangle.
    This bounded candidate family preserves rigid captures for actual return;
    it is not a claim of globally optimal arbitrary-site packing.
    """
    if layout == 'enola':
        _, platform, placement, metadata = create_enola_environment(prefix, proposal, seed=seed)
    elif layout == 'interleaved':
        _, platform, placement, metadata = create_interleaved_environment(prefix, seed=seed)
    else:
        raise ValueError('Collective MZ requires the declared interleaved or Enola home layout')
    mz = next(z for z in platform.world.zones if z.zone_type == ZoneType.MEASUREMENT)
    from math import floor
    traps = dict(platform.world.traps)
    translations, slots = {}, {}
    for aod_id in ('AOD_0', 'AOD_MAGIC'):
        atoms = tuple(q for q in placement if metadata['atom_roles'][q]['aod_id'] == aod_id)
        if not atoms:
            continue
        homes = tuple(traps[placement[q]].position for q in atoms)
        # All current homes lie above MZ; the greatest legal grid-aligned
        # translation is closest in this explicitly bounded footprint family.
        dy = 5. * floor((mz.bounds.upper.y_um - max(p.y_um for p in homes)) / 5.)
        translations[aod_id] = [0., dy]
        for q in atoms:
            home = traps[placement[q]]
            point = Position2D(home.position.x_um, home.position.y_um + dy)
            if not mz.bounds.contains(point):
                raise ValueError('Complete home footprint does not fit declared MZ')
            key = 'mz.' + home.id
            traps[key] = StaticTrap(key, GridCoord(int(point.x_um / 5), int(point.y_um / 5)), point, False)
            slots[q] = key
    # The declared global interaction band spans the full world x range.
    # Trap inventory remains a separate, finite set of actual supports.
    zones = tuple(replace(z, bounds=_rect(platform.world.bounds.lower.x_um,
        z.bounds.lower.y_um, platform.world.bounds.upper.x_um,
        z.bounds.upper.y_um)) if z.zone_type == ZoneType.ENTANGLEMENT else z
        for z in platform.world.zones)
    platform = replace(platform, world=replace(platform.world, traps=traps, zones=zones))
    contract = {'schema': 'collective-mz-platform/1', 'mz_support': 'declared_stable_slm',
        'target_traps': slots, 'translations_um': translations, 'slm_slots': len(slots),
        'selection': 'distance-first within device complete-home vertical translations on 5um grid',
        'transport_capacity': {a.aod_id: a.rows * a.columns
            for a in (platform.aod, *platform.additional_aods)},
        'service_capacity': len(slots), 'transport_waves_are_not_service_batches': True,
        'illumination_x_equals_world_x': True, 'physical_thresholds_changed': False,
        'backend': 'rigid_env_prefix_compatibility', 'full_enola_kernel_claimed': False}
    metadata = {**metadata, 'collective_mz_contract': contract,
        'layout_contract': {**metadata['layout_contract'], 'mz_service': 'collective_slm_v1'}}
    state = initialize(prefix.circuit, platform, placement, seed=seed)
    state = replace(state, quantum_state=StabilizerState.zero(tuple(sorted(state.atoms))),
        aods={'AOD_0': platform.aod, **{a.aod_id: a for a in platform.additional_aods}})
    return NeutralAtomEnv(state), platform, placement, metadata

"""Pure-motion device modules coordinated on the independent kernel clock.

Each device retains its own END chain. Shared resources add only the necessary
ordering edges; finishing another device is never an implicit return barrier.
This v1 requires separated fixed envelopes and the kernel's occupied-axis union
mask contract. An independent geometry guard is mandatory at block binding.
Gate/measurement/reset operations are outside this qualification.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from hashlib import sha256
import json
from math import hypot, isfinite, sqrt, ulp
from collections.abc import Callable, Mapping

from neutral_atom_kernel.model import Block, Operation, freeze, thaw
from neutral_atom_strategies.native_kernel.lowering import finalize_operations


ACTIVE_AXES_CONTRACT = 'occupied-row-column-union/full-cartesian/v1'
_KINDS = frozenset(('CONFIGURE', 'LOAD', 'MOVE', 'STORE', 'WAIT'))
_TIMING = {'load_duration_us': 15., 'store_duration_us': 15.,
           'move_scale_us': 200., 'move_reference_um': 110.}


class AODModuleError(ValueError):
    def __init__(self, code, message, *, operation_id=None):
        self.code, self.operation_id = code, operation_id
        super().__init__(f'{code}: {message}')


def _require(condition, code, message, operation=None):
    if not condition:
        raise AODModuleError(code, message, operation_id=operation.id if operation else None)


def _digest(value):
    return sha256(json.dumps(thaw(freeze(value)), sort_keys=True, separators=(',', ':'),
                             allow_nan=False).encode()).hexdigest()


def review_input_sha256(initial_positions, operations, profile, *, initial_axes, initial_holders=None):
    """Canonical receipt identity of the exact inputs sent to the reviewer.

    All Operation fields, including full RF metadata, resources, dependencies
    and explicit endpoints, are bound. This identifies an input; qualification
    still comes from the separately supplied independent geometry reviewer.
    """
    holders = {q: 'slm' for q in initial_positions}
    holders.update(initial_holders or {})
    return _digest({'initial_positions': initial_positions, 'initial_holders': holders,
        'initial_axes': initial_axes, 'profile': profile,
        'operations': [{item.name: getattr(operation, item.name) for item in fields(Operation)}
                       for operation in operations]})


def _rectangle(value):
    values = tuple(float(v) for v in value)
    _require(len(values) == 4 and all(isfinite(v) for v in values) and
             values[0] < values[2] and values[1] < values[3], 'PROFILE_BOUNDS', 'Require xmin,ymin,xmax,ymax')
    return values


def _inside(point, bounds):
    return bounds[0] <= point[0] <= bounds[2] and bounds[1] <= point[1] <= bounds[3]


def _axes(value):
    rows, columns = value.get('rows', value.get('y_um', ())), value.get('columns', value.get('x_um', ()))
    _require(all(type(v) in (int, float) and isfinite(v) for v in (*rows, *columns)),
             'RF_GEOMETRY', 'RF vectors require finite numeric coordinates, not masks')
    return {'rows': tuple(float(v) for v in rows), 'columns': tuple(float(v) for v in columns)}


def _points(value):
    result = {}
    for atom, point in value.items():
        p = tuple(float(v) for v in point)
        _require(isinstance(atom, str) and bool(atom) and len(p) == 2 and all(isfinite(v) for v in p),
                 'ATOM_IDENTITY', 'Initial positions require unique IDs and finite x/y')
        result[atom] = p
    return result


def _profile(value, initial_axes):
    profile = thaw(freeze(value))
    _require(isinstance(profile.get('profile_id'), str) and bool(profile['profile_id']),
             'PROFILE_IDENTITY', 'An explicit profile_id is required')
    _require(profile.get('active_axes_contract') == ACTIVE_AXES_CONTRACT,
             'UNSUPPORTED_RF_MASK', 'Declare occupied row/column union and every Cartesian intersection')
    _require(not profile.get('extra_active_empty_axes', False), 'UNSUPPORTED_RF_MASK',
             'Extra active empty RF axes require a separately qualified kernel capability')
    bounds = _rectangle(profile['bounds_um'])
    devices = profile.get('devices', {})
    _require(bool(devices) and set(initial_axes) == set(devices), 'PROFILE_AXES',
             'Initial full RF vectors must cover exactly the declared devices')
    for key, fixed in _TIMING.items():
        _require(profile.get(key) == fixed, 'PROFILE_TIMING', f'Pure-motion v1 requires {key}={fixed}')
    for key, qualified in (('slm_grid_um', 5.), ('aod_axis_spacing_um', 2.), ('transport_clearance_um', 1.)):
        actual = profile.get(key)
        _require(type(actual) in (int, float) and isfinite(actual) and actual == qualified,
                 'PROFILE_THRESHOLD', f'Pure-motion v1 qualifies exactly {key}={qualified}')
    _require(tuple(profile.get('slm_origin_um', (0., 0.))) == (0., 0.),
             'PROFILE_SLM', 'Pure-motion v1 requires an explicitly compatible origin-zero 5um lattice')
    sites = tuple(tuple(float(v) for v in point) for point in profile.get('declared_slm_sites_um', ()))
    _require(bool(sites) and len(set(sites)) == len(sites), 'PROFILE_SLM', 'Declare the exact finite SLM site inventory')
    _require(all(len(p) == 2 and all(isfinite(v) for v in p) and _inside(p, bounds) and
                 all(v / 5 == round(v / 5) for v in p) for p in sites),
             'PROFILE_SLM', 'Every declared SLM point must lie on the world 5um lattice')
    for name, descriptor in devices.items():
        _require(isinstance(name, str) and bool(name) and name != 'slm', 'DEVICE_IDENTITY', 'Require stable AOD IDs')
        rows, columns, capacity = (descriptor.get(k) for k in ('rows', 'columns', 'capacity'))
        _require(all(type(v) is int and 0 < v <= 128 for v in (rows, columns, capacity)) and
                 rows * columns <= capacity, 'PROFILE_CAPACITY', 'Declare complete RF row/column capacity')
        envelope = _rectangle(descriptor['envelope_um'])
        _require(_inside(envelope[:2], bounds) and _inside(envelope[2:], bounds),
                 'PROFILE_ENVELOPE', 'Device envelope must be inside the declared world')
        _check_axes(_axes(initial_axes[name]), descriptor, profile)
    names = tuple(devices)
    for index, left in enumerate(names):
        a = _rectangle(devices[left]['envelope_um'])
        for right in names[index + 1:]:
            b = _rectangle(devices[right]['envelope_um'])
            dx, dy = max(0., a[0] - b[2], b[0] - a[2]), max(0., a[1] - b[3], b[1] - a[3])
            _require(hypot(dx, dy) >= profile['transport_clearance_um'], 'OVERLAP_GUARD_REQUIRED',
                     'Intersecting or insufficiently separated device envelopes need another qualified overlap guard')
    return profile


def _check_axes(axes, descriptor, profile):
    envelope = _rectangle(descriptor['envelope_um'])
    gap = profile['aod_axis_spacing_um']
    _require(len(axes['rows']) == descriptor['rows'] and len(axes['columns']) == descriptor['columns'],
             'RF_CAPACITY', 'Do not trim or change active/disabled RF axis identity')
    for key, lower, upper in (('rows', envelope[1], envelope[3]), ('columns', envelope[0], envelope[2])):
        values = axes[key]
        _require(all(isfinite(v) and lower <= v <= upper for v in values) and
                 all(b - a >= gap for a, b in zip(values, values[1:])),
                 'RF_GEOMETRY', 'Every active and disabled ordered RF line must fit its envelope and spacing')


def _motion_duration(source, target, profile):
    displacement = max((abs(a - b) for key in ('rows', 'columns')
                        for a, b in zip(source[key], target[key])), default=0.)
    return profile['move_scale_us'] * sqrt(displacement / profile['move_reference_um'])


def _check_duration(operation, expected):
    _require(abs(operation.duration_us - expected) <= 4 * (ulp(expected) + ulp(operation.duration_us)),
             'RF_TIMING', 'Motion time must cover every RF line, including disabled spares', operation)


def _segment_distance(point, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    square = dx * dx + dy * dy
    fraction = min(1., max(0., ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / square)) if square else 0.
    return hypot(point[0] - start[0] - fraction * dx, point[1] - start[1] - fraction * dy)


def _transport_only(operation):
    _require(operation.kind in _KINDS and not operation.gate_ids and not operation.report_ids,
             'PURE_MOTION_SCOPE', 'Gate, CZ, MEASURE and RESET need separate qualified laser/region validators', operation)
    _require(operation.start_us is None and operation.end_us is None, 'ALREADY_SCHEDULED',
             'Modules accept untimed primitives; coordinate after full RF timing', operation)


def _local_resources(module, initial_positions, initial_holders, initial_axes, profile):
    """Validate local carrier/RF truth and derive resources before each primitive."""
    points, holders = dict(initial_positions), dict(initial_holders)
    device = module.aod_id
    axes = _axes(initial_axes[device])
    descriptor, sites = profile['devices'][device], set(map(tuple, profile['declared_slm_sites_um']))
    resources = {}
    for operation in module.operations:
        _transport_only(operation)
        _require(operation.aod_id == device, 'DEVICE_IDENTITY', 'A module cannot issue transport on another device', operation)
        _require(set(operation.atoms) <= set(points), 'ATOM_IDENTITY', 'Operation names an unknown atom', operation)
        loaded = {q for q in points if holders[q] == device}
        demand = set(operation.resources) | {device} | {'ATOM:' + q for q in operation.atoms}
        if operation.kind != 'WAIT':
            demand.update('ATOM:' + q for q in loaded)
        resources[operation.id] = tuple(sorted(demand))
        metadata = operation.metadata
        if operation.kind == 'WAIT':
            _require(not operation.positions, 'WAIT_POSITION', 'WAIT cannot move a carrier', operation)
            continue
        _require('source_axes' in metadata and 'target_axes' in metadata,
                 'FULL_RF_REQUIRED', 'Every transport primitive needs complete source/target RF vectors', operation)
        source, target = _axes(metadata['source_axes']), _axes(metadata['target_axes'])
        _require(source == axes, 'RF_SOURCE', 'Source axes must equal the previous committed full RF endpoint', operation)
        _check_axes(target, descriptor, profile)
        if operation.kind in ('CONFIGURE', 'MOVE'):
            _require(operation.motion_profile == 'row_column', 'MOTION_PROFILE', 'This v1 uses common cubic row/column motion', operation)
            _check_duration(operation, _motion_duration(source, target, profile))
        else:
            _require(source == target, 'RF_TRANSFER', 'LOAD/STORE do not implicitly reposition RF lines', operation)
            _check_duration(operation, profile['load_duration_us' if operation.kind == 'LOAD' else 'store_duration_us'])
        if operation.kind == 'CONFIGURE':
            _require(not loaded and not operation.atoms and not operation.positions, 'CONFIGURE_LOADED', 'Empty RF configuration cannot carry atoms', operation)
        elif operation.kind == 'LOAD':
            _require(bool(operation.atoms) and all(holders[q] == 'slm' and points[q] in sites for q in operation.atoms),
                     'LOAD_SOURCE', 'LOAD requires each actual declared SLM source', operation)
            _require(all(points[q][0] in axes['columns'] and points[q][1] in axes['rows'] for q in operation.atoms),
                     'RF_SUPPORT', 'LOAD cannot change row/column identity', operation)
            active = loaded | set(operation.atoms)
            xs, ys = {points[q][0] for q in active}, {points[q][1] for q in active}
            captured = set()
            for q, point in points.items():
                if holders[q] != 'slm':
                    continue
                distance = hypot(min(abs(point[0] - x) for x in xs), min(abs(point[1] - y) for y in ys))
                if distance == 0:
                    captured.add(q)
                else:
                    _require(distance >= profile['transport_clearance_um'], 'CARTESIAN_CAPTURE', 'An enabled empty intersection affects an unrequested nearby atom', operation)
            _require(captured == set(operation.atoms), 'CARTESIAN_CAPTURE', 'LOAD must account for the entire active Cartesian capture closure', operation)
            holders.update({q: device for q in operation.atoms})
        elif operation.kind == 'MOVE':
            destinations = dict(operation.positions)
            _require(bool(operation.atoms) and set(destinations) == set(operation.atoms) and set(operation.atoms) <= loaded,
                     'MOVE_SOURCE', 'MOVE requires explicitly bound positions of supported atoms', operation)
            for q in loaded:
                point = points[q]
                _require(point[0] in source['columns'] and point[1] in source['rows'], 'RF_SUPPORT', 'Carried atom lacks its source RF axes', operation)
                row, column = source['rows'].index(point[1]), source['columns'].index(point[0])
                expected = (target['columns'][column], target['rows'][row])
                _require(destinations.get(q, point) == expected, 'RF_IDENTITY', 'Shared RF axes cannot split, renumber or move an undeclared atom', operation)
            rows = {source['rows'].index(points[q][1]) for q in loaded}
            columns = {source['columns'].index(points[q][0]) for q in loaded}
            # Common cubic progress traces the complete straight segment image
            # for every active Cartesian intersection, including empty cells.
            for row in rows:
                for column in columns:
                    a, b = (source['columns'][column], source['rows'][row]), (target['columns'][column], target['rows'][row])
                    for q, point in points.items():
                        if q not in loaded:
                            _require(_segment_distance(point, a, b) >= profile['transport_clearance_um'],
                                     'CARTESIAN_SWEEP', 'An active Cartesian trap sweeps a static or foreign carrier', operation)
            points.update(destinations)
        elif operation.kind == 'STORE':
            _require(bool(operation.atoms) and set(operation.atoms) <= loaded and all(points[q] in sites for q in operation.atoms),
                     'STORE_TARGET', 'STORE requires loaded atoms at actual declared SLM targets', operation)
            holders.update({q: 'slm' for q in operation.atoms})
        if operation.kind in ('LOAD', 'STORE'):
            _require(all(points[q] == tuple(point) for q, point in operation.positions), 'TRANSFER_POSITION', 'Transfers cannot implicitly move atoms', operation)
        axes = target
        active = {q for q in points if holders[q] == device}
        expected_rows, expected_columns = tuple(sorted({points[q][1] for q in active})), tuple(sorted({points[q][0] for q in active}))
        _require(tuple(metadata.get('active_rows', expected_rows)) == expected_rows and
                 tuple(metadata.get('active_columns', expected_columns)) == expected_columns,
                 'UNSUPPORTED_RF_MASK', 'Masks must preserve occupied-axis union and its full Cartesian product', operation)
    _require(not any(h == device for h in holders.values()), 'MODULE_TERMINAL', 'A complete transport module must finish with its carriers stored')
    return resources


@dataclass(frozen=True, slots=True)
class AODTransportModule:
    aod_id: str
    operations: tuple[Operation, ...]
    release_us: float = 0.
    profile_id: str = ''
    source_contract: Mapping = field(default_factory=dict)

    def __post_init__(self):
        _require(isinstance(self.aod_id, str) and bool(self.aod_id) and self.aod_id != 'slm', 'DEVICE_IDENTITY', 'Require a stable AOD identity')
        _require(bool(self.operations) and all(isinstance(op, Operation) for op in self.operations), 'MODULE_OPERATIONS', 'A module needs immutable kernel primitives')
        _require(isfinite(self.release_us) and self.release_us >= 0, 'MODULE_RELEASE', 'release_us must be nonnegative and finite')
        for op in self.operations:
            _transport_only(op)
        object.__setattr__(self, 'operations', tuple(self.operations))
        object.__setattr__(self, 'source_contract', freeze(self.source_contract))

    @classmethod
    def compile(cls, aod_id, operations, initial_positions, *, initial_axes, profile, initial_holders=None, release_us=0.):
        """Finalize one device's complete RF chain without scheduling peers."""
        positions = _points(initial_positions)
        normalized = _profile(profile, initial_axes)
        _require(aod_id in normalized['devices'], 'DEVICE_IDENTITY', 'Unknown device in module profile')
        holders = {q: 'slm' for q in positions}
        holders.update(initial_holders or {})
        _require(set(holders) == set(positions), 'ATOM_IDENTITY', 'Holder mapping contains unknown atoms')
        operations = tuple(operations)
        for op in operations:
            _transport_only(op)
            _require(op.aod_id == aod_id, 'DEVICE_IDENTITY', 'Module primitives must select their actual device', op)
            _require(set(op.atoms) <= set(positions), 'ATOM_IDENTITY', 'Operation names an unknown atom', op)
        finalized = finalize_operations(operations, positions, initial_axes={aod_id: initial_axes[aod_id]},
            initial_holders=holders, bounds=normalized['devices'][aod_id]['envelope_um'],
            minimum_axis_spacing_um=normalized['aod_axis_spacing_um'])
        contract = {'profile_id': normalized['profile_id'], 'active_axes_contract': ACTIVE_AXES_CONTRACT,
            'initial_positions': positions, 'initial_holders': holders,
            'initial_axes': {name: _axes(value) for name, value in initial_axes.items()}, 'profile': normalized}
        module = cls(aod_id, finalized, float(release_us), normalized['profile_id'], contract)
        _local_resources(module, positions, holders, initial_axes, normalized)
        return module


@dataclass(frozen=True, slots=True)
class ModuleSchedule:
    operations: tuple[Operation, ...]
    device_completion_us: Mapping
    makespan_us: float
    initial_positions: Mapping
    initial_holders: Mapping
    initial_axes: Mapping
    profile: Mapping

    def __post_init__(self):
        for key in ('device_completion_us', 'initial_positions', 'initial_holders', 'initial_axes', 'profile'):
            object.__setattr__(self, key, freeze(getattr(self, key)))

    def bind_block(self, kernel, id, *, geometry_guard: Callable) -> Block:
        """Run the independent full review, then bind the unchanged live origin."""
        _require(callable(geometry_guard), 'GEOMETRY_GUARD_REQUIRED', 'A separate full geometry reviewer is required before execution')
        _require(all(op.kind in _KINDS and not op.gate_ids and not op.report_ids for op in self.operations),
                 'PURE_MOTION_SCOPE', 'This transport qualification cannot approve laser or report effects')
        observation = kernel.observe()
        _require(not observation.inflight_operations and observation.pending_events == 0,
                 'MODULE_ORIGIN', 'Bind modules only at an idle committed boundary')
        _require(dict(observation.committed_positions) == dict(self.initial_positions) and
                 dict(observation.holders) == dict(self.initial_holders) and
                 {name: _axes(value) for name, value in observation.aod_axes.items()} ==
                 {name: _axes(value) for name, value in self.initial_axes.items()},
                 'MODULE_ORIGIN', 'Live carrier and full RF state differs from the compiled source contract')
        input_sha256 = review_input_sha256(self.initial_positions, self.operations, self.profile,
            initial_axes=self.initial_axes, initial_holders=self.initial_holders)
        reviewed = geometry_guard(thaw(self.initial_positions), self.operations, thaw(self.profile),
            initial_axes=thaw(self.initial_axes), initial_holders=thaw(self.initial_holders))
        _require(isinstance(reviewed, Mapping) and reviewed.get('status') == 'PASS',
                 'GEOMETRY_REVIEW_FAILED', 'Independent full geometry review did not pass')
        _require(reviewed.get('input_sha256') == input_sha256, 'GEOMETRY_RECEIPT_IDENTITY',
                 'Independent geometry receipt must bind every exact initial/profile/operation input')
        return kernel.bind_block(id, self.operations, execution_mode='scheduled', native_provenance={
            'strategy': 'independent-aod-modules/pure-motion-v1', 'profile_id': self.profile['profile_id'],
            'source_contract_sha256': _digest({'positions': self.initial_positions, 'holders': self.initial_holders,
                'axes': self.initial_axes, 'profile': self.profile}),
            'active_axes_contract': ACTIVE_AXES_CONTRACT, 'gate_or_service_qualification': False,
            'geometry_review_input_sha256': input_sha256,
            'geometry_review': reviewed})


def coordinate_aod_modules(modules, initial_positions, *, initial_axes, profile, initial_holders=None, shared_operations=()):
    """Schedule local END chains and explicit dependencies/resources, not returns.

    Shared operations in this pure-motion qualification are WAIT/controller
    resource reservations only. Physical effects need a future laser validator.
    Intersecting device envelopes fail closed instead of assuming independence.
    """
    modules, shared_operations = tuple(modules), tuple(shared_operations)
    positions = _points(initial_positions)
    normalized = _profile(profile, initial_axes)
    holders = {q: 'slm' for q in positions}
    holders.update(initial_holders or {})
    _require(set(holders) == set(positions) and all(h == 'slm' or h in normalized['devices'] for h in holders.values()),
             'ATOM_IDENTITY', 'Holder mapping must preserve all declared atoms and devices')
    _require(bool(modules) and all(isinstance(m, AODTransportModule) for m in modules) and
             len({m.aod_id for m in modules}) == len(modules), 'DEVICE_MODULE', 'Declare one complete module per selected device')
    axes = {name: _axes(value) for name, value in initial_axes.items()}
    for name, value in initial_axes.items():
        carried = {q for q, holder in holders.items() if holder == name}
        _require(tuple(value.get('active_rows', tuple(sorted({positions[q][1] for q in carried})))) == tuple(sorted({positions[q][1] for q in carried})) and
                 tuple(value.get('active_columns', tuple(sorted({positions[q][0] for q in carried})))) == tuple(sorted({positions[q][0] for q in carried})),
                 'UNSUPPORTED_RF_MASK', 'Initial masks cannot add empty active RF lines')
    owner, entries = {}, []
    for module in modules:
        _require(module.aod_id in normalized['devices'] and module.profile_id == normalized['profile_id'],
                 'PROFILE_IDENTITY', 'Module must bind the same explicitly declared profile')
        expected = {'profile_id': normalized['profile_id'], 'active_axes_contract': ACTIVE_AXES_CONTRACT,
                    'initial_positions': positions, 'initial_holders': holders, 'initial_axes': axes, 'profile': normalized}
        _require(thaw(module.source_contract) == thaw(freeze(expected)), 'MODULE_ORIGIN', 'Every module must retain the complete original source contract')
        transported = {q for op in module.operations if op.kind in ('LOAD', 'MOVE', 'STORE') for q in op.atoms}
        for atom in transported:
            _require(atom not in owner, 'SHARED_CARRIER', 'Separate device modules cannot transport the same physical atom')
            owner[atom] = module.aod_id
        resources = _local_resources(module, positions, holders, initial_axes, normalized)
        previous = None
        for operation in module.operations:
            deps = tuple(dict.fromkeys((*operation.depends_on, *((previous,) if previous else ()))))
            entries.append((operation, deps, resources[operation.id], float(module.release_us), module.aod_id))
            previous = operation.id
    for operation in shared_operations:
        _transport_only(operation)
        _require(operation.kind == 'WAIT' and not operation.positions, 'PURE_MOTION_SCOPE', 'Shared nodes are explicit controller WAIT resources only', operation)
        _require(set(operation.atoms) <= set(positions), 'ATOM_IDENTITY', 'Shared wait names an unknown atom', operation)
        entries.append((operation, operation.depends_on, tuple(sorted(set(operation.resources) |
            {'ATOM:' + atom for atom in operation.atoms})), 0., None))
    ids = {entry[0].id for entry in entries}
    _require(len(ids) == len(entries), 'OPERATION_IDENTITY', 'Operation identities must be unique across all modules')
    _require(all(set(deps) <= ids for _, deps, _, _, _ in entries), 'DEPENDENCY_IDENTITY', 'Operation dependency has no producer in this schedule')
    pending = list(enumerate(entries))
    scheduled, ends, calendars = [], {}, {}
    device_ends = {}
    while pending:
        ready = [(max((ends[d] for d in entry[1]), default=entry[3]), ordinal, entry)
                 for ordinal, entry in pending if set(entry[1]) <= ends.keys()]
        _require(bool(ready), 'DEPENDENCY_CYCLE', 'Module/shared dependency graph contains a cycle')
        desired, ordinal, entry = min(ready, key=lambda item: (max(item[0], item[2][3]), item[1]))
        operation, dependencies, resources, release, device = entry
        start = max(desired, release)
        blockers = []
        while True:
            end = start + operation.duration_us
            conflicts = [(finish, other) for resource in resources for begin, finish, other in calendars.get(resource, ())
                         if start < finish and begin < end]
            if not conflicts:
                break
            start = max(finish for finish, _ in conflicts)
            blockers.extend(other for _, other in conflicts)
        _require(isfinite(end), 'TIME_OVERFLOW', 'Module schedule must have finite explicit endpoints', operation)
        deps = tuple(dict.fromkeys((*dependencies, *blockers)))
        metadata = thaw(operation.metadata)
        metadata.update(schedule_binding='independent-device-END-chain/resources/v1',
                        profile_id=normalized['profile_id'], active_axes_contract=ACTIVE_AXES_CONTRACT,
                        module_aod_id=device, gate_or_service_qualification=False)
        scheduled.append(replace(operation, start_us=start, end_us=end, depends_on=deps,
                                 resources=resources, metadata=metadata))
        ends[operation.id] = end
        for resource in resources:
            calendars.setdefault(resource, []).append((start, end, operation.id))
        if device is not None:
            device_ends[device] = end
        pending = [(i, item) for i, item in pending if i != ordinal]
    return ModuleSchedule(tuple(scheduled), device_ends, max(ends.values()), positions, holders, axes, normalized)


__all__ = ('ACTIVE_AXES_CONTRACT', 'AODModuleError', 'AODTransportModule', 'ModuleSchedule',
           'coordinate_aod_modules', 'review_input_sha256')

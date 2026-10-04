"""Temporal/carrier module tests; independent full geometry proof is separate.

The binding dispatch stub tests the required reviewer call, not qualification.
The artifact/demo tests use the separately owned production geometry auditor.
"""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from neutral_atom_kernel import KernelExecutor, Operation
from neutral_atom_strategies.scheduling.aod_modules import (
    ACTIVE_AXES_CONTRACT, AODModuleError, AODTransportModule, coordinate_aod_modules, review_input_sha256,
)


def fixture(*, release=0., bus=False):
    positions = {'D0': (0, 0), 'D1': (10, 0), 'D2': (0, 10),
                 'R0': (100, 0), 'R1': (110, 0), 'R2': (100, 10)}
    initial_axes = {'AOD_0': {'rows': (0, 10, 20), 'columns': (0, 10, 20)},
                    'AOD_MAGIC': {'rows': (0, 10, 20), 'columns': (100, 110, 120)}}
    profile = {'profile_id': 'independent-aod-modules-test/v1', 'bounds_um': (-10, -10, 130, 130),
        'active_axes_contract': ACTIVE_AXES_CONTRACT, 'slm_grid_um': 5.,
        'aod_axis_spacing_um': 2., 'transport_clearance_um': 1.,
        'load_duration_us': 15., 'store_duration_us': 15., 'move_scale_us': 200., 'move_reference_um': 110.,
        'devices': {'AOD_0': {'rows': 3, 'columns': 3, 'capacity': 9, 'envelope_um': (-5, -5, 25, 125)},
                    'AOD_MAGIC': {'rows': 3, 'columns': 3, 'capacity': 9, 'envelope_um': (95, -5, 125, 125)}}}
    raw = {}
    sites = set(positions.values())
    for device, prefix, shift, dwell in (('AOD_0', 'D', 100, 30), ('AOD_MAGIC', 'R', 50, 10)):
        atoms = tuple(q for q in positions if q.startswith(prefix))
        destination = tuple((q, (positions[q][0], positions[q][1] + shift)) for q in atoms)
        sites.update(p for _, p in destination)
        raw[device] = (
            Operation(device + ':load', 'LOAD', atoms, 15, aod_id=device,
                      resources=('TRANSFER_BUS',) if bus else ()),
            Operation(device + ':out', 'MOVE', atoms, positions=destination, aod_id=device),
            Operation(device + ':land', 'STORE', atoms, 15, aod_id=device),
            Operation(device + ':dwell', 'WAIT', atoms, dwell, aod_id=device),
            Operation(device + ':reload', 'LOAD', atoms, 15, aod_id=device),
            Operation(device + ':return', 'MOVE', atoms, positions=tuple((q, positions[q]) for q in atoms), aod_id=device),
            Operation(device + ':home', 'STORE', atoms, 15, aod_id=device),
        )
    profile['declared_slm_sites_um'] = sorted(sites)
    modules = tuple(AODTransportModule.compile(device, operations, positions,
        initial_axes=initial_axes, profile=profile, release_us=release if device == 'AOD_0' else 0)
        for device, operations in raw.items())
    return positions, initial_axes, profile, raw, modules


def coordinate(parts, **kwargs):
    positions, axes, profile, _, modules = parts
    return coordinate_aod_modules(modules, positions, initial_axes=axes, profile=profile, **kwargs)


def dispatch_guard(initial, operations, profile, *, initial_axes, initial_holders):
    # Unit-test dispatch only. No physical qualification artifact is emitted.
    assert set(initial) == set(initial_holders)
    assert len(initial_axes) == 2 and profile['active_axes_contract'] == ACTIVE_AXES_CONTRACT
    assert all(op.start_us is not None and op.end_us is not None for op in operations)
    return {'status': 'PASS', 'scope': 'unit-test reviewer dispatch stub',
        'input_sha256': review_input_sha256(initial, operations, profile,
            initial_axes=initial_axes, initial_holders=initial_holders)}


def bind(parts, schedule, kernel, id='modules'):
    return schedule.bind_block(kernel, id, geometry_guard=dispatch_guard)


def test_two_real_moves_overlap_and_resource_returns_while_data_keeps_moving():
    parts = fixture()
    schedule = coordinate(parts)
    by_id = {op.id: op for op in schedule.operations}
    data, resource = by_id['AOD_0:out'], by_id['AOD_MAGIC:out']
    assert data.start_us == resource.start_us == 15
    assert data.end_us > resource.end_us
    assert 'AOD_MAGIC:home' not in by_id['AOD_0:return'].depends_on
    kernel = KernelExecutor(parts[0], initial_aod_axes=parts[1])
    kernel.run(bind(parts, schedule, kernel), until_us=50)
    observation = kernel.observe()
    assert set(observation.inflight_operations) == {'AOD_0:out', 'AOD_MAGIC:out'}
    assert observation.resource_owners['AOD_0'] == 'AOD_0:out'
    assert observation.resource_owners['AOD_MAGIC'] == 'AOD_MAGIC:out'
    for atom, op, shift in (('D0', data, 100), ('R0', resource, 50)):
        u = (50 - op.start_us) / op.duration_us
        assert observation.positions[atom][1] == pytest.approx(shift * (3 * u * u - 2 * u * u * u))
        assert observation.committed_positions[atom] == parts[0][atom]
    resource_done = schedule.device_completion_us['AOD_MAGIC']
    returned = kernel.wait_until(resource_done)
    assert all(returned.holders[q] == 'slm' and returned.positions[q] == parts[0][q] for q in parts[0] if q.startswith('R'))
    assert returned.inflight_operations == ('AOD_0:return',)
    assert returned.holders['D0'] == 'AOD_0' and returned.positions['D0'] != parts[0]['D0']
    final = kernel.run()
    assert final.time_us == schedule.makespan_us == schedule.device_completion_us['AOD_0']
    assert final.positions == parts[0] and all(h == 'slm' for h in final.holders.values())
    starts = {r['operation_id']: r for r in kernel.journal if r['event'] == 'OPERATION_STARTED'}
    assert starts['AOD_0:out']['start_us'] == starts['AOD_MAGIC:out']['start_us']
    assert starts['AOD_0:return']['start_us'] < resource_done < starts['AOD_0:return']['end_us']


@pytest.mark.parametrize('cut', ('outbound', 'resource_wait', 'resource_returned'))
def test_cold_checkpoint_preserves_two_devices_waits_queue_and_full_journal(cut):
    parts, = (fixture(),)
    schedule = coordinate(parts)
    by_id = {op.id: op for op in schedule.operations}
    times = {'outbound': 50., 'resource_wait': by_id['AOD_MAGIC:dwell'].start_us + 5,
             'resource_returned': schedule.device_completion_us['AOD_MAGIC']}
    kernel = KernelExecutor(parts[0], initial_aod_axes=parts[1])
    kernel.wait_until(100.1)
    kernel.run(bind(parts, schedule, kernel), until_us=100.1 + times[cut])
    checkpoint = kernel.checkpoint_json(include_journal=True)
    restored = KernelExecutor.restore(checkpoint)
    assert restored.observe() == kernel.observe()
    assert restored.checkpoint_json(include_journal=True) == checkpoint
    kernel.run(); restored.run()
    assert restored.checkpoint_json(include_journal=True) == kernel.checkpoint_json(include_journal=True)
    assert restored.observe().positions == parts[0]


def test_shared_bus_wait_and_explicit_dispatch_dependency_do_not_make_return_barrier():
    parts = fixture(bus=True)
    schedule = coordinate(parts)
    by_id = {op.id: op for op in schedule.operations}
    assert by_id['AOD_0:load'].start_us == 0
    assert by_id['AOD_MAGIC:load'].start_us == 15
    assert 'AOD_0:load' in by_id['AOD_MAGIC:load'].depends_on
    assert by_id['AOD_0:out'].start_us == by_id['AOD_MAGIC:load'].start_us
    kernel = KernelExecutor(parts[0], initial_aod_axes=parts[1])
    kernel.run(bind(parts, schedule, kernel))
    assert kernel.observe().positions == parts[0]
    positions, axes, profile, raw, modules = fixture()
    modified = (replace(raw['AOD_0'][0], depends_on=('dispatch',)), *raw['AOD_0'][1:])
    data = AODTransportModule.compile('AOD_0', modified, positions, initial_axes=axes, profile=profile)
    dispatched = coordinate_aod_modules((data, modules[1]), positions, initial_axes=axes, profile=profile,
        shared_operations=(Operation('dispatch', 'WAIT', duration_us=25, resources=('CONTROL_BUS',)),))
    mapping = {op.id: op for op in dispatched.operations}
    assert mapping['AOD_0:load'].start_us == 25 and mapping['AOD_MAGIC:load'].start_us == 0


def test_every_full_rf_line_and_empty_cartesian_intersection_survives_compilation():
    parts = fixture()
    schedule = coordinate(parts)
    for op in schedule.operations:
        if op.kind != 'WAIT':
            for boundary in ('source_axes', 'target_axes'):
                assert len(op.metadata[boundary]['rows']) == len(op.metadata[boundary]['columns']) == 3
    kernel = KernelExecutor(parts[0], initial_aod_axes=parts[1])
    kernel.run(bind(parts, schedule, kernel), until_us=15)
    for axes in kernel.observe().aod_axes.values():
        assert len(axes['rows']) == len(axes['columns']) == 3
        assert len(axes['active_rows']) * len(axes['active_columns']) == 4  # 3 atoms + 1 empty active cell.


@pytest.mark.parametrize('kind', ('RESET', 'MEASURE', 'CZ', 'GATE'))
def test_nontransport_scope_fails_before_fake_qualification(kind):
    positions, axes, profile, _, _ = fixture()
    with pytest.raises(AODModuleError, match='PURE_MOTION_SCOPE'):
        AODTransportModule.compile('AOD_0', (Operation('effect', kind, ('D0',), 1, gate_ids=('g',)),),
            positions, initial_axes=axes, profile=profile)


@pytest.mark.parametrize('problem', ('overlap', 'extra_axis', 'capture', 'empty_sweep', 'undeclared_store', 'unknown_atom'))
def test_profile_capture_and_path_refusals_do_not_mutate_inputs(problem):
    positions, axes, profile, raw, _ = fixture()
    if problem == 'overlap':
        profile['devices']['AOD_MAGIC']['envelope_um'] = (-5, -5, 125, 125)
        expected = 'OVERLAP_GUARD_REQUIRED'
    elif problem == 'extra_axis':
        profile['extra_active_empty_axes'] = True
        expected = 'UNSUPPORTED_RF_MASK'
    elif problem in ('capture', 'empty_sweep'):
        positions['SPECTATOR'] = (10, 10) if problem == 'capture' else (10, 105)
        profile['declared_slm_sites_um'].append(positions['SPECTATOR'])
        expected = 'CARTESIAN_CAPTURE' if problem == 'capture' else 'CARTESIAN_SWEEP'
    elif problem == 'undeclared_store':
        profile['declared_slm_sites_um'].remove((0, 100))
        expected = 'STORE_TARGET'
    else:
        raw['AOD_0'] = (replace(raw['AOD_0'][0], atoms=('UNKNOWN',)), *raw['AOD_0'][1:])
        expected = 'ATOM_IDENTITY'
    before = (*deepcopy((positions, axes, profile)), dict(raw))
    with pytest.raises(AODModuleError, match=expected):
        AODTransportModule.compile('AOD_0', raw['AOD_0'], positions, initial_axes=axes, profile=profile)
    assert (positions, axes, profile, raw) == before


def test_same_atom_cross_device_and_cycle_are_rejected_without_live_commit():
    positions, axes, profile, raw, modules = fixture()
    cross = replace(modules[1], operations=(replace(modules[1].operations[0], atoms=('D0',)), *modules[1].operations[1:]))
    with pytest.raises(AODModuleError, match='SHARED_CARRIER'):
        coordinate_aod_modules((modules[0], cross), positions, initial_axes=axes, profile=profile)
    cycle = (replace(raw['AOD_0'][0], depends_on=('AOD_0:home',)), *raw['AOD_0'][1:])
    data = AODTransportModule.compile('AOD_0', cycle, positions, initial_axes=axes, profile=profile)
    with pytest.raises(AODModuleError, match='DEPENDENCY_CYCLE'):
        coordinate_aod_modules((data, modules[1]), positions, initial_axes=axes, profile=profile)


def test_geometry_guard_is_called_on_exact_ir_and_failure_or_changed_origin_is_atomic():
    parts = fixture()
    schedule = coordinate(parts)
    kernel = KernelExecutor(parts[0], initial_aod_axes=parts[1])
    before = kernel.checkpoint_json(include_journal=True)
    calls = []
    def refuse(initial, operations, profile, **kwargs):
        calls.append((initial, operations, profile, kwargs))
        return {'status': 'FAIL', 'reason': 'independent reviewer refused'}
    with pytest.raises(AODModuleError, match='GEOMETRY_REVIEW_FAILED'):
        schedule.bind_block(kernel, 'refused', geometry_guard=refuse)
    assert len(calls) == 1 and calls[0][1] == schedule.operations
    assert kernel.checkpoint_json(include_journal=True) == before
    moved = dict(parts[0], D0=(5, 0))
    stale = KernelExecutor(moved, initial_aod_axes=parts[1])
    with pytest.raises(AODModuleError, match='MODULE_ORIGIN'):
        schedule.bind_block(stale, 'stale', geometry_guard=dispatch_guard)


def test_recording_on_and_off_keep_identical_final_state_and_completion_times():
    parts = fixture(release=12.3)
    schedule = coordinate(parts)
    noisy = KernelExecutor(parts[0], initial_aod_axes=parts[1])
    quiet = KernelExecutor(parts[0], initial_aod_axes=parts[1], recording=False)
    noisy.run(bind(parts, schedule, noisy)); quiet.run(bind(parts, schedule, quiet))
    assert noisy.observe() == quiet.observe()
    recorded, unrecorded = (json.loads(executor.checkpoint_json()) for executor in (noisy, quiet))
    for payload in (recorded, unrecorded):
        del payload['recording'], payload['checkpoint_digest']
    assert recorded == unrecorded
    assert noisy.journal and not quiet.journal


@pytest.mark.parametrize('receipt', ('status_only', 'stale_operations', 'stale_profile', 'stale_origin'))
def test_receipt_must_bind_every_actual_review_input_before_execution(receipt):
    parts = fixture()
    schedule = coordinate(parts)
    kernel = KernelExecutor(parts[0], initial_aod_axes=parts[1])
    before = kernel.checkpoint_json(include_journal=True)
    def bad_receipt(initial, operations, profile, *, initial_axes, initial_holders):
        if receipt == 'status_only':
            return {'status': 'PASS'}
        if receipt == 'stale_operations':
            operations = (replace(operations[0], resources=(*operations[0].resources, 'NEW_BUS')), *operations[1:])
        elif receipt == 'stale_profile':
            profile['profile_id'] = 'another-profile'
        else:
            initial['D0'] = [5., 0.]
        return {'status': 'PASS', 'input_sha256': review_input_sha256(initial, operations, profile,
            initial_axes=initial_axes, initial_holders=initial_holders)}
    with pytest.raises(AODModuleError, match='GEOMETRY_RECEIPT_IDENTITY'):
        schedule.bind_block(kernel, 'wrong-receipt', geometry_guard=bad_receipt)
    assert kernel.checkpoint_json(include_journal=True) == before


@pytest.mark.parametrize('field,value', (('slm_origin_um', (1., 0.)),
    ('aod_axis_spacing_um', 3.), ('transport_clearance_um', 2.)))
def test_profile_lattice_and_spacing_cannot_change_the_qualified_contract(field, value):
    positions, axes, profile, raw, _ = fixture()
    profile[field] = value
    with pytest.raises(AODModuleError, match='PROFILE_SLM|PROFILE_THRESHOLD'):
        AODTransportModule.compile('AOD_0', raw['AOD_0'], positions, initial_axes=axes, profile=profile)

"""Bounded HRS prefix / four-factory intake. Fail before missing native work.

No 200 ms timer may stand in for a produced magic state. This entry never
turns on build_missing and never imports live state from previous runs.
"""
from pathlib import Path
from copy import deepcopy
import argparse
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from na_pipeline.device import canonical_surface17_device, build_preinitialized_state, validate_preinitialized_state
from na_pipeline.qec import factory_fleet_requirements
from na_pipeline.runtime import EventSession, FactoryFleet, LogicalGateLibrary, resource_inventory
from na_pipeline.runtime.compilation_guard import CompilationGuard, UnexpectedCompilation
from na_pipeline.backend.enola_kernel import StrategyError, digest
from na_pipeline.runtime.pipeline import save_artifact


def build_world(layout):
    logical = {'patches': [{'patch_id': 'q'+str(i),
               'initial_state': {'logical_basis': 'Z', 'logical_value': 0}} for i in range(17)]}
    req = factory_fleet_requirements(logical, ['F0', 'F1', 'F2', 'F3'])
    device = canonical_surface17_device()
    ref = {'artifact_id': 'shor17-single-side-layout:'+digest(layout), 'producer': 'R0', 'fixture': False}
    patches = {p: {k: r[k] for k in ('aod_group', 'basis', 'value')} for p, r in req['patches'].items()}
    placements = {p['id']: {'anchor_um': p['anchor_um'], 'orientation': 'x_vertical_z_horizontal'} for p in layout['patches']}
    inventory = resource_inventory(req, {f['id']+':join_probe': f['probe_um'] for f in layout['factories']}, placement_ref=ref)
    world = build_preinitialized_state(device, patches, placements, placement_ref=ref, resource_inventory=inventory)
    errors = validate_preinitialized_state(world, device)
    if errors:
        raise ValueError(errors)
    expected = {a['id']: a['xy_um'] for a in layout['atoms']}
    actual = {a['qubit_id']: a['position_um'] for a in world['atoms']}
    if actual != expected or len(actual) != 769:
        raise ValueError('DEMO_LAYOUT_IDENTITY_CHANGED')
    return device, req, world


def extract_prefix(circuit_path, layout):
    raw = circuit_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != layout['source_files']['circuit.json']['sha256']:
        raise ValueError('REFERENCE_CIRCUIT_CHANGED')
    source = json.loads(raw)
    ops = []
    for i, n in enumerate(source['gates'][:16]):
        gate = n['name'].upper()
        if gate == 'P':
            from math import pi
            if abs(abs(n['angle'])-pi/4) > 1e-12:
                raise ValueError('PREFIX_PHASE_NOT_T')
            gate = 'T' if n['angle'] > 0 else 'TDG'
        ops.append({'id': 'hrs-prefix:'+str(i), 'source_gate_index': i, 'operation': gate,
                    'patches': ['q'+str(q) for q in n['q']], 'original': deepcopy(n)})
    if len(ops) != 16 or [n['operation'] for n in ops if n['operation'] in ('T', 'TDG')] != ['TDG', 'T']:
        raise ValueError('PREFIX_UNEXPECTED_SOURCE')
    return {'schema_version': 'Shor17Prefix/0.1', 'operations': ops, 'original_circuit_sha256': hashlib.sha256(raw).hexdigest(),
            'source_range': [0, 16], 'initial_logical_state': 'all_17_Z_zero_before_original_prefix',
            'full_shor': False, 'quantum_state_simulated': False, 'factory_period_ms_sizing_assumption': 200,
            'factory_ready_policy': 'actual_accepted_checks_and_conversion_only_no_timer'}


def preflight(layout_path, circuit_path, source, out):
    out.mkdir(parents=True, exist_ok=True)
    layout = json.loads(layout_path.read_bytes())
    prefix = extract_prefix(circuit_path, layout)
    device, req, world = build_world(layout)
    for filename, data in [('prefix.json', prefix), ('device.json', device), ('resource-requirements.json', req),
                           ('initial-state.json.gz', world), ('layout.json', layout)]:
        save_artifact(out/filename, data, immutable=True)
    session = EventSession(device, world, run_id='shor17-prefix-four-factory-preflight-v1')
    fleet = FactoryFleet(session, req, reserve_ready=4)
    starts = fleet.start_idle()
    library = LogicalGateLibrary(device, allow_connection_planning=False)
    library.import_component('H', source/'H')
    recipe = library.import_producer_component('initialize', source/'factory.initialize')
    save_artifact(out/'producer-initialize-derivation.json', recipe)
    save_artifact(out/'frontier.json.gz', fleet.frontier())
    guard = CompilationGuard(on_violation=lambda d: save_artifact(out/'first-compilation-violation.json.gz', d, immutable=True))
    try:
        with guard:
            with guard.scope(stage='data_H_preflight', logical_source=prefix['operations'][0]):
                call = library.prepare('H', session, operands={'block': 'q0'}, invocation_id='hrs-prefix:0')
            save_artifact(out/'first-H-plan.json.gz', call['physical_plan'])
            save_artifact(out/'first-H-binding.json', call['physical_plan']['parametric_component_instance'])
            graph = fleet.lines['F0'].next_graph()
            with guard.scope(stage='producer.initialize', factory='F0', world_atoms=769):
                try:
                    library.prepare_dags('producer.initialize', session, [graph])
                except StrategyError as exc:
                    if exc.code in {'MODULE_DEPENDENCY_MISSING', 'COMPONENT_NOT_REGISTERED'}:
                        guard.missing_dependency(exc)
                    raise
        status = {'status': 'initial_frontier_bound', 'execution_ready': False}
    except (Exception, UnexpectedCompilation) as exc:
        status = {'status': 'stopped_before_submission', 'error_code': getattr(exc, 'code', type(exc).__name__),
                  'message': str(exc), 'execution_ready': False}
    finally:
        status.update(world_atoms=769, data_patches=17, factories=4, logical_operations=16,
                      production_starts=starts, submitted_windows=len(session.plans),
                      ready_magic_tokens=len(fleet.inventory()),
                      factory_production_executed=False, hardware_executed=False,
                      quantum_state_simulated=False, compiler_stats=library.stats,
                      user_visual_acceptance='pending')
        save_artifact(out/'preflight-status.json', status)
        save_artifact(out/'compilation-guard.json', guard.receipt())
        save_artifact(out/'fleet-intake-checkpoint.json.gz', fleet.checkpoint())
    print(json.dumps(status, ensure_ascii=False), flush=True)
    return 0 if status['status'] == 'initial_frontier_bound' else 2


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--layout', type=Path, required=True)
    p.add_argument('--circuit', type=Path, required=True)
    p.add_argument('--component-source', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    raise SystemExit(preflight(a.layout, a.circuit, a.component_source, a.out))

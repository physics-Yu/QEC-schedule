"""Execute only the frozen 16-gate prefix and real four-line factory protocols."""
from pathlib import Path
from copy import deepcopy
import argparse
import gzip
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'scripts')]
from shor17_factory_demo import build_world
from na_pipeline.runtime import EventSession, FactoryFleet, LogicalGateLibrary, make_scenario
from na_pipeline.runtime.frozen_frontier import FrozenFrontier
from na_pipeline.runtime.pipeline import save_artifact
from na_pipeline.backend.enola_kernel import digest
from na_pipeline.validation.dag_physical import validate_physical_plan
from na_pipeline.validation.dag_core import DAGAudit
from na_pipeline.validation.dag_session import inspect_window_binding


def read(path):
    raw = Path(path).read_bytes()
    return json.loads(gzip.decompress(raw) if str(path).endswith('.gz') else raw)


def execute(layout_path, prefix_path, source, out, max_windows=140):
    out.mkdir(parents=True, exist_ok=True)
    layout, prefix = read(layout_path), read(prefix_path)
    device, req, initial = build_world(layout)
    inputs = {'layout': digest(layout), 'prefix': digest(prefix), 'device': digest(device), 'initial': digest(initial)}
    library = LogicalGateLibrary(device, connection_directory=out/'compiled-modules',
                                 budget={'max_wall_seconds': 900, 'max_operations': 100000}, allow_connection_planning=False)
    required = ['H', 'X', 'CZ', 'factory.consume', 'factory.consume_correction',
                'factory.consume_correction_tdg', 'factory.consume_cleanup']
    for name in required:
        library.import_component(name, source/name)
    cz_adapter = library.import_canonical_cz(ROOT/'artifacts/demos/aod-held-cz-20261007/CZ', source/'CZ')
    save_artifact(out/'canonical-CZ-adapter.json', cz_adapter)
    derivations = []
    for path in sorted(source.glob('factory.*')):
        if path.name.startswith('factory.consume') or not (path/'physical-plan.json').exists():
            continue
        derivations.append(library.import_producer_component(path.name[8:], path))
    save_artifact(out/'producer-recipes.json.gz', derivations)
    checkpoint = out/'checkpoint.json.gz'
    if checkpoint.exists():
        saved = read(checkpoint)
        if saved['inputs'] != inputs:
            raise ValueError('DEMO_CHECKPOINT_INPUT_CHANGED')
        fleet = FactoryFleet.restore(device, saved['fleet'], archive_root=out/'history')
        session = fleet.session
        states, window = saved['logical_states'], saved['next_window']
    else:
        session = EventSession(device, initial, run_id='shor17-prefix-four-factory-real-v1')
        fleet = FactoryFleet(session, req, reserve_ready=4)
        states = {o['id']: {'status': 'pending'} for o in prefix['operations']}
        window = 0
    frontier = FrozenFrontier(library, qualification_directory=out/'qualification', variant_limit=2048)
    frontier.materializations = [read(p) for p in sorted((out/'qualification').glob('*.json'))]
    dependencies, last = {}, {}
    for op in prefix['operations']:
        dependencies[op['id']] = {last[p] for p in op['patches'] if p in last}
        last.update({p: op['id'] for p in op['patches']})
    for name, value in [('inputs.json', inputs), ('prefix.json', prefix), ('layout.json', layout),
                        ('device.json', device), ('initial-state.json.gz', initial), ('requirements.json', req)]:
        save_artifact(out/name, value, immutable=True)
    started = time.monotonic()
    status = {'status': 'running', 'scope': '16_original_logical_operations_real_factory_internals', 'full_shor': False}

    def persist():
        save_artifact(checkpoint, {'inputs': inputs, 'fleet': fleet.checkpoint(),
                                  'logical_states': states, 'next_window': window})
        save_artifact(out/'status.json', {**status, 'next_window': window, 'time_us': session.now_us,
            'logical_completed': sum(s['status']=='completed' for s in states.values()),
            'factory_stages': {f: c.stage_id if c else None for f, c in fleet.lines.items()},
            'ready_inventory': fleet.inventory(), 'qualified_native_variants': len(frontier.materializations),
            'elapsed_wall_seconds': time.monotonic()-started, 'compiler_stats': library.stats})

    try:
        while window < max_windows:
            for rid, r in fleet.requests.items():
                if r['status'] == 'completed':
                    states[rid].update(status='completed', completed_us=r['completed_us'], token_id=r['token_id'])
            done = all(s['status']=='completed' for s in states.values())
            # Stop launching replacements at the prefix endpoint. Already
            # started producers finish to bounded same-W4 inventory.
            if not done:
                fleet.start_idle()
            ready = [o for o in prefix['operations'] if states[o['id']]['status']=='pending'
                     and all(states[d]['status']=='completed' for d in dependencies[o['id']])]
            for op in ready:
                if op['operation'] not in ('T', 'TDG'):
                    continue
                fleet.request(op['id'], op['patches'][0], gate=op['operation'],
                              encoded_state_ref=op['id'], logical_frame='identity')
                states[op['id']].update(status='waiting_magic', requested_us=session.now_us)
            fleet.assign_ready()
            work = fleet.frontier()
            calls = [{'component': library.component_for([w['physical_dag']]), 'dags': [w['physical_dag']]} for w in work]
            selected = []
            available = set(fleet.available_data_patches())
            for op in ready:
                if op['operation'] in ('T', 'TDG') or not set(op['patches']) <= available:
                    continue
                component = 'CZ_CANONICAL' if op['operation']=='CZ' else op['operation']
                ports = list(library.describe(component)['operands'])
                if len(ports) != len(op['patches']):
                    raise ValueError('LOGICAL_GATE_PORT_ARITY')
                dags = library.source(component, operands=dict(zip(ports, op['patches'], strict=True)),
                                      invocation_id=op['id'])
                for d in dags:
                    d['logical_source'] = deepcopy(op)
                    for n in d['nodes']:
                        n['source_ids'] = list(dict.fromkeys(n['source_ids']+[op['id']]))
                calls.append({'component': component, 'dags': dags})
                selected.append(op)
            if not calls:
                if done:
                    break
                raise ValueError('DEMO_NO_READY_PROGRESS')
            print(json.dumps({'event': 'prepare_frontier', 'window': window, 'time_us': session.now_us,
                              'components': [c['component'] for c in calls], 'atoms': len(initial['atoms'])}), flush=True)
            persist()
            entry = session.snapshot()
            call = frontier.prepare(calls, session)
            plan, atom = call['physical_plan'], call['atom_program']
            static = validate_physical_plan(plan, device)
            if static['failures']:
                save_artifact(out/'first-failure.json', static)
                raise ValueError('FRONTIER_STATIC_VALIDATION_FAILED')
            scenario = make_scenario(atom)
            # A declared fake branch exercises conditional work on just F1,
            # while every line's acceptance still comes from its own events.
            for rid in scenario['results']:
                if 'F1-e0-' in rid and '.rotate_04/r0/magic_read_m_d0' in rid:
                    scenario['results'][rid]['value'] = 1
            stem = f'window-{window:04d}'
            save_artifact(out/'windows'/(stem+'.json.gz'), {'physical_plan': plan, 'atom_program': atom,
                'context': call['context'], 'scenario': scenario, 'fleet_work': work,
                'logical_operations': selected, 'factory_before': fleet.snapshot()}, immutable=True)
            session.submit(atom, scenario, expected_revision=call['context']['revision'])
            session.advance()
            session.advance(max(session.now_us, max(a['t_end_us'] for a in atom['actions'])))
            ids = {a['id'] for a in atom['actions']}
            events = [deepcopy(session.events[a['id']]) for a in atom['actions']]
            results = {r: deepcopy(v) for r, v in session.results.items() if v['action_id'] in ids}
            trace = {'schema_version': 'EventTrace/0.2.0-draft', 'artifact_id': stem+'/trace',
                'provenance': {'owner': 'R0', 'fixture': False}, 'execution_kind': 'fake_event_run',
                'quantum_state_simulated': False, 'hardware_executed': False, 'loss_enabled': False,
                'sampled': False, 'measurement_origin': 'fake', 'atom_program_ref': atom['artifact_id'],
                'device_ref': device['artifact_id'], 'events': events, 'results': results,
                'final_state': session.state.export(session.now_us),
                'illumination_counts': {a: v-entry['illumination_counts'].get(a, 0)
                                        for a, v in session.state.illumination_counts.items()},
                'stats': {'t_start_us': entry['time_us'], 't_end_us': session.now_us,
                    'duration_us': session.now_us-entry['time_us'], 'action_count': len(ids), 'atom_count': 769,
                    'result_count': len(results), 'executed_action_count': sum(e['status']=='completed' for e in events),
                    'skipped_action_count': sum(e['status']=='skipped' for e in events)}}
            report = validate_physical_plan({**plan, 'atom_program': atom}, device, trace=trace)
            binding = DAGAudit('prefix_actual_session_binding', {}, fixture=False)
            inspect_window_binding(binding, plan, atom, call['context'], session.results, session.run_id)
            save_artifact(out/'traces'/(stem+'.json.gz'), trace, immutable=True)
            save_artifact(out/'validation'/(stem+'.json'), {'physical': report, 'binding': binding.report()}, immutable=True)
            if report['failures'] or not binding.report()['passed']:
                raise ValueError('FRONTIER_EVENT_VALIDATION_FAILED')
            fleet.commit(work, plan, atom, allow_other_work=bool(selected))
            for op in selected:
                owned = [a for n in plan['physical_dags'] if n.get('logical_source',{}).get('id')==op['id']
                         for s in n['nodes'] for a in atom['source_map'][s['id']]]
                states[op['id']] = {'status': 'completed', 'completed_us': max(session.completed[a] for a in owned),
                                    'window': window, 'actions': list(dict.fromkeys(owned))}
            save_artifact(out/'fleet'/(stem+'.json.gz'), fleet.snapshot(), immutable=True)
            keep_actions = {a for c in fleet.lines.values() if c for r in c.receipts for a in r['action_ids']}
            keep_results = {r for c in fleet.lines.values() if c for receipt in c.receipts for r in receipt['result_ids']}
            session.retire_committed(out/'history'/(stem+'.json.gz'), keep_action_ids=keep_actions,
                                     keep_result_ids=keep_results)
            window += 1
            print(json.dumps({'event': 'frontier_committed', 'window': window, 'time_us': session.now_us,
                'logical_completed': sum(s['status']=='completed' for s in states.values()),
                'ready': len(fleet.inventory()), 'stages': {f: c.stage_id if c else None for f,c in fleet.lines.items()}}), flush=True)
            persist()
        else:
            raise ValueError('DEMO_WINDOW_BUDGET_REACHED')
        if not all(s['status']=='completed' for s in states.values()) or len(fleet.completed) != 2:
            raise ValueError('DEMO_PREFIX_CONSUMPTION_INCOMPLETE')
        status.update(status='execution_complete_pending_independent_audit', complete=True)
        save_artifact(out/'logical-states.json', states)
        save_artifact(out/'final-fleet.json.gz', fleet.snapshot())
    except BaseException as exc:
        status.update(status='stopped_on_first_error', complete=False, error_type=type(exc).__name__, error=str(exc),
                      error_details=getattr(exc,'details',None))
        save_artifact(out/'first-error.json', status)
        raise
    finally:
        persist()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--layout', type=Path, required=True)
    p.add_argument('--prefix', type=Path, required=True)
    p.add_argument('--component-source', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    execute(a.layout, a.prefix, a.component_source, a.out)

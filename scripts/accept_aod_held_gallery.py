"""Audit the rebuilt carrier lifecycle against source and committed fake events."""
from pathlib import Path
from collections import defaultdict
import argparse, gzip, hashlib, json, sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from na_pipeline.validation import validate_physical_dag_source


def read(path):
    path = Path(path)
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def carrier_audit(atom, trace):
    initial = atom['initial_state']['atoms']
    carrier = {a['atom_id']: a['carrier'] for a in initial}
    pos = {a['atom_id']: a['position_um'] for a in initial}
    trap = {a['atom_id']: a['trap_id'] for a in initial}
    active, held, cycles = {}, {}, {}
    events = {e['action_id']: e for e in trace['events']}
    assert set(events) == {a['id'] for a in atom['actions']}
    points = defaultdict(lambda: [[], []])
    pulse_count = pair_count = move_count = 0
    for a in atom['actions']:
        e = events[a['id']]
        assert e['status'] in ('completed', 'skipped')
        assert (e['t_start_us'], e['t_end_us']) == (a['t_start_us'], a['t_end_us'])
        if e['status'] == 'skipped':
            continue
        assert not any('slm:gate:' in r for r in a['resources']), a['id']
        if a['kind'] not in ('pickup', 'drop', 'move') and a['payload'].get('name') != 'CZ':
            continue
        assert a['t_end_us'] > a['t_start_us'], a['id']
        points[a['t_start_us']][1].append(a)
        points[a['t_end_us']][0].append(a)
    for t, (ends, starts) in sorted(points.items()):
        for a in ends:
            p = a['payload']
            if a['kind'] == 'move':
                for tr in p['trajectories']:
                    pos[tr['atom_id']] = tr['to_um']
            elif a['kind'] in ('pickup', 'drop'):
                for b in p['bindings']:
                    q = b['atom_id']
                    assert trap[q] == b['from_trap_id'] and pos[q] == b['position_um']
                    trap[q] = b['to_trap_id']
                    carrier[q] = 'AOD' if a['kind'] == 'pickup' else 'SLM'
                    if a['kind'] == 'drop':
                        cycle = cycles[held.pop(q)]
                        cycle['returned'].add(q)
                        if cycle['pulses']:
                            assert pos[q] == cycle['home'][q] and trap[q] == cycle['home_trap'][q], (a['id'], q)
                            assert p['purpose'] == 'enola_cz_return'
            active.pop(a['id'])
        for a in starts:
            p = a['payload']
            if a['kind'] in ('pickup', 'drop', 'move'):
                expected = 'SLM' if a['kind'] == 'pickup' else 'AOD'
                assert all(carrier[q] == expected for q in a['atoms']), (a['id'], expected)
                assert not any(set(a['atoms']) & set(x['atoms']) for x in active.values()), a['id']
            if a['kind'] == 'pickup':
                cycles[a['id']] = {'home': {q: pos[q] for q in a['atoms']},
                    'home_trap': {q: trap[q] for q in a['atoms']}, 'pulses': set(), 'returned': set(),
                    'atoms': set(a['atoms']), 'purpose': p.get('purpose')}
                for q in a['atoms']:
                    assert q not in held
                    held[q] = a['id']
            elif a['kind'] == 'move':
                move_count += 1
                for tr in p['trajectories']:
                    assert pos[tr['atom_id']] == tr['from_um'], a['id']
            elif p.get('name') == 'CZ':
                pulse_count += 1
                assert p.get('carrier_policy') == 'stationary-aod-held-cz/1'
                assert 'rydberg:global' in a['resources']
                pulse_cycles = set()
                for pair in p['pairs']:
                    pair_count += 1
                    assert {carrier[q] for q in pair} == {'AOD', 'SLM'}, (a['id'], pair)
                    assert not any(set(pair) & set(x['atoms']) for x in active.values()), a['id']
                    q = next(q for q in pair if carrier[q] == 'AOD')
                    assert 'trap:' + trap[q] in a['resources']
                    pulse_cycles.add(held[q])
                assert len(pulse_cycles) == 1
                cycle = cycles[next(iter(pulse_cycles))]
                assert cycle['purpose'] == 'enola_cz_transport'
                cycle['pulses'].add(a['id'])
            active[a['id']] = a
    assert not active and not held and all(v == 'SLM' for v in carrier.values())
    for c in cycles.values():
        assert c['returned'] == c['atoms']
        if c['purpose'] == 'enola_cz_transport':
            assert len(c['pulses']) == 1
    final = trace['final_state']['atoms']
    final = final.values() if isinstance(final, dict) else final
    for a in final:
        q = a['atom_id']
        assert carrier[q] == a['carrier'] and pos[q] == a['position_um'] and trap[q] == a['trap_id']
    return {'passed': True, 'cz_pulses': pulse_count, 'cz_pairs': pair_count,
        'moves': move_count, 'capture_cycles': len(cycles),
        'CZ_cycles_returned_to_original_SLM': sum(bool(c['pulses']) for c in cycles.values())}


def upstream(out):
    catalog = read(out / 'catalog.json')
    names = [r['id'] for r in catalog['components'] if r['kind'] == 'physical'] + ['SE_PAIR']
    assert len(names) == 66
    old = ROOT / 'artifacts/demos/neutral-modular-20261007'
    rows = []
    for n in names:
        folder = out / n
        s, v, device = [read(folder / f) for f in ('summary.json', 'validation.json', 'device.json')]
        assert s['status'] == 'passed' and v['passed'] and not v['failures'] and not v['unverified'], n
        assert s['implementation_version'] == 'neutral-modular/1'
        assert not any(s.get('composition_search_delta', {}).values()), n
        assert device['zones']['measurement']['x_range_um'] == [None, None]
        assert device['rigid_readout']['schema_version'] == 'rigid-readout-profile/0.3'
        assert device['rigid_readout']['max_parallel_readouts'] is None
        dag = read(folder / 'physical-dag.json')
        if isinstance(dag, list):
            reports = [validate_physical_dag_source(d) for d in dag]
            source = {'schema_version': 'JointSourceAudit/0.1', 'passed': all(r['passed'] for r in reports),
                'scoped_pass': all(r['scoped_pass'] for r in reports), 'reports': reports,
                'failures': [f for r in reports for f in r['failures']],
                'unverified': [f for r in reports for f in r['unverified']]}
        else:
            source = validate_physical_dag_source(dag)
        assert source['scoped_pass'] and not source['failures'], (n, source)
        if n in ('SE', 'H', 'CX', 'CZ', 'S', 'SDG'):
            assert source['passed'] and not source['unverified'], (n, source)
        save(folder / 'source-semantics.json', source)
        source_hash = digest(folder / 'physical-dag.json')
        assert source_hash == digest(old / n / 'physical-dag.json'), ('LOGICAL_CIRCUIT_CHANGED', n)
        audit = carrier_audit(read(folder / 'atom-program.json'), read(folder / 'event-trace.json'))
        save(folder / 'carrier-audit.json', audit)
        before = read(old / n / 'summary.json')
        rows.append({'component': n, 'source_unchanged_sha256': source_hash,
            'source_structure_passed': source['scoped_pass'], 'source_semantics_unverified': source['unverified'],
            'actions': s['action_count'], 'duration_us': s['duration_us'],
            'previous_duration_us': before['duration_us'], 'saved_us': before['duration_us'] - s['duration_us'],
            'carrier_audit': audit})
    result = {'schema_version': 'HeldCZUpstreamAudit/0.1', 'passed': True, 'components': rows,
        'logical_sources_byte_identical': True, 'compiler_invoked_by_audit': False,
        'scope': 'source semantics and committed carrier lifecycle; existing full-world validator receipts checked'}
    save(out / 'held-cz-upstream-audit.json', result)
    return result


def complete(out):
    first = read(out / 'held-cz-upstream-audit.json')
    assert first['passed'] and len(first['components']) == 66
    protocols = []
    for name, count in (('T', 39), ('TDG', 39), ('REJECT_RETRY', 26)):
        folder = out / 'protocols' / name
        s, guard = read(folder / 'summary.json'), read(folder / 'raw-search-observation.json')
        assert s['status'] == 'passed' and s['physical_stage_count'] == count
        assert guard['zero_native_calls'] and not any(guard['call_counts'].values())
        for key in ('leaf_compile_count', 'placement_search_count', 'routing_search_count', 'connector_compile_count'):
            assert s['module_stats'][key] == 0
        audits = []
        for phase in s['phases']:
            raw = read(folder / phase['artifact'])
            v = raw['validation']
            assert v['passed'] and not v['failures'] and not v['unverified']
            assert raw['atom_program']['time_basis'] == 'absolute_session'
            assert all(i['cache_hit'] and i['search_calls'] == 0 and i['static_geometry_passed'] for i in raw['physical_plan']['module_composition']['instances'])
            audits.append({'stage': phase['id'], **carrier_audit(raw['atom_program'], raw['trace'])})
        controller, pool = read(folder / 'controller.json'), read(folder / 'pool.json')
        if name != 'REJECT_RETRY':
            assert controller['terminal'] == 'consumed' and controller['token']['status'] == 'consumed'
            assert not pool['active_leases']
        else:
            assert s['outcome'] == 'rejected_cleaned_and_new_epoch_initialized'
            assert s['phases'][-1]['epoch'] == 1 and s['phases'][-1]['stage_id'] == 'initialize'
            assert controller['epoch'] == 1 and controller['token'] is None
            assert len([x for x in pool['history'] if x['event'] == 'release' and x['epoch'] == 0]) == 1
        save(folder / 'carrier-audit.json', {'passed': True, 'stages': audits})
        protocols.append({'id': name, 'stages': count, 'actions': s['action_count'],
            'duration_us': s['duration_us'], 'module_stats': s['module_stats'], 'outcome': s['outcome'],
            'cz_pulses': sum(a['cz_pulses'] for a in audits), 'native_entry_guard': guard})
    viewer = read(out / 'held-cz-functional-checks.json')
    paths = read(out / 'viewer-path-audit.json')
    assert viewer['passed'] and viewer['components'] == 71
    assert paths['passed'] and paths['components'] == 71 and paths['original_fallback_count'] == 0
    regions = read(out / 'viewer-regions.json')['regions']
    assert len(regions) == 71
    for r in regions.values():
        assert r['measurement'] == [None, None, 1020, 1220]
        assert digest(out / r['source']) == r['source_sha256']
    assert len(read(out / 'viewer-resource-export.json')['components']) == 71
    dispatch = read(ROOT / 'knowledge/roles/R0/aod-held-cz-dispatch-v2.json')
    dp = Path(dispatch['dispatch'])
    receipt = read(dp.parent / 'held-cz-receipt/worker-receipt.json')
    job = read(dp.parent / 'held-cz-receipt/job/status.json')
    assert receipt['source_snapshot_stable'] and receipt['input_snapshot_verified']
    assert job['returncode'] == 0
    inventory = read(dp.parent / 'held-cz-receipt/source-inventory.json')
    core = {rel: value for rel, value in inventory.items() if rel.startswith(('src/', 'tests/'))}
    assert core
    for rel, value in core.items():
        assert digest(ROOT / rel) == value, ('LOCAL_QUALIFIED_CORE_DRIFT', rel)
    for name in ('held-cz-fetch-upstream.json', 'held-cz-fetch-complete.json'):
        export = read(dp.parent / name)
        assert export['all_exported_bytes_verified']
        for rel, item in export['manifest']['files'].items():
            if rel.startswith('artifacts/demos/'):
                assert digest(ROOT / rel) == item['sha256'], ('FROZEN_OUTPUT_CHANGED', rel)
    result = {'schema_version': 'HeldCZGalleryAcceptance/0.1', 'engineering_passed': True,
        'component_count': 70, 'parallel_examples': 1, 'physical_components': first['components'],
        'protocols': protocols, 'logical_sources_byte_identical': True,
        'module_artifacts': len(list((out / 'compiled-modules').glob('*.json'))),
        'viewer_checks': viewer, 'path_audit': paths, 'job': job,
        'window': 'animation-library.html', 'window_sha256': digest(out / 'animation-library.html'),
        'source_snapshot_stable': True, 'input_and_output_bytes_verified': True,
        'local_core_files_match_server': len(core),
        'display_source_sha256': {rel: digest(ROOT / rel) for rel in ('viewer/components.js', 'viewer/lab-renderer.js',
            'viewer/components.html', 'viewer/components.css', 'viewer/motion-preview.js', 'viewer/resource-schedule.js')},
        'scope': 'compiled device model and no-loss fake events', 'quantum_state_simulated': False,
        'hardware_executed': False, 'fault_tolerance_qualified': False, 'full_shor_executed': False,
        'browser_rendering_verified': False, 'user_visual_acceptance': 'pending'}
    save(out / 'acceptance.json', result)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--out', default='artifacts/demos/aod-held-cz-20261007')
    p.add_argument('--complete', action='store_true')
    a = p.parse_args()
    result = (complete if a.complete else upstream)(ROOT / a.out)
    print(json.dumps({'passed': result.get('passed', result.get('engineering_passed')), 'phase': 'complete' if a.complete else 'upstream'}))

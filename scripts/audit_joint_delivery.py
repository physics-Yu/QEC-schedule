"""Read-only full-gallery evidence and same-device performance attribution.

This complements, and never relaxes, audit_joint_factory. No plans are compiled
or retimed. Work sums and elapsed unions are deliberately reported separately.
"""
from collections import Counter, defaultdict
from pathlib import Path
import argparse
import gzip
import hashlib
import json

from audit_joint_factory import plan_audit


def read(path):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def digest_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def elapsed_unions(actions, start, end):
    cuts = defaultdict(Counter)
    for a in actions:
        kind = 'CZ' if a['payload'].get('name') == 'CZ' else a['kind']
        if a['t_end_us'] > a['t_start_us']:
            cuts[a['t_start_us']][kind] += 1
            cuts[a['t_end_us']][kind] -= 1
    active = Counter(); elapsed = Counter(); cursor = start
    for t, delta in sorted(cuts.items()):
        assert t >= cursor - 1e-7
        label = '+'.join(sorted(k for k, v in active.items() if v)) or 'idle_or_result_latency'
        elapsed[label] += t - cursor
        active.update(delta); cursor = t
    elapsed['idle_or_result_latency'] += end - cursor
    assert abs(sum(elapsed.values()) - (end - start)) < 1e-6
    return dict(elapsed)


def source_metrics(plan):
    ops = {o['id']: o for d in plan['physical_dags'] for o in d['nodes']}
    parents = {sid: set(o['after']) for sid, o in ops.items()}
    for dag in plan['physical_dags']:
        for e in dag['edges']:
            parents[e['target']].add(e['source'])
    depth = {}; pending = set(ops)
    while pending:
        ready = sorted(s for s in pending if parents[s] <= depth.keys())
        assert ready, 'SOURCE_DAG_CYCLE'
        for sid in ready:
            depth[sid] = 1 + max((depth[p] for p in parents[sid]), default=0)
        pending.difference_update(ready)
    pulses = [a for a in plan['atom_program']['actions'] if a['payload'].get('name') == 'CZ']
    blocks = defaultdict(list)
    for o in ops.values():
        for block in {q.rsplit('/', 1)[0] for q in o['qubits']}:
            blocks[block].append(o)
    rows = {}
    for block, items in sorted(blocks.items()):
        ids = {o['id'] for o in items}
        local_depth = {}
        for sid in sorted(ids, key=lambda s: depth[s]):
            local_depth[sid] = 1 + max((local_depth[p] for p in parents[sid] & ids), default=0)
        rows[block] = {
            'source_operations_touching_block': len(items),
            'source_gate_counts': dict(Counter(o['params'].get('name', o['kind']) for o in items)),
            'source_dependency_depth_including_local_fences': max(local_depth.values(), default=0),
            'actual_CZ_layers_touching_block': sum(any(s['physical_op_id'] in ids for s in a['payload']['pair_sources']) for a in pulses),
        }
    return {'per_block': rows, 'all_source_operation_count': len(ops),
            'source_dependency_depth': max(depth.values(), default=0),
            'depth_scope': 'unit-cost source DAG including typed edges; not a hardware lower bound; inter-block gates count at both endpoints'}


def reasons(plan):
    frontiers = plan['module_composition']['dependency_graph'].get('joint_frontiers', [])
    grouped = Counter(); detailed = Counter(); deferred = 0
    for f in frontiers:
        deferred += len(f['deferred'])
        for item in f.get('unselected_details', []):
            assert item['all_reassignments_proven_infeasible'] is False
            for choice in item['alternatives']:
                reason = choice['reason']; detailed[reason] += 1
                if reason in ('Enola_pair_or_axis_conflict_with_selected_assignment',
                              'capture_includes_fixed_partner_or_foreign_AOD_group',
                              'EXTRA_BROADCAST_PAIR'):
                    kind = 'conflict_for_this_assignment_only'
                elif reason == 'qualified_extension_deferred_by_direction_or_cohort_policy':
                    kind = 'scheduling_policy'
                else:
                    kind = 'routing_or_search_not_qualified'
                grouped[kind] += 1
    limits = Counter(c['reason'] for m in plan['module_composition']['instances'] for c in m['schedule_constraints'])
    return {'candidate_alternative_reasons': dict(detailed), 'reason_classes': dict(grouped),
            'partial_cohort_policy_deferrals': deferred, 'schedule_constraint_counts': dict(limits),
            'compiler_static_scene_limit_is_hardware_limit': False,
            'all_alternative_assignments_ruled_out': False}


def inspect(plan, store, label):
    strict = plan_audit(plan, store, label)
    actions = plan['atom_program']['actions']
    stats = plan['atom_program']['stats']
    ops = {o['id']: o for d in plan['physical_dags'] for o in d['nodes']}
    pulses = [a for a in actions if a['payload'].get('name') == 'CZ']
    sources = [s['physical_op_id'] for a in pulses for s in a['payload']['pair_sources']]
    expected = [o['id'] for o in ops.values() if o['kind'] == 'gate' and len(o['qubits']) == 2]
    assert sorted(sources) == sorted(expected), (label, 'COUPLING_COVERAGE')
    h_by_source = defaultdict(list)
    for a in actions:
        if a['payload'].get('name') == 'H':
            for sid in a['payload'].get('physical_op_ids', []):
                h_by_source[sid].append(a)
    for pulse in pulses:
        for source in pulse['payload']['pair_sources']:
            sid = source['physical_op_id']
            if ops[sid]['params']['name'] != 'CX':
                continue
            hs = sorted(h_by_source[sid], key=lambda a: a['t_start_us'])
            assert len(hs) == 2 and all(source['atoms'][1] in a['atoms'] for a in hs), (label, sid, 'TARGET_H_COVERAGE')
            assert hs[0]['t_end_us'] <= pulse['t_start_us'] and hs[1]['t_start_us'] >= pulse['t_end_us'], (label, sid, 'H_CZ_H_ORDER')
    strict.update(source_metrics(plan))
    strict['non_parallel_reasons'] = reasons(plan)
    strict['elapsed_union_by_action_kind_us'] = elapsed_unions(actions, stats.get('t_start_us', 0.), stats['t_end_us'])
    strict['work_sum_is_not_elapsed_time'] = True
    return strict


def audit(out, preview, baseline):
    store = out/'compiled-modules'; inputs = {}; rows = []; protocols = {}
    def pin(p):
        inputs[str(p)] = digest_file(p)
        return read(p)
    for p in sorted(out.glob('*/physical-plan.json')):
        rows.append(inspect(pin(p), store, p.parent.name))
    assert len(rows) == 66, ('COMPONENT_COVERAGE', len(rows))
    for p in sorted((out/'parallel-examples').glob('*/physical-plan.json')):
        rows.append(inspect(pin(p), store, p.parent.name))
    assert len(rows) == 70, ('PARALLEL_EXAMPLE_COVERAGE', len(rows))
    for name in ('T', 'TDG', 'REJECT_RETRY'):
        folder = out/'protocols'/name; summary = pin(folder/'summary.json')
        current_device = pin(folder/'device.json')
        assert current_device == pin(preview/'protocols'/name/'device.json') == pin(baseline/'protocols'/name/'device.json'), (name, 'DEVICE_COMPARISON_CHANGED')
        old = pin(preview/'protocols'/name/'summary.json'); old_by_id = {p['id']: p for p in old['phases']}
        legacy = pin(baseline/'protocols'/name/'summary.json')
        assert set(old_by_id) == {p['id'] for p in summary['phases']}, (name, 'PHASE_SET_CHANGED')
        stage_rows = []
        for phase in summary['phases']:
            plan = pin(folder/phase['artifact'])['physical_plan']
            prior = pin(preview/'protocols'/name/old_by_id[phase['id']]['artifact'])['physical_plan']
            assert plan['physical_dags'] == prior['physical_dags'], (name, phase['id'], 'SOURCE_DAG_CHANGED')
            row = inspect(plan, store, name+'/'+phase['id']); rows.append(row); stage_rows.append(row)
        total = sum(r['duration_us'] for r in stage_rows)
        assert abs(total - summary['duration_us']) < 1e-6
        counts = Counter(); work = Counter(); unions = Counter(); reason_counts = Counter()
        for row in stage_rows:
            counts.update(row['counts']); work.update(row['action_work_us']); unions.update(row['elapsed_union_by_action_kind_us'])
            reason_counts.update(row['non_parallel_reasons']['reason_classes'])
        ready = lambda s: next((p['end_us'] for p in s['phases'] if p['stage_id'] == 'convert_output'), None)
        protocols[name] = {'duration_us': summary['duration_us'], 'preview_duration_us': old['duration_us'],
                           'cohort_baseline_duration_us': legacy['duration_us'],
                           'factory_through_ready_us': ready(summary), 'preview_factory_through_ready_us': ready(old),
                           'identical_device_verified': True, 'identical_source_DAG_to_preview': True,
                           'action_counts': dict(counts), 'action_work_us': dict(work), 'elapsed_union_us': dict(unions),
                           'candidate_reason_classes': dict(reason_counts), 'phase_count': len(stage_rows)}
    frames = sorted((out/'frame-continuations').glob('*/frame-session.json.gz'))
    assert len(frames) == 7
    for p in frames:
        data = pin(p)
        for i, entry in enumerate(data['entries']):
            rows.append(inspect(entry['physical_plan'], store, p.parent.name+'/'+str(i)))
    result = {'schema_version': 'JointDeliveryEvidence/0.1', 'passed': True, 'plans_checked': len(rows),
              'components_and_pair': 66, 'parallel_examples': 4, 'frame_cases': 7,
              'strict_selected_batch_and_all_CX_H_CZ_H_checked': True, 'protocols': protocols,
              'plans': rows, 'input_sha256': inputs, 'compiled_or_retimed': False,
              'global_optimality_claimed': False, 'noise_or_fault_tolerance_qualified': False,
              'user_visual_acceptance': 'pending'}
    (out/'joint-delivery-evidence.json').write_bytes((json.dumps(result, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--out', type=Path, required=True)
    p.add_argument('--preview', type=Path, default=Path('artifacts/demos/joint-factory-accepted-20261008'))
    p.add_argument('--baseline', type=Path, default=Path('artifacts/demos/frame-cnot-cohorts-20261008'))
    args = p.parse_args(); result = audit(args.out, args.preview, args.baseline)
    print(json.dumps({k: v for k, v in result.items() if k not in ('plans', 'input_sha256')}, ensure_ascii=False))

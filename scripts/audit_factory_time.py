"""Read-only timing attribution for the frozen successful distillation branch."""
from pathlib import Path
from collections import Counter, defaultdict
import gzip, hashlib, json, sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from na_pipeline.qec.factory import MATRIX
from na_pipeline.qec.factory_primitives import merged_zz_checks


def read(p):
    data = p.read_bytes()
    return json.loads(gzip.decompress(data) if p.suffix == '.gz' else data)


def category(op):
    name = op['id'].rsplit('/', 1)[-1]
    if op.get('metadata', {}).get('joint_zz_geometry_scope'):
        if '_merge_' in name:
            return 'joint_ZZ_merge'
        if '_split_' in name:
            return 'joint_ZZ_split_SE_and_fix'
        return 'joint_ZZ_parity_and_cleanup'
    if name.startswith(('hold_', 'live_data_hold', 'output_hold')):
        return 'maintenance_SE'
    if name.startswith('raw'):
        return 'raw_A_QEC' if '_qec_' in name else 'raw_A_encoder'
    if name.startswith(('fanin_', 'uncompute_')):
        return 'transversal_parity_CX'
    if name.startswith(('phase_fix', 'output_same_carrier_S')):
        return 'S_SE'
    if name.startswith(('magic_read', 'injection_pauli')):
        return 'injection_readout_feedback'
    if name.startswith(('terminal_', 'acceptance')):
        return 'terminal_readout_accept'
    if name.startswith('work_plus'):
        return 'encoded_plus_prepare'
    return 'other:' + name.split('_')[0]


def main():
    base = ROOT / 'artifacts/demos/aod-held-cz-20261007'
    folder = base / 'protocols/T'
    summary = read(folder / 'summary.json')
    selected = [p for p in summary['phases'] if not p['stage_id'].startswith('consume')]
    rows, inputs = [], {}
    total_categories, total_kinds = Counter(), Counter()
    transfer_count = cz_count = pair_count = source_count = module_count = 0
    extra_serial_pairs = resource_disjoint_pairs = 0
    examples = []
    for phase in selected:
        path = folder / phase['artifact']
        inputs[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        raw = read(path)
        source = {o['id']: o for d in raw['physical_plan']['physical_dags'] for o in d['nodes']}
        source_count += len(source)
        modules = raw['physical_plan']['module_composition']['instances']
        actions = raw['atom_program']['actions']
        action_modules = defaultdict(list)
        for a in actions:
            action_modules[a['id'].rsplit('/action:', 1)[0]].append(a)
        costs, module_types = Counter(), Counter()
        ancestors, resources, previous_end = [], [], 0.
        for i, m in enumerate(modules):
            groups = {category(source[s]) for s in m['source_ids']}
            key = next(iter(groups)) if len(groups) == 1 else 'mixed:' + '+'.join(sorted(groups))
            assert m['start_us'] >= previous_end - 1e-7
            costs[key] += m['end_us'] - m['start_us']
            costs['inter_module_gap'] += m['start_us'] - previous_end
            previous_end = m['end_us']
            module_types[m['kind']] += 1
            deps = {int(x.split(':')[-1]) for x in m['dependency_ids']}
            anc = deps | {p for d in deps for p in ancestors[d]}
            ancestors.append(anc)
            use = {r for a in action_modules[m['instance_id']] for r in a['resources']}
            resources.append(use)
            if i and i - 1 not in anc:
                extra_serial_pairs += 1
                if not use & resources[i - 1]:
                    resource_disjoint_pairs += 1
                    if len(examples) < 6:
                        prev = modules[i - 1]
                        examples.append({'phase': phase['id'], 'earlier_module': i - 1, 'later_module': i,
                            'earlier_us': [prev['start_us'], prev['end_us']], 'later_us': [m['start_us'], m['end_us']],
                            'earlier_kind': prev['kind'], 'later_kind': m['kind'], 'source_DAG_orders_pair': False,
                            'resource_sets_disjoint': True, 'concurrent_geometry_revalidated': False,
                            'earlier_sources': prev['source_ids'], 'later_sources': m['source_ids']})
        assert abs(previous_end - (phase['end_us'] - phase['start_us'])) < 1e-7
        assert abs(sum(costs.values()) - previous_end) < 1e-7
        cuts = defaultdict(Counter)
        kinds = Counter()
        for a in actions:
            kind = 'CZ' if a['payload'].get('name') == 'CZ' else 'gate_1q' if a['kind'] == 'gate' else a['kind']
            if a['t_end_us'] > a['t_start_us']:
                cuts[a['t_start_us']][kind] += 1
                cuts[a['t_end_us']][kind] -= 1
            transfer_count += a['kind'] in ('pickup', 'drop')
            if kind == 'CZ':
                cz_count += 1
                pair_count += len(a['payload']['pairs'])
        active, cursor = Counter(), phase['start_us']
        for t, delta in sorted(cuts.items()):
            if t > cursor:
                key = '+'.join(sorted(k for k, v in active.items() if v)) or 'idle_or_result_latency'
                kinds[key] += t - cursor
            active.update(delta)
            cursor = t
        kinds['idle_or_result_latency'] += phase['end_us'] - cursor
        assert abs(sum(kinds.values()) - previous_end) < 1e-7
        total_categories.update(costs)
        total_kinds.update(kinds)
        module_count += len(modules)
        rows.append({'stage': phase['stage_id'], 'duration_us': previous_end, 'module_cost_us': dict(costs),
            'module_kinds': dict(module_types), 'physical_actions': len(actions), 'source_operations': len(source)})
    zz = read(base / 'JOINT_ZZ/atom-program.json')
    cz = [a for a in zz['actions'] if a['payload'].get('name') == 'CZ']
    captures = sum(a['kind'] == 'pickup' for a in zz['actions'])
    merged = merged_zz_checks()
    total = selected[-1]['end_us'] - selected[0]['start_us']
    result = {'schema_version': 'FactoryTimingBottleneckAudit/0.1', 'scope': 'frozen current T success branch, initialization through READY',
        'duration_us': total, 'source_operations': source_count, 'module_instances': module_count,
        'raw_A_inputs': 15, 'transversal_logical_CX_compute_uncompute': 2 * sum(sum(row[c] for row in MATRIX) - 1 for c in range(4, 15)),
        'injection_joint_ZZ_calls': 11, 'atom_actions': sum(r['physical_actions'] for r in rows),
        'transfers': transfer_count, 'CZ_pulses': cz_count, 'CZ_pairs': pair_count,
        'time_by_source_module_us': dict(total_categories.most_common()), 'planned_time_union_by_action_kind_us': dict(total_kinds.most_common()),
        'joint_ZZ_standalone': {'duration_us': zz['stats']['duration_us'], 'capture_return_cycles': captures,
            'pickup_drop_time_us': captures * 400, 'CZ_pulses': len(cz), 'one_pair_CZ_pulses': sum(len(a['payload']['pairs']) == 1 for a in cz),
            'merge_rounds': 3, 'checks_per_round': len(merged), 'CX_per_merge_round': sum(len(c['support']) for c in merged),
            'split_SE_rounds': 6},
        'consecutive_module_pairs_not_ordered_by_source_DAG': extra_serial_pairs,
        'also_disjoint_resource_sets': resource_disjoint_pairs, 'parallel_candidates': examples,
        'candidate_scope': 'proves extra serialization; concurrency still needs changed resource scheduling and dynamic geometry validation',
        'stages': rows, 'input_sha256': inputs,
        'source_sha256': {r: hashlib.sha256((ROOT / r).read_bytes()).hexdigest() for r in (
            'src/na_pipeline/qec/factory_primitives.py', 'src/na_pipeline/qec/factory.py',
            'src/na_pipeline/backend/compiled_modules.py', 'src/na_pipeline/backend/module_graph.py',
            'src/na_pipeline/backend/strategy_compile.py')},
        'compiler_invoked': False, 'new_physical_plan_generated': False, 'quantum_state_simulated': False,
        'hardware_executed': False, 'fault_tolerance_qualified': False}
    out = ROOT / 'knowledge/roles/R0/evidence/factory-time-bottlenecks-20261008.json'
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in ('stages', 'input_sha256', 'source_sha256', 'parallel_candidates')}, ensure_ascii=False))


if __name__ == '__main__':
    main()

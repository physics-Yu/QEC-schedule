"""Record the completed cold build and its immutable reuse interface."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from na_pipeline.backend.enola_kernel import digest
from na_pipeline.backend.compiled_modules import native_compiler_sources
from frozen_native_identity import frozen_native_sources


def read(p):
    return json.loads(p.read_bytes())


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, obj):
    p.write_bytes((json.dumps(obj, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))


def seal(out, dispatch):
    job = dispatch.parent; record = read(dispatch)
    worker = read(job/'held-cz-receipt/worker-receipt.json')
    assert worker['returncode'] == 0 and worker['source_snapshot_stable'] and worker['input_snapshot_verified']
    assert read(out/'residency-and-frame-complete.json')['status'] == 'passed'
    assert read(out/'status.json')['status'] == 'passed'
    strict = read(out/'joint-parallel-acceptance.json'); assert strict['passed']
    full = read(out/'joint-delivery-evidence.json'); assert full['passed']
    cohort = read(out/'cohort-acceptance.json'); assert cohort['passed']
    checks = ['cohort-acceptance.json', 'joint-parallel-acceptance.json', 'joint-delivery-evidence.json',
              'atom-brightness-functional-checks.json', 'frame-functional-checks.json', 'viewer-path-audit.json']
    for n in checks:
        assert read(out/n)['passed'], n
    assert read(out/'viewer-path-audit.json')['original_fallback_count'] == 0
    suites = {}
    for name in ('qec', 'backend', 'device', 'runtime', 'validation'):
        t = (out/(name+'-tests.log')).read_text(encoding='utf-8')
        assert '\nOK' in t, name
        suites[name] = int(re.findall(r'Ran (\d+) tests?', t)[-1])
    manifest = json.loads((out/'manifest.js').read_text(encoding='utf-8').split('=', 1)[1].strip().removesuffix(';'))
    assert len(manifest['components']) == 82
    native = frozen_native_sources(dispatch); native_hash = digest(native)
    current_native = native_compiler_sources()
    immutable = {}; lookups = {}; modules = 0; proofs = 0
    for p in sorted((out/'compiled-modules').glob('*.json')):
        item = read(p); body = item['body']; assert digest(body) == item['hash'], p
        if item['schema_version'] == 'CompiledModule/0.1':
            assert body['compiler_sources'] == native, p
            modules += 1
        elif item['schema_version'] == 'JointFrontierDecision/0.1':
            assert body['identity']['compiler_hash'] == native_hash, p
            if p.name.startswith('frontier-proof-'):
                assert p.name == 'frontier-proof-'+item['hash']+'.json', p
                proofs += 1
            else:
                lookups[p.name] = sha(p); continue
        else:
            raise ValueError('UNEXPECTED_MODULE_SCHEMA '+str(p))
        immutable[p.name] = sha(p)
    protocols = {}
    for name in ('T', 'TDG', 'REJECT_RETRY'):
        summary = read(out/'protocols'/name/'summary.json')
        guard = read(out/'protocols'/name/'raw-search-observation.json')
        assert summary['status'] == 'passed' and guard['zero_native_calls'] and not any(guard['call_counts'].values())
        assert all(summary['module_stats'][k] == 0 for k in ('leaf_compile_count', 'placement_search_count', 'routing_search_count'))
        assert summary['module_stats_current_process']['frontier_search_count'] == 0
        protocols[name] = {'duration_us': summary['duration_us'], 'stages': summary['physical_stage_count'], 'new_native_calls_on_compose': 0}
    frames = {p.parent.name: read(p) for p in (out/'frame-continuations').glob('*/summary.json')}
    assert len(frames) == 7 and all(v['status'] == 'passed' for v in frames.values())
    assert all(frames[n]['action_count'] == 0 and frames[n]['duration_us'] == 0 for n in ('H_VIRTUAL', 'H_THEN_H'))
    inventory = read(job/'held-cz-receipt/source-inventory.json')
    source_files = {p: v for p, v in inventory.items() if p.startswith('src/')}
    local_drift = [p for p, v in source_files.items() if not (ROOT/p).is_file() or sha(ROOT/p) != v]
    fixed = {
        'schema_version': 'RepairedModuleLibrary/0.1', 'status': 'sealed_scoped_engineering_passed',
        'server_job_id': record['job_id'], 'remote_project': record['project'],
        'remote_directory': record['project']+'/'+record['spec']['output_roots'][0]+'/compiled-modules',
        'local_directory': str((out/'compiled-modules').resolve()),
        'native_rule_hash': native_hash, 'native_rule_sources': native,
        'current_workspace_native_rule_hash': digest(current_native),
        'current_workspace_native_identity_matches': current_native == native,
        'frozen_source_inventory_sha256': sha(job/'held-cz-receipt/source-inventory.json'),
        'fixed_source_files': source_files, 'local_source_drift_from_frozen_build': local_drift,
        'module_artifacts': modules, 'immutable_frontier_proofs': proofs,
        'immutable_file_sha256': immutable, 'mutable_lookup_snapshot_sha256': lookups,
        'read_interface': {
            'compiler': 'LogicalComponentCompiler(device, module_directory=directory)',
            'build': 'build_dependencies(dag, complete_world) explicitly constructs missing qualified geometry variants',
            'compose': 'compose_recipe(dag, complete_world, execution_context=...) performs binding only; missing leaf/frontier rejects',
            'qualification': 'same native identity/device/source shape and checked complete-world entry/exit geometry; no blanket qualification for a new Shor world',
            'never_cached': ['measurement_results', 'frames', 'tokens', 'epochs', 'runtime_state', 'acceptance'],
        },
        'validation_scope': {'components_and_pair': 66, 'protocols': protocols, 'frame_cases': 7,
                             'parallel_examples': 4, 'checked_plans': full['plans_checked'],
                             'all_selected_CZ_batches_single_pulse': True, 'all_CX_target_H_CZ_H': True},
        'full_shor_qualified_by_this_library': False, 'user_visual_acceptance': 'pending',
        'further_parallel_optimization': 'deferred_by_user; not a basic pipeline delivery prerequisite',
    }
    save(out/'library-manifest.json', fixed)
    result = {
        'schema_version': 'RepairedJointGalleryAcceptance/0.1', 'status': 'engineering_passed_visual_pending',
        'entries': 82, 'server_job_id': record['job_id'], 'regressions': suites, 'regressions_total': sum(suites.values()),
        'scope': fixed['validation_scope'], 'protocols': protocols,
        'same_device_and_source_DAG_as_frozen_preview_verified': True,
        'committed_batch_parallelism_audit_passed': True, 'global_parallel_optimality_claimed': False,
        'further_optimization_is_basic_pipeline_gate': False,
        'noise_or_fault_tolerance_qualified': False, 'quantum_state_simulated': False, 'hardware_executed': False,
        'browser_rendering_verified': False, 'user_visual_acceptance': 'pending',
        'remaining_limits': ['SE remains five physical CZ batches in the canonical case',
                             'separate motion leaves still use a static geometry-scene reservation',
                             'bounded assignment search is not a global optimality proof',
                             'cross-module residency requires matching arrays and return homes',
                             'H-to-T retains explicit physical H materialization'],
        'evidence_sha256': {n: sha(out/n) for n in checks+['library-manifest.json', 'animation-library.html']},
    }
    save(out/'acceptance.json', result)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--out', type=Path, required=True); p.add_argument('--dispatch', type=Path, required=True)
    a = p.parse_args(); result = seal(a.out, a.dispatch)
    print(json.dumps({k: result[k] for k in ('status', 'entries', 'regressions_total', 'protocols', 'user_visual_acceptance')}))

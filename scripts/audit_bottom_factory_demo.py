"""Independent bounded-prefix audit; derive transitions from event results.

No compilation, runtime replay, controller decision/acceptance helper, or
precomputed 'passed' flags are used to qualify the run.
"""
from pathlib import Path
from copy import deepcopy
from collections import Counter
import argparse
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'scripts')]
from run_bottom_factory_demo import read
from na_pipeline.backend.enola_kernel import digest
from na_pipeline.runtime.compilation_guard import CompilationGuard
from na_pipeline.runtime.history import verify_chunks
from na_pipeline.validation.dag_core import DAGAudit
from na_pipeline.validation.dag_physical import validate_physical_plan
from na_pipeline.validation.dag_session import inspect_window_binding
from na_pipeline.validation.stream_factory import _template, _cleanup
from na_pipeline.qec.factory import build_factory_producer
from na_pipeline.qec import get_component_spec


def audit_run(run):
    device, prefix, layout, initial = (read(run/n) for n in ('device.json','demo-program.json','layout.json','initial-state.json.gz'))
    checkpoint = read(run/'checkpoint.json.gz')
    fleet = read(run/'final-fleet.json.gz')
    states = read(run/'logical-states.json')
    audit = DAGAudit('shor17_bottom_factory_interaction', {}, fixture=False)
    if read(run/'status.json')['status'] != 'execution_complete_pending_independent_audit':
        raise ValueError('COMPLETED_PREFIX_REQUIRED')
    if len(initial['atoms']) != 769 or len(layout['factories']) != 4:
        audit.fail('USER_LAYOUT_COUNT', 'Require 289 data plus 480 factory atoms')
    if {a['qubit_id']:a['position_um'] for a in initial['atoms']} != {a['id']:a['xy_um'] for a in layout['atoms']}:
        audit.fail('USER_LAYOUT_IDENTITY', 'Original placement/identity changed')
    verify_chunks(checkpoint['fleet']['body']['session']['body']['history_chunks'], archive_root=run/'history')
    protocols, consumers = {}, {}
    ledgers = fleet['completed_attempts']+[c for c in fleet['lines'].values() if c]
    for ledger in ledgers:
        pid = ledger['protocol_ref']
        m = re.fullmatch(r'(F[0-3])-e(\d+)-(.+)-T', pid)
        if m is None:
            raise ValueError('FACTORY_PROTOCOL_ID')
        protocol = build_factory_producer(factory_id=m[1], epoch=int(m[2]), batch_id=m[3])
        if digest(protocol) != ledger['protocol_hash']:
            audit.fail('FROZEN_PROTOCOL_HASH', 'Factory source identity changed', protocol_id=pid)
        protocols[pid] = protocol
        if 'consumer_protocol' in ledger:
            consumers[ledger['consumer_protocol']['artifact_id']] = ledger['consumer_protocol']
    all_protocols = {**protocols, **consumers}
    expected = {pid: p['entry'] for pid,p in protocols.items()}
    observed, results, action_ids, data_actions, physical_end = {}, {}, set(), {}, {}
    qualified_sources = set()
    accepted, converted, consumed = set(), set(), set()
    prior = {a['atom_id']:(a['qubit_id'], a['position_um'], a['carrier'], a.get('site_id')) for a in initial['atoms']}
    windows = sorted((run/'windows').glob('window-*.json.gz'))
    start = 0.
    bytes_checked = {}
    with CompilationGuard() as guard:
        for wi,path in enumerate(windows):
            w, trace = read(path), read(run/'traces'/path.name)
            plan, atom, context = w['physical_plan'], w['atom_program'], w['context']
            qualified_sources.update(digest(m['dag']) for m in plan['module_composition']['dependency_graph']['modules'])
            runtime_guard = plan.get('frozen_frontier',{}).get('runtime_guard',{})
            if runtime_guard.get('violation_count') != 0 or runtime_guard.get('native_compile_allowance') != 0:
                audit.fail('UNEXPECTED_RUNTIME_COMPILATION','Runtime binding must retain a zero-compilation guard')
            current = {a['atom_id']:(a['qubit_id'], a['position_um'], a['carrier'], a.get('site_id')) for a in atom['initial_state']['atoms']}
            if current != prior or context['time_us'] != start:
                audit.fail('CROSS_WINDOW_WORLD', 'World or clock discontinuity', window=wi)
            if set(a['id'] for a in atom['actions']) & action_ids:
                audit.fail('ACTION_REPLAY', 'Repeated action identity', window=wi)
            action_ids.update(a['id'] for a in atom['actions'])
            results.update(trace['results'])
            report = validate_physical_plan({**plan,'atom_program':atom},device,trace=trace)
            audit.failures.extend({**f,'window':wi} for f in report['failures'])
            audit.unverified.extend({**f,'window':wi} for f in report['unverified'])
            inspect_window_binding(audit, plan, atom, context, results, fleet['run_id'])
            events = {e['action_id']:e for e in trace['events']}
            actions = {a['id']:a for a in atom['actions']}
            mapping = {a['qubit_id']:a['atom_id'] for a in atom['initial_state']['atoms']}
            for dag in plan['physical_dags']:
                own = list(dict.fromkeys(a for n in dag['nodes'] for a in atom['source_map'][n['id']]))
                end = max([actions[a]['t_end_us'] for a in own]+[results[r]['ready_us'] for r in dag['result_producers']])
                if 'logical_source' in dag:
                    source = dag['logical_source']
                    if source != prefix['operations'][source['source_gate_index']]:
                        audit.fail('ORIGINAL_LOGICAL_SOURCE', 'Logical source/angle/target differs from the saved prefix')
                    if source['operation']=='CZ':
                        ns=dag['nodes'];left,right=source['patches']
                        original=get_component_spec('CZ')['physical_dag']['nodes']
                        partners=[int(n['qubits'][1].rsplit('d',1)[1]) for n in original]
                        def move(xs,p):
                            ys=[None]*9
                            if sorted(p)!=list(range(9)):raise ValueError('CZ_ADAPTER_PERMUTATION')
                            for i,j in enumerate(p):ys[j]=xs[i]
                            return ys
                        if len(ns)!=11 or ns[0]['kind']!='permute' or ns[-1]['kind']!='permute':
                            audit.fail('CANONICAL_CZ_SOURCE','Canonical CZ must contain both explicit transports')
                        else:
                            middle=move(list(range(9)),ns[0]['params']['destination_indices'])
                            restored=move(middle,ns[-1]['params']['destination_indices'])
                            if (middle!=partners or restored!=list(range(9)) or
                                any(n['kind']!='gate' or n['params']!={'name':'CZ'} or
                                    n['qubits']!=[left+'/d'+str(i),right+'/d'+str(i)] for i,n in enumerate(ns[1:10]))):
                                audit.fail('CANONICAL_CZ_PAIR_EQUIVALENCE','Transport and pulse do not reproduce the original CZ pairs')
                    data_actions[source['id']] = own
                    physical_end[source['id']] = end
                    continue
                binding = dag.get('protocol_binding', {})
                pid, stage = binding.get('protocol_id'), binding.get('stage_id')
                if pid not in all_protocols:
                    audit.fail('MISSING_FACTORY_SOURCE', 'Every stage needs its exact original protocol', protocol_id=pid)
                    continue
                p = all_protocols[pid]
                production = p.get('consumer_link',{}).get('producer_protocol_id',pid)
                if pid not in expected:
                    if production not in converted:
                        audit.fail('CONSUMER_BEFORE_CONVERSION', 'Consumption precedes actual output conversion')
                    expected[pid] = 'consume'
                if stage != expected[pid]:
                    audit.fail('FACTORY_STAGE_ORDER', 'A stage skips a branch or dependency', expected=expected[pid], actual=stage)
                _template(audit, dag, p)
                selected_atom = {**atom, 'actions':[actions[a] for a in own]}
                live = {mapping[q] for q in p['live_data_information_qubit_ids']}
                if any(events[a]['status']=='completed' and actions[a]['kind'] in ('measure','reset')
                       and set(actions[a]['atoms']) & live for a in own):
                    audit.fail('LIVE_DATA_DESTROYED', 'Factory work destroys its existing data target')
                step = p['stages'][stage]
                following = step.get('next')
                if step.get('branch'):
                    branch = step['branch'];result = results.get(branch['result_id'])
                    if result is None or result['ready_us'] > trace['stats']['t_end_us']:
                        audit.fail('BRANCH_BEFORE_RESULT', 'Branch lacks a published result')
                    else:
                        following = branch['one'] if result['value'] else branch['zero']
                if stage == 'terminal_checks':
                    passes = [sum(results[r]['value'] for r in check['result_ids'])%2 == check['expected_parity']
                              for check in p['acceptance_checks']]
                    if len(passes)==4 and all(passes):
                        accepted.add(pid)
                    if (following=='convert_output') != (pid in accepted):
                        audit.fail('ACCEPTANCE_FROM_EVENTS', 'Acceptance differs from measured terminal parities')
                if stage == 'convert_output':
                    protected = {mapping[q] for q in p['output']['qubit_ids'] if '/d' in q}
                    if pid not in accepted or any(actions[a]['kind'] in ('measure','reset') and
                        events[a]['status']=='completed' and set(actions[a]['atoms']) & protected for a in own):
                        audit.fail('SAME_CARRIER_CONVERSION', 'Accepted W4 output was not preserved')
                    converted.add(pid)
                if stage == 'consume':
                    consumed.add(production)
                if stage in p['cleanup_stage_ids']:
                    _cleanup(audit,selected_atom,events,p['factory_qubit_ids'],p['live_data_information_qubit_ids'])
                expected[pid] = following
                observed[(pid,stage)] = {'dag_hash':digest(dag),'atom_hash':digest(atom),'actions':own,
                                         'result_ids':sorted(dag['result_producers']),'end_us':end}
            prior = {a['atom_id']:(a['qubit_id'],a['position_um'],a['carrier'],a.get('site_id')) for a in trace['final_state']['atoms']}
            start = trace['stats']['t_end_us']
            bytes_checked[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            if audit.failures:
                break
            print(json.dumps({'audit_window':wi+1,'actions':len(action_ids),'failures':len(audit.failures)}),flush=True)
    tokens = set()
    for ledger in ledgers:
        for receipt in ledger['stage_receipts']:
            observed_stage = observed.get((receipt['protocol_id'],receipt['stage_id']))
            if (not observed_stage or receipt['physical_dag_hash'] != observed_stage['dag_hash']
                or receipt['atom_program_hash'] != observed_stage['atom_hash']
                or set(receipt['action_ids']) != set(observed_stage['actions'])
                or receipt['result_ids'] != observed_stage['result_ids'] or receipt['end_us'] < observed_stage['end_us']):
                audit.fail('RECEIPT_EVENT_BINDING','Controller receipt lacks its exact completed actions')
        token = ledger.get('token')
        pid = ledger['protocol_ref']
        if token:
            carrier = {a['atom_id'] for a in initial['atoms'] if a['qubit_id'].startswith(protocols[pid]['output']['block_id']+'/')}
            if token['token_id'] in tokens or set(token['output_atom_ids']) != carrier or token['epoch'] != ledger['epoch'] or pid not in converted:
                audit.fail('TOKEN_CARRIER_EPOCH','Token was reused, substituted, or produced without conversion')
            tokens.add(token['token_id'])
        if ledger['terminal']=='consumed' and (pid not in consumed or not token or token['status']!='consumed'):
            audit.fail('TOKEN_CONSUMPTION','Terminal consumption lacks actual same-token work')
    for op in prefix['operations']:
        state = states[op['id']]
        if state['status'] != 'completed':
            audit.fail('PREFIX_INCOMPLETE','Logical source was not completed',logical_id=op['id'])
        if op['operation'] in ('T','TDG'):
            request = fleet['requests'].get(op['id'],{})
            if request.get('status')!='completed' or request.get('target_patch')!=op['patches'][0] or request.get('gate')!=op['operation'] or request.get('token_id')!=state.get('token_id') or request.get('reservation',{}).get('data_port',{}).get('encoded_state_ref')!=op['id']:
                audit.fail('LOGICAL_MAGIC_CONSUMPTION','Logical T target, sign, or consumed token changed')
            ledger=next((l for l in ledgers if l.get('token',{}).get('token_id')==request.get('token_id')),None)
            suffix=ledger.get('consumer_protocol',{}) if ledger else {}
            if (not ledger or suffix.get('request_gate')!=op['operation'] or suffix.get('data_block_id')!=op['patches'][0]
                or suffix.get('consumer_link',{}).get('producer_protocol_id')!=ledger['protocol_ref']
                or ledger.get('consumer_binding',{}).get('output_port',{}).get('token_id')!=request.get('token_id')):
                audit.fail('CONSUMER_SOURCE_REQUEST_LINK','Actual consumer source is detached from the requested sign, target, or producer')
        elif op['operation']=='H':
            event=state.get('frame_event',{})
            if event.get('requested_gate')!='H' or event.get('blocks')!=op['patches'] or not event.get('software_only') or event.get('physical_components') or state.get('actions'):
                audit.fail('SOFTWARE_H_EVIDENCE','H must be a frame event without transport')
            before=event.get('before',{}).get(op['patches'][0],{}).get('observable_pullback',{})
            after=event.get('after',{}).get(op['patches'][0],{}).get('observable_pullback',{})
            if after!={'X':before.get('Z'),'Y':dict(axis=before.get('Y',{}).get('axis'),sign=-before.get('Y',{}).get('sign',0)),'Z':before.get('X')}:
                audit.fail('SOFTWARE_H_ALGEBRA','Signed Pauli pullback is incorrect')
        elif op['id'] not in data_actions or state['completed_us'] < physical_end[op['id']]:
            audit.fail('LOGICAL_WITHOUT_ACTIONS','Logical completion lacks actual events')
    # Derive positive simultaneous AOD movement evidence from completed events.
    overlaps=[]
    for path in windows:
        w=read(path);tr=read(run/'traces'/path.name);completed={e['action_id'] for e in tr['events'] if e['status']=='completed'}
        moves={g:[a for a in w['atom_program']['actions'] if a['id'] in completed and a['kind']=='move' and a['payload'].get('aod_group')==g] for g in ('data','magic')}
        for a in moves['data']:
            for b in moves['magic']:
                lo,hi=max(a['t_start_us'],b['t_start_us']),min(a['t_end_us'],b['t_end_us'])
                if lo<hi:overlaps.append(dict(window=path.name,start_us=lo,end_us=hi,data_action=a['id'],magic_action=b['id']))
        if any(n.get('metadata',{}).get('protocol')=='logical_H_transversal_plus_atom_transport' for d in w['physical_plan']['physical_dags'] for n in d['nodes']):
            audit.fail('LEGACY_H_EXECUTION','Old logical H transport is forbidden in this demo')
    if not overlaps:audit.fail('TWO_AOD_NEVER_MOVE_TOGETHER','Actual data/magic moves must overlap')
    if max(a['xy_um'][1] for a in layout['atoms'] if a['aod_group']=='magic') >= min(a['xy_um'][1] for a in layout['atoms'] if a['aod_group']=='data'):
        audit.fail('FACTORY_NOT_BELOW_DATA','Actual initial layout must put all factories below data')
    if len(consumed)!=1:audit.fail('T_CONSUMPTION_COUNT','This demo must consume one actual produced T')
    if not any(int(re.search(r'-e(\d+)-',l['protocol_ref'])[1])>0 and l['stage_receipts'] for l in ledgers):
        audit.fail('NO_REPLACEMENT_PRODUCTION','Production must restart after actual T consumption and cleanup')
    (run/'dual-aod-overlap.json').write_text(json.dumps(overlaps,indent=2))
    for stopped in (run/'stops').glob('*/selected-sources.json'):
        proof=read(stopped);raw=(stopped.parent/proof['source']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=proof['file_sha256']:raise ValueError('STOP_EVIDENCE_HASH')
        prior_plan=read(stopped.parent/proof['source'])['physical_plan']
        qualified_sources.update(digest(m['dag']) for m in prior_plan['module_composition']['dependency_graph']['modules'])
    qualifications=[read(p) for p in sorted((run/'qualification').glob('*.json'))]
    if len({r['identity'] for r in qualifications})!=len(qualifications):
        audit.fail('REPEATED_QUALIFICATION','The same fragment/geometry was compiled more than once')
    if any(r['status']!='qualified_native_body_built' or r['world_atoms']!=769 or r['fragment_sha256'] not in qualified_sources for r in qualifications):
        audit.fail('UNSCOPED_QUALIFICATION','Native materialization lacks a selected frozen source and complete world')
    audit.metrics.update(world_atoms=769, logical_operations=len(prefix['operations']), windows=len(windows), actions=len(action_ids),
        producer_epochs=len(protocols), consumed_outputs=len(consumed), ready_outputs=len(fleet['ready_inventory']),
        dual_aod_overlapping_move_pairs=len(overlaps), factories=4, duration_us=fleet['time_us'], qualified_native_variants=len(list((run/'qualification').glob('*.json'))))
    result = audit.report()
    result.update(full_shor=False, guard=guard.receipt(), input_window_byte_sha256=bytes_checked,
                  user_visual_acceptance='pending', scheduling_scope='independent line state machines with complete-stage physical submission boundaries')
    (run/'acceptance.json').write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode())
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args()
    r=audit_run(a.run);print(json.dumps({'passed':r['passed'],'failures':r['failures'][:5],'unverified':r['unverified'][:5]},ensure_ascii=False))
    raise SystemExit(0 if r['passed'] else 2)

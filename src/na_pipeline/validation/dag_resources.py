"""Independent finite-world and lease-boundary checks; no token/state simulator.

Inputs are the published R3 requirements, R1 initial world, R5 pool snapshot,
unchanged submitted AtomPrograms and EventSession trace. These checks do not
replace source/geometry validation or qualify candidate/ready token semantics.
"""
from collections import Counter
from math import isfinite

from .checker import _hash
from .dag_core import DAGAudit
from .dag_entry import inspect_inventory_continuity

LOCALS=tuple([f'd{i}' for i in range(9)]+[f'x{i}' for i in range(4)]+[f'z{i}' for i in range(4)])


def inspect_resource_world(audit,requirements,initial,*,algorithm_patch_count=5):
    if requirements['schema_version']!='PhysicalResourceRequirements/0.1.0':
        audit.fail('RESOURCE_SCHEMA','Unsupported physical inventory schema'); return
    patches=requirements['patches']; slots=requirements['factory_slots']; nonpatch=requirements['nonpatch_atoms']
    algorithm={p for p,row in patches.items() if row['role']=='algorithm'}
    factory=set(patches)-algorithm
    if len(algorithm)!=algorithm_patch_count or len(factory)!=7 or set(slots)!=set(['W0','W1','W2','W3','W4','M','Y']) or set(slots.values())!=factory or len(nonpatch)!=1:
        audit.fail('RESOURCE_WORLD_SHAPE','World must retain every algorithm patch plus exactly seven factory patches and one probe')
    expected={p+'/'+q for p in patches for q in LOCALS}|{q['physical_qubit_id'] for q in nonpatch}
    if set(requirements['physical_qubit_ids'])!=expected or len(requirements['physical_qubit_ids'])!=len(expected) or requirements['physical_qubit_count']!=len(expected):
        audit.fail('RESOURCE_QUBIT_DECLARATION','Physical inventory differs from the complete patch/probe expansion')
    atoms={a['qubit_id']:a for a in initial['atoms']}
    if set(atoms)!=expected or len(initial['atoms'])!=len(expected) or len({a['atom_id'] for a in initial['atoms']})!=len(expected):
        audit.fail('RESOURCE_WORLD_INCOMPLETE','Initial world has missing, additional, or aliased carriers')
    counts=Counter(a['aod_group'] for a in initial['atoms'])
    for q,atom in atoms.items():
        expected_group='data' if q.rsplit('/',1)[0] in algorithm else 'magic'
        if atom['aod_group']!=expected_group: audit.fail('RESOURCE_AOD_ASSIGNMENT','Carrier belongs to the wrong independent AOD',qubit_id=q)
    expected_counts={'algorithm_patches':len(algorithm),'factory_patches':7,'factory_atoms':120,'nonpatch_atoms':1,'data_aod_atoms':17*len(algorithm),'magic_aod_atoms':120}
    if requirements['counts']!=expected_counts or counts!={'data':17*len(algorithm),'magic':120}:
        audit.fail('RESOURCE_COUNTS','Declared counts differ from the actual carrier inventory')
    scratch=requirements['shared_phase_scratch']; probe=nonpatch[0]['physical_qubit_id']; mutex=requirements['factory_id']+':protocol_mutex'
    if scratch!={'phase_aux':slots['Y'],'bridge':probe,'exclusive_mutex':mutex,'additional_carriers':0}:
        audit.fail('RESOURCE_PHASE_ALIAS','S/SDG must use the same factory Y/probe and mutex, without extra carriers')
    rules=requirements['lease_rules']; expected_s={mutex,slots['Y'],probe,'operand:block'}; expected_t={mutex,probe,'operand:block'}|factory
    for kind,expected_resources in (('S_SDG',expected_s),('T_TDG',expected_t)):
        resources=rules[kind]['exclusive']
        if set(resources)!=expected_resources or len(resources)!=len(expected_resources): audit.fail('RESOURCE_EXCLUSIVE_RULE','Published lease omits or aliases a required exclusive resource',operation_group=kind)
    if rules['T_TDG']['ready_token_carrier']!=slots['W4'] or rules['T_TDG']['consume_once'] is not True or rules['T_TDG']['new_epoch_requires_cleanup'] is not True:
        audit.fail('RESOURCE_TOKEN_RULE','Output carrier, single claim, and physical epoch cleanup are required')
    if requirements['initial_ready_magic_tokens'] or initial.get('ready_magic_tokens') or requirements['startup_actions'] or requirements['dynamic_carrier_creation_allowed'] is not False:
        audit.fail('RESOURCE_FREE_MAGIC_OR_EXPANSION','The preinitialized finite world cannot supply ready magic or allow carrier creation')
    audit.metrics.update(algorithm_patches=len(algorithm),factory_patches=len(factory),world_carriers=len(atoms),data_aod_carriers=counts['data'],magic_aod_carriers=counts['magic'])


def inspect_protocol_completion(audit,programs,trace,end_us,*,earliest_us=0.):
    """O03/O07/O09: every selected action/result, including parallel cleanup.

    A legitimately false conditional branch is skipped, not required to execute.
    This helper binds actual events to original programs, not to a success flag.
    """
    if type(end_us) not in (int,float) or not isfinite(end_us) or end_us<earliest_us:
        audit.fail('PROTOCOL_BOUNDARY_TIME','Invalid protocol completion boundary'); return {}
    events={e['action_id']:e for e in trace['events']}; results=trace['results']; actions={}
    if len(events)!=len(trace['events']): audit.fail('PROTOCOL_EVENT_DUPLICATE','Trace repeats an action identity')
    for program in programs:
        for action in program['actions']:
            aid=action['id']
            if aid in actions: audit.fail('PROTOCOL_ACTION_DUPLICATE','An action was counted in more than one submitted program',action_id=aid)
            actions[aid]=action
            event=events.get(aid)
            if event is None:
                audit.fail('PROTOCOL_TERMINAL_PENDING','Completion omitted an actual action, possibly a parallel cleanup terminal',action_id=aid); continue
            for field in ('kind','atoms','payload','condition','depends_on','t_start_us','t_end_us'):
                if event[field]!=action[field]: audit.fail('PROTOCOL_EVENT_DETACHED','Event differs from its committed action',action_id=aid,field=field)
            if action['t_start_us']<earliest_us or action['t_end_us']>end_us:
                audit.fail('PROTOCOL_EARLY_RELEASE','Boundary precedes actual protocol completion or reuses an earlier epoch action',action_id=aid)
            reads=set(action.get('reads',[]))|set(action['payload'].get('reads',[])); condition=action['condition']
            if condition: reads.add(condition['bit'])
            for rid in reads:
                if rid not in results or results[rid]['ready_us']>action['t_start_us']:
                    audit.fail('PROTOCOL_READ_NOT_READY','Actual feedback precedes the producer-ready event',action_id=aid,result_id=rid)
            skip=condition is not None and condition['bit'] in results and results[condition['bit']]['value']!=condition['equals']
            if event['status']!=('skipped' if skip else 'completed'):
                audit.fail('PROTOCOL_BRANCH_STATUS','Action completion/skip is inconsistent with actual published results',action_id=aid)
            writes=[] if skip else action.get('writes',action['payload'].get('writes',[]))
            if set(event['result_ids'])!=set(writes): audit.fail('PROTOCOL_RESULT_COVERAGE','Boundary omitted a required writer result',action_id=aid)
            for rid in writes:
                record=results.get(rid)
                if record is None or record['action_id']!=aid or not action['t_end_us']<=record['ready_us']<=end_us:
                    audit.fail('PROTOCOL_RESULT_PENDING','Release precedes a required result or uses another result producer',action_id=aid,result_id=rid)
            for dep in action['depends_on']:
                if dep not in events or events[dep]['status'] not in ('completed','skipped') or events[dep]['t_end_us']>action['t_start_us']:
                    audit.fail('PROTOCOL_DEPENDENCY_PENDING','Protocol action precedes a required committed dependency',action_id=aid,dependency=dep)
    if not actions: audit.fail('PROTOCOL_EMPTY_COMPLETION','An empty helper receipt cannot prove protocol completion')
    return actions


def inspect_pool_history(audit,requirements,initial,pool,programs,trace):
    expected_hash=_hash(requirements); mapping={a['qubit_id']:a['atom_id'] for a in initial['atoms']}
    if pool['schema_version']!='finite-resource-pool/0.1' or pool['requirements_hash']!=expected_hash or pool['qubit_to_atom']!=mapping:
        audit.fail('POOL_WORLD_BINDING','Pool snapshot changed the requirements or physical carrier identity')
    if pool['initial_ready_magic_tokens']: audit.fail('POOL_FREE_MAGIC','Finite pool cannot create a ready resource at entry')
    inspect_inventory_continuity(audit,initial,[trace['final_state']],required_qubit_ids=requirements['physical_qubit_ids'])
    plans=trace['submitted_plans']; by_hash={_hash(p):p for p in programs}
    if len(by_hash)!=len(programs) or set(by_hash)!={p['plan_hash'] for p in plans}:
        audit.fail('POOL_PLAN_COVERAGE','Original submitted AtomPrograms are incomplete, duplicated or detached from the trace'); return
    for plan in plans:
        program=by_hash[plan['plan_hash']]
        if set(plan['action_ids'])!={a['id'] for a in program['actions']}: audit.fail('POOL_PLAN_ACTION_BINDING','Submission action inventory differs from its original plan')
    events={e['action_id']:e for e in trace['events']}; active={}; owners=set(); releases=0; last_time=-1.
    for record in pool['history']:
        owner=record['owner']
        if record['event']=='acquire':
            at=record['acquired_us']; operation=record['operation']; target=record['target_patch']
            if owner in owners or record['epoch']!=len(owners): audit.fail('POOL_EPOCH_OR_OWNER','Lease epoch is not new and monotonic, or owner is reused',owner=owner)
            owners.add(owner)
            if operation not in ('S','SDG','T','TDG') or target not in requirements['patches'] or requirements['patches'][target]['role']!='algorithm':
                audit.fail('POOL_OPERATION_TARGET','Lease requires a supported protocol and existing live algorithm patch',owner=owner); continue
            resources={target if r=='operand:block' else r for r in requirements['lease_rules']['S_SDG' if operation in ('S','SDG') else 'T_TDG']['exclusive']}
            if set(record['resources'])!=resources or len(record['resources'])!=len(resources) or record['requirements_hash']!=expected_hash or record['session_run_id']!=trace['run_id'] or record['ready_magic_token'] is not None:
                audit.fail('POOL_LEASE_BINDING','Acquisition changed actual resources/world/session or supplied a free token',owner=owner)
            if any(resources&set(other['resources']) for other in active.values()): audit.fail('POOL_OVERLAPPING_LEASE','S scratch and factory share exclusive carriers and protocol mutex',owner=owner)
            count=record['entry_plan_count']
            if type(count) is not int or not 0<=count<=len(plans) or any(p['submitted_us']>at for p in plans[:count]) or any(p['submitted_us']<at for p in plans[count:]):
                audit.fail('POOL_ACQUIRE_FRONTIER','Lease entry plan frontier does not match actual submissions',owner=owner)
            active[owner]={k:v for k,v in record.items() if k!='event'}
        elif record['event']=='release':
            at=record['released_us']; lease=active.get(owner)
            if lease is None: audit.fail('POOL_RELEASE_ABSENT','Release has no live exclusive lease',owner=owner); continue
            if record['epoch']!=lease['epoch']: audit.fail('POOL_RELEASE_EPOCH','Cleanup receipt belongs to a different lease epoch',owner=owner)
            hashes=record['committed_plan_hashes']; start=lease['entry_plan_count']; end=start+len(hashes)
            if not hashes or hashes!=[p['plan_hash'] for p in plans[start:end]] or any(p['submitted_us']<at for p in plans[end:]):
                audit.fail('POOL_RELEASE_PLAN_PREFIX','Release omitted or substituted a submitted protocol plan',owner=owner)
            selected=[by_hash[h] for h in hashes if h in by_hash]
            actions=inspect_protocol_completion(audit,selected,trace,at,earliest_us=lease['acquired_us'])
            expected={q for q in mapping if any(q==r or q.startswith(r+'/') for r in lease['resources'] if r!=lease['target_patch'])}
            expected_atoms={mapping[q] for q in expected}; resets=record['cleanup_action_ids']; covered=set(); reset_ends={}
            if set(record['reset_qubit_ids'])!=expected: audit.fail('POOL_RESET_COVERAGE','Cleanup must cover exactly every leased reusable carrier',owner=owner)
            if len(set(resets))!=len(resets): audit.fail('POOL_RESET_DUPLICATE','Cleanup counts a reset action twice',owner=owner)
            for aid in resets:
                event=events.get(aid)
                if aid not in actions or event is None or event['status']!='completed' or event['kind']!='reset' or event['payload'].get('state')!=0 or event['payload'].get('params',{}).get('basis','Z')!='Z' or not lease['acquired_us']<=event['t_start_us']<=event['t_end_us']<=at:
                    audit.fail('POOL_RESET_NOT_EXECUTED','Cleanup needs actual same-epoch completed physical Z0 resets',action_id=aid); continue
                covered.update(event['atoms'])
                for atom in event['atoms']: reset_ends[atom]=max(reset_ends.get(atom,0),event['t_end_us'])
            if covered!=expected_atoms: audit.fail('POOL_RESET_COVERAGE','Physical reset events do not exactly cover leased scratch/factory carriers',owner=owner)
            live={mapping[lease['target_patch']+'/d'+str(i)] for i in range(9)}
            for aid,action in actions.items():
                event=events.get(aid)
                if event is None or event['status']=='skipped': continue
                touched=set(action['atoms'])
                if action['kind']=='gate' and action['payload'].get('name')=='CZ': touched={a for pair in action['payload'].get('pairs',[]) for a in pair}
                if action['kind'] in ('reset','measure') and touched&live: audit.fail('POOL_LIVE_DATA_DESTROYED','Release cleanup destructively touched live target data',action_id=aid)
                if action['kind'] in ('gate','measure','reset') and any(action['t_end_us']>reset_ends[a] for a in touched&set(reset_ends)): audit.fail('POOL_RESET_NOT_FINAL','Carrier was operated on after the alleged final cleanup',action_id=aid)
            if record['released_state']!={'kind':'physical_basis','basis':'Z','value':0,'encoding_status':'not_asserted_encoded'}:
                audit.fail('POOL_RESET_NOT_ENCODED','All physical Z0 does not certify encoded zero or a prepared Y resource',owner=owner)
            del active[owner]; releases+=1
        else:
            audit.fail('POOL_HISTORY_EVENT','Unsupported pool history event'); continue
        if not isfinite(at) or at<last_time or at>trace['final_state']['time_us']: audit.fail('POOL_HISTORY_TIME','Pool history lies outside actual monotonic session time',owner=owner)
        last_time=at
    if active!=pool['active_leases'] or len(owners)!=pool['next_epoch']: audit.fail('POOL_SNAPSHOT_HISTORY','Current leases or next epoch differ from replayed acquisition/release history')
    audit.metrics.update(lease_count=len(owners),released_leases=releases,active_leases=len(active),lifecycle_scope='pool resource exclusivity and actual selected-action/reset boundaries only; no token qualification')


def validate_resource_world(requirements,initial,*,fixture=False,algorithm_patch_count=5):
    audit=DAGAudit('finite_resource_world',{'requirements':requirements,'initial':initial},fixture=fixture)
    audit.interfaces={'R1-PREINITIALIZED-IF-001':'0.2.0','R3-PHYSICAL-DAG-001':'0.2.0-draft'}
    audit.check('full_finite_inventory_and_shared_scratch',lambda:inspect_resource_world(audit,requirements,initial,algorithm_patch_count=algorithm_patch_count))
    return audit.report()


def validate_resource_pool(requirements,initial,pool,programs,trace,*,fixture=False,algorithm_patch_count=5):
    audit=DAGAudit('finite_pool_lifecycle',{'requirements':requirements,'initial':initial,'pool':pool,'programs':programs,'trace':trace},fixture=fixture)
    audit.interfaces={'R1-PREINITIALIZED-IF-001':'0.2.0','R3-PHYSICAL-DAG-001':'0.2.0-draft','R5-RESOURCE-POOL-001':'0.1.0-draft','R8-FACTORY-PHASE-001':'0.2.0'}
    audit.check('finite_resource_world',lambda:inspect_resource_world(audit,requirements,initial,algorithm_patch_count=algorithm_patch_count))
    audit.check('pool_history_and_actual_cleanup',lambda:inspect_pool_history(audit,requirements,initial,pool,programs,trace))
    return audit.report()

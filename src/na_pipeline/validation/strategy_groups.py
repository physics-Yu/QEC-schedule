"""Group metrics from source identities and actual atom intervals, not labels."""
from collections import Counter,defaultdict
import math

from .checker import EPS


def check_group_source(audit,physical,ops):
    contract=physical['strategy_contract']; groups=contract['groups']; by_id={op['id']:op for op in ops}
    inventory={q['id']:q for q in physical['qubits']}
    operation=contract['operation']['name']
    covered=set()
    for group in groups:
        gid=group['group_id']; members=group['members']; purpose=group['purpose']
        qids=[m['physical_qubit_id'] for m in members]
        if len(qids)!=len(set(qids)) or not set(qids)<=inventory.keys(): audit.fail('GROUP_MEMBER_IDENTITY','Group has duplicate or undeclared qubits',group_id=gid)
        if purpose=='maintenance_readout':
            if len(members)!=8 or Counter(m['check_type'] for m in members)!={'X':4,'Z':4}:
                audit.fail('READOUT_GROUP_MEMBERS','Maintenance requires four X and four Z ancillas',group_id=gid)
            for member in members:
                q=member['physical_qubit_id']; measure=by_id[member['measurement_op_id']]
                if measure['kind']!='measure' or measure['qubits']!=[q] or measure['writes']!=[member['result_id']] or member['measurement_basis']!='Z' or measure['params']['basis']!='Z':
                    audit.fail('GROUP_MEASUREMENT_BINDING','Group result/basis differs from actual source measurement',group_id=gid,source_id=measure['id'])
                preceding=ops[:next(i for i,op in enumerate(ops) if op['id']==measure['id'])]
                couplings=[op for op in preceding if q in op['qubits'] and op['kind']=='gate' and len(op['qubits'])==2]
                if not couplings or member.get('last_coupling_op_id')!=couplings[-1]['id']:
                    audit.fail('GROUP_LAST_COUPLING','Last coupling dependency is absent or stale',group_id=gid,resource=q)
                basis_changes=[op for op in preceding if op['kind']=='gate' and op['qubits']==[q] and op['params'].get('name')=='H']
                expected=basis_changes[-1]['id'] if member['check_type']=='X' and basis_changes else None
                if member.get('basis_change_op_id')!=expected or (member['check_type']=='X' and expected is None):
                    audit.fail('GROUP_BASIS_CHANGE','X readout must retain its final H',group_id=gid,resource=q)
                covered.add(measure['id'])
        elif purpose=='patch_initialization_transport':
            if len(members)!=17: audit.fail('INITIALIZATION_GROUP_MEMBERS','Surface-17 initialization transports its complete declared patch',group_id=gid)
            for member in members:
                for ref in member['prepare_before_op_ids']:
                    op=by_id[ref]
                    if op['kind']!='reset' or member['physical_qubit_id'] not in op['qubits']:
                        audit.fail('INITIALIZATION_PREPARATION_BINDING','Transport/preparation boundary must identify this member reset',group_id=gid,source_id=ref)
        else: audit.need('GROUP_PURPOSE_UNSUPPORTED',f'Unsupported purpose {purpose}',group_id=gid)
    if operation in ('syndrome_round','prepare'):
        missing={op['id'] for op in ops if op['kind']=='measure'}-covered
        if missing: audit.fail('GROUP_MEASUREMENT_COVERAGE','Some source readouts lack a maintenance group',source_ids=sorted(missing))
    if operation=='syndrome_round':
        data={q['id'] for q in physical['qubits'] if q['role']=='data'}
        destroyed=[op['id'] for op in ops if op['kind'] in ('reset','measure') and data.intersection(op['qubits'])]
        if destroyed: audit.fail('MAINTENANCE_DESTROYS_DATA','Maintenance resets or measures live data',source_ids=destroyed)


def _span(values): return max(values)-min(values) if values else 0.


def group_metrics(audit,plan,physical,trace=None):
    groups=physical['strategy_contract']['groups']
    actions=plan['actions']; source_map=plan['source_map']; by_id={a['id']:a for a in actions}
    by_qubit={a['qubit_id']:a['atom_id'] for a in plan['initial_state']['atoms']}
    results=trace['results'] if trace is not None else None
    metrics=[]
    for group in groups:
        gid=group['group_id']; purpose=group['purpose']; members=group['members']
        atoms=[by_qubit[m['physical_qubit_id']] for m in members]
        if purpose=='maintenance_readout':
            records=[]; ids=[]
            for member,atom in zip(members,atoms):
                candidates=[by_id[key] for key in source_map[member['measurement_op_id']] if by_id[key]['kind']=='measure']
                if len(candidates)!=1:
                    audit.fail('GROUP_READOUT_COUNT','Each group member must have one actual readout',group_id=gid,resource=atom); continue
                measure=candidates[0]; ids.append(measure['id'])
                if measure['atoms']!=[atom] or measure['payload']['result_id']!=member['result_id']:
                    audit.fail('GROUP_ATOM_RESULT_BINDING','Readout changed atom/result binding',group_id=gid,action_id=measure['id'])
                prerequisites=[]
                for key in ('last_coupling_op_id','basis_change_op_id'):
                    if member.get(key):
                        prerequisites.extend(by_id[k] for k in source_map[member[key]] if by_id[k]['kind']=='gate')
                prerequisite_end=max((a['t_end_us'] for a in prerequisites),default=0.)
                transport=[a for a in actions if atom in a['atoms'] and a['kind'] in ('pickup','move','drop') and a['t_start_us']<measure['t_start_us']]
                transport_end=max((a['t_end_us'] for a in transport),default=0.)
                earliest=max(prerequisite_end,transport_end)
                if earliest>measure['t_start_us']+EPS: audit.fail('GROUP_READOUT_TOO_EARLY','Readout precedes member gate/transport readiness',group_id=gid,action_id=measure['id'])
                ready=results[member['result_id']]['ready_us'] if results is not None else measure['payload']['result_ready_us']
                if member.get('post_readout_reset_op_id'):
                    reset_actions=[by_id[k] for k in source_map[member['post_readout_reset_op_id']] if by_id[k]['kind']=='reset']
                    resets_end=max(a['t_end_us'] for a in reset_actions)
                    reset_source=member['post_readout_reset_op_id']
                    def own_return(a):
                        return (a['payload'].get('group_id')==gid or reset_source in a['payload'].get('physical_op_ids',[])) and a['payload'].get('purpose') in ('maintenance_readout_return','rigid_measurement_return')
                    returns=[a for a in actions if atom in a['atoms'] and a['kind']=='pickup' and own_return(a)]
                    aod_reset=all(a['payload'].get('carrier_at_reset',{}).get(atom)=='AOD' for a in reset_actions)
                    if aod_reset:
                        # Pickup is stationary. In the current device the
                        # service reset occurs after pickup, before translation.
                        moves=[a for a in actions if atom in a['atoms'] and a['kind']=='move'
                               and own_return(a) and a['t_start_us']>=measure['t_end_us']-EPS]
                        legal=bool(returns and moves) and max(a['t_end_us'] for a in returns)<=min(a['t_start_us'] for a in reset_actions)+EPS and min(a['t_start_us'] for a in moves)>=resets_end-EPS
                    else:
                        legal=bool(returns) and min(a['t_start_us'] for a in returns)>=resets_end-EPS
                    if not legal:
                        audit.fail('GROUP_RETURN_BEFORE_RESET','Return transport starts before the required member service reset',group_id=gid,resource=atom)
                records.append({'atom_id':atom,'result_id':member['result_id'],'earliest_readout_us':earliest,'t_start_us':measure['t_start_us'],'t_end_us':measure['t_end_us'],'result_ready_us':ready,'wait_us':measure['t_start_us']-earliest})
            if len(records)!=len(members): continue
            span=_span([r['t_start_us'] for r in records]); earliest_common=max(r['earliest_readout_us'] for r in records)
            transport=[a for a in actions if a['kind']=='pickup' and a['payload'].get('group_id')==gid]
            item={'group_id':gid,'purpose':purpose,'member_count':len(members),'readout_start_span_us':span,'readout_end_span_us':_span([r['t_end_us'] for r in records]),'result_ready_span_us':_span([r['result_ready_us'] for r in records]),'per_member':records,'per_atom_wait_us':{r['atom_id']:r['wait_us'] for r in records},'earliest_common_readout_us':earliest_common,'transport_batch_count':len({(a['t_start_us'],a['t_end_us'],a['payload'].get('aod_group')) for a in transport}),'readout_batch_count':len({(r['t_start_us'],r['t_end_us']) for r in records}),'split_reasons':[]}
            if span!=0:
                audit.need('GROUP_READOUT_SPLIT_REQUIRES_EVIDENCE','Readout is split; requires capability/conflict-bound reason',group_id=gid)
            common_start=min(r['t_start_us'] for r in records)
            if common_start>earliest_common+EPS:
                # A later common slot must have a real shared resource blocker;
                # an arbitrary delay is not an optimization proof.
                occupied=set().union(*(set(by_id[key]['resources']) for key in ids))
                blockers=[a for a in actions if a['id'] not in ids and occupied.intersection(a['resources']) and a['t_end_us']>earliest_common and a['t_start_us']<common_start]
                if not blockers: audit.fail('UNJUSTIFIED_COMMON_WAIT','All members were ready earlier and no declared readout resource blocks that window',group_id=gid)
                item['common_window_blockers']=[a['id'] for a in blockers]
            metrics.append(item)
        elif purpose=='patch_initialization_transport':
            moved=set(); ends={}; intervals=[]
            for member,atom in zip(members,atoms):
                prep=min(by_id[key]['t_start_us'] for ref in member['prepare_before_op_ids'] for key in source_map[ref] if by_id[key]['kind']=='reset')
                movements=[a for a in actions if a['kind']=='move' and atom in a['atoms'] and a['t_end_us']<=prep+EPS]
                real=[a for a in movements if any(t['atom_id']==atom and math.dist(t['from_um'],t['to_um'])>EPS for t in a['payload']['trajectories'])]
                if not real: audit.fail('INITIALIZATION_TRANSPORT_OMITTED','Initialization member has no actual movement before its preparation',group_id=gid,resource=atom)
                else: moved.add(atom); ends[atom]=max(a['t_end_us'] for a in real); intervals.extend((a['t_start_us'],a['t_end_us']) for a in real)
            full=[a for a in actions if a['kind']=='move' and a['payload'].get('group_id')==gid and set(atoms)<=set(a['atoms'])]
            if not full: audit.need('INITIALIZATION_GROUP_SPLIT','No common full-patch movement; split batches require physical-constraint evidence',group_id=gid)
            metrics.append({'group_id':gid,'purpose':purpose,'member_count':len(members),'moved_member_count':len(moved),'transport_start_us':min((t[0] for t in intervals),default=None),'transport_end_us':max((t[1] for t in intervals),default=None),'completion_span_us':_span(list(ends.values())),'transport_batch_count':sum(a['kind']=='pickup' and a['payload'].get('group_id')==gid for a in actions),'motion_segment_count':len(set(intervals)),'full_patch_move_ids':[a['id'] for a in full]})
    audit.metrics['groups']=metrics
    audit.metrics['cycle_duration_us']=max((a['t_end_us'] for a in actions),default=0.)-min((a['t_start_us'] for a in actions),default=0.)
    return metrics


def check_readout_capacity(audit,plan,device,geometry):
    profile=device['grouped_profile']['readout']
    if profile['model']!='per_site_parallel' or profile['resource_scope']!='instantiated_bank_and_site':
        audit.need('READOUT_PROFILE_UNSUPPORTED','Unknown group readout model'); return
    entries=[a for a in plan['actions'] if a['kind']=='measure']
    banks=defaultdict(list)
    for action in entries:
        banks[action['payload']['bank_id']].append(action)
        if action['payload']['basis']!=profile['basis']: audit.fail('READOUT_BASIS','Readout basis unsupported',action_id=action['id'])
    for bank,records in banks.items():
        capacity=profile['bank_capacity']
        if bank=='rigid-mz' and device.get('rigid_readout',{}).get('schema_version') in {'rigid-readout-profile/0.2','rigid-readout-profile/0.3'}:
            capacity=device['rigid_readout']['max_parallel_readouts']
        events=sorted([(a['t_start_us'],1,a['id']) for a in records]+[(a['t_end_us'],-1,a['id']) for a in records])
        live=set()
        for now,delta,aid in events:
            if delta<0: live.discard(aid)
            else:
                live.add(aid)
                if capacity is not None and len(live)>capacity: audit.fail('READOUT_CAPACITY_EXCEEDED','Simultaneous readouts exceed bank capacity',resource=bank,action_id=aid,time_us=now)
    for i,left in enumerate(entries):
        for right in entries[i+1:]:
            if max(left['t_start_us'],right['t_start_us'])>=min(left['t_end_us'],right['t_end_us']): continue
            a=geometry['snapshots'][(left['id'],'before')][left['atoms'][0]]['position_um']
            b=geometry['snapshots'][(right['id'],'before')][right['atoms'][0]]['position_um']
            same_slot=left['payload']['site_id']==right['payload']['site_id'] and left['payload']['bank_id']==right['payload']['bank_id']
            if math.dist(a,b)<=device['geometry']['distance_tolerance_um'] or same_slot:
                audit.fail('READOUT_SITE_CONFLICT','Concurrent readouts share a physical site, regardless of bank labels',action_id=right['id'],resource=left['id'])

"""Full physical semantics with shared transport/CZ actions (T404 contract)."""
from .checker import EPS


def check_strategy_source(audit,physical,plan,ops):
    by_id={a['id']:a for a in plan['actions']}; source_map=plan['source_map']
    atoms={a['atom_id']:a.get('site_id', a['qubit_id']) for a in plan['initial_state']['atoms']}
    bindings_at = {}
    commits = sorted([a for a in plan['actions'] if a['kind']=='rebind'], key=lambda a:a['t_end_us'])
    binding = dict(atoms); cursor = 0
    for action in sorted(plan['actions'], key=lambda a:a['t_start_us']):
        while cursor < len(commits) and commits[cursor]['t_end_us'] <= action['t_start_us']:
            binding.update({b['atom_id']:b['to_site_id'] for b in commits[cursor]['payload']['site_bindings']})
            cursor += 1
        bindings_at[action['id']] = dict(binding) if commits else atoms
    qubits={q['id'] for q in physical['qubits']}
    if not qubits<=set(atoms.values()): audit.fail('STRATEGY_QUBIT_COVERAGE','Strategy qubit binding is incomplete')
    seen=set(); used=set(); ends={}
    for op in ops:
        sid=op['id']; seen.add(sid); ids=source_map.get(sid,[])
        if not ids or len(ids)!=len(set(ids)) or any(key not in by_id for key in ids):
            audit.fail('STRATEGY_SOURCE_OMITTED','Source map omits/repeats an operation implementation',source_id=sid); continue
        semantic=[]
        for aid in ids:
            action=by_id[aid]; payload=action['payload']; used.add(aid)
            sources=payload.get('physical_op_ids',[payload.get('physical_op_id')])
            if sid not in sources or sid not in action['source_ids']:
                audit.fail('STRATEGY_SOURCE_BINDING','Action lacks its mapped source identity',action_id=aid,source_id=sid)
            if not set(op['source_ids'])<=set(action['source_ids']): audit.fail('STRATEGY_SOURCE_PROVENANCE','Original source provenance is incomplete',action_id=aid,source_id=sid)
            if action['kind'] in ('pickup','move','drop'):
                if payload.get('writes'): audit.fail('TRANSPORT_WRITES_RESULT','Transport cannot write measurement results',action_id=aid)
                continue
            if action['kind']=='wait' and op['kind']!='wait': continue
            live_atoms = bindings_at[aid]
            if action['kind']=='rebind':
                dest = op['params'].get('destination_indices', [])
                expected_binding = {q:op['qubits'][dest[i]] for i,q in enumerate(op['qubits'])} if len(dest)==len(op['qubits']) else {}
                actual_binding = {b['from_site_id']:b['to_site_id'] for b in payload.get('site_bindings', [])}
                if (op['kind']!='permute' or actual_binding != expected_binding or
                        any(live_atoms[b['atom_id']] != b['from_site_id'] for b in payload.get('site_bindings', [])) or
                        payload.get('transport_action_ids') != [i for i in ids if by_id[i]['kind'] in ('pickup','move','drop')]):
                    audit.fail('TRANSPORT_PERMUTATION_CHANGED', 'Transport/binding must implement the exact source site permutation', action_id=aid, source_id=sid)
                semantic.append((action, ('permute', None, op['qubits'])))
                continue
            if action['kind']=='gate' and payload['name']=='CZ' and 'pair_sources' in payload:
                matched=[pair for pair in payload['pair_sources'] if pair['physical_op_id']==sid]
                if len(matched)!=1:
                    audit.fail('SHARED_CZ_SOURCE','Shared pulse must bind exactly one pair to each mapped source',action_id=aid,source_id=sid); continue
                pair=matched[0]
                bound=[live_atoms[key] for key in pair['atoms']]
                if pair['qubits']!=op['qubits'] or sorted(bound)!=sorted(op['qubits']):
                    audit.fail('SHARED_CZ_DIRECTION','Pulse pair source has wrong qubits/direction',action_id=aid,source_id=sid)
                semantic.append((action,('gate','CZ',sorted(bound))))
            else:
                bound=[live_atoms[key] for key in action['atoms']]
                name=payload.get('name') if action['kind']=='gate' else None
                if name=='CZ': bound=sorted(bound)
                semantic.append((action,(action['kind'],name,bound)))
            if action.get('condition')!=op.get('condition'):
                audit.fail('STRATEGY_CONDITION_CHANGED','Lowering changed a source condition',action_id=aid,source_id=sid)
            if not set(op['reads'])<=set(payload.get('reads',[])):
                audit.fail('STRATEGY_READS_CHANGED','Source result dependency was dropped',action_id=aid,source_id=sid)
            if action['kind']=='measure':
                if payload.get('writes')!=op['writes'] or op['writes']!=[payload.get('result_id')] or payload.get('basis')!=op['params'].get('basis'):
                    audit.fail('STRATEGY_MEASUREMENT_CHANGED','Result namespace or basis changed',action_id=aid,source_id=sid)
            if action['kind']=='classical' and (payload.get('writes')!=op['writes'] or payload.get('reads')!=op['reads'] or payload.get('operation')!=op['params'].get('operation')):
                audit.fail('STRATEGY_CLASSICAL_CHANGED','Classical operation or complete result input/output mapping changed',action_id=aid,source_id=sid)
            if op['kind']=='gate' and op['params']['name'] not in ('CX','CZ'):
                for key,value in op['params'].items():
                    if key!='name' and payload.get('params',{}).get(key)!=value: audit.fail('STRATEGY_GATE_PARAMETER','Gate parameter was dropped or changed',action_id=aid,source_id=sid)
        semantic.sort(key=lambda item:(item[0]['t_start_us'],item[0]['t_end_us'],item[0]['id']))
        if op['kind']=='gate':
            name=op['params']['name']; q=op['qubits']
            expected=[('gate','H',[q[1]]),('gate','CZ',sorted(q)),('gate','H',[q[1]])] if name=='CX' else [('gate',name,sorted(q) if name=='CZ' else q)]
        else: expected=[(op['kind'],None,op['qubits'])]
        actual=[signature for action,signature in semantic]
        if actual!=expected: audit.fail('STRATEGY_LOWERING_SEMANTICS',f'Expected {expected}, got {actual}',source_id=sid)
        if not semantic: continue
        start=min(by_id[i]['t_start_us'] for i in ids) if op['kind']=='permute' else min(a['t_start_us'] for a,s in semantic); end=max(a['t_end_us'] for a,s in semantic)
        for prior,later in zip(semantic,semantic[1:]):
            if prior[0]['t_end_us']>later[0]['t_start_us']+EPS: audit.fail('STRATEGY_LOWERING_ORDER','Sequential decomposition overlaps',source_id=sid)
        for dep in op['after']:
            if dep not in ends or ends[dep]>start+EPS: audit.fail('STRATEGY_PHYSICAL_DEPENDENCY','Physical dependency is not complete before its consumer',source_id=sid,resource=dep)
        ends[sid]=end
    if set(source_map)!=seen: audit.fail('STRATEGY_SOURCE_MAP_SET','Source map does not equal the complete physical operation set')
    if used!=set(by_id): audit.fail('STRATEGY_EXTRA_ACTIONS','Some actions are not covered by any physical source',action_ids=sorted(set(by_id)-used))
    for action in plan['actions']:
        p=action['payload']
        if action['kind']=='gate' and p.get('name')=='CZ' and 'pair_sources' in p:
            actual={tuple(sorted(pair)) for pair in p['pairs']}
            bound={tuple(sorted(pair['atoms'])) for pair in p['pair_sources']}
            if actual!=bound or len(p['pair_sources'])!=len(actual): audit.fail('SHARED_CZ_PAIR_COVERAGE','Each actual CZ pair must have one physical source',action_id=action['id'])
    audit.metrics['physical_operation_count']=len(ops)

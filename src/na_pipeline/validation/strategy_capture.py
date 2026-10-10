"""Independent AOD Cartesian capture closure at every explicit pickup pulse."""
from collections import defaultdict
from copy import deepcopy
from itertools import product

from .checker import EPS


def transfer_records(action):
    payload=action['payload']
    if 'bindings' in payload:
        return [{**payload,**record} for record in payload['bindings']]
    if len(action['atoms'])!=1: raise ValueError('batch pickup/drop requires explicit per-atom transfers')
    return [{**payload,'atom_id':action['atoms'][0]}]


def capture_closure(audit,plan,device=None):
    initial={a['atom_id']:a for a in plan['initial_state']['atoms']}
    tolerance=device['geometry']['distance_tolerance_um'] if device is not None else EPS
    boundaries=sorted({a['t_start_us'] for a in plan['actions'] if a['kind']=='pickup'})
    movements=defaultdict(list); transfers=[]; pickups=defaultdict(list)
    for action in plan['actions']:
        if action['kind']=='move':
            for tr in action['payload']['trajectories']: movements[tr['atom_id']].append((action,tr))
        elif action['kind'] in ('pickup','drop'):
            records=transfer_records(action)
            if {r['atom_id'] for r in records}!=set(action['atoms']) or len(records)!=len(action['atoms']):
                audit.fail('TRANSFER_MEMBER_COVERAGE','Batch transfer must cover each action atom exactly once',action_id=action['id'])
            transfers.append((action,records))
            if action['kind']=='pickup':
                for r in records: pickups[(action['t_start_us'],r['aod_group'])].append((action,r))
    for values in movements.values(): values.sort(key=lambda item:item[0]['t_start_us'])
    transfers.sort(key=lambda item:item[0]['t_end_us'])
    def axis_state(now, before_end=False):
        axes=defaultdict(lambda:{'rows':{},'columns':{}})
        for field,axis,idkey,coord in (('aod_rows','rows','row_id','y_um'),('aod_columns','columns','column_id','x_um')):
            for line in plan['initial_state'][field]:
                group=line['aod_group']; identity=line[idkey]
                if identity in axes[group][axis]: raise ValueError('duplicate explicit initial AOD line')
                axes[group][axis][identity]=line[coord]
        carriers={key:{k:a[k] for k in ('carrier','aod_group','row_id','column_id')} for key,a in initial.items()}
        for aid,a in initial.items():
            if a['carrier']=='AOD' and (a['row_id'] not in axes[a['aod_group']]['rows'] or a['column_id'] not in axes[a['aod_group']]['columns']):
                raise ValueError('initial AOD resident has no explicit axis inventory')
        events=[(action,records) for action,records in transfers]
        events.extend((action,action['payload']['trajectories']) for action in plan['actions'] if action['kind']=='move')
        for action,records in sorted(events,key=lambda pair:pair[0]['t_end_us']):
            if action['t_end_us']>now: break
            if action['kind']=='move':
                group=action['payload']['aod_group']
                for tr in records:
                    for axis,key,coordinate in (('rows','row_id',1),('columns','column_id',0)):
                        if tr[key] in axes[group][axis]: axes[group][axis][tr[key]]=tr['to_um'][coordinate]
                continue
            if before_end and action['t_end_us']==now: continue
            for record in records:
                group=record['aod_group']; atom=carriers[record['atom_id']]
                if action['kind']=='pickup':
                    atom.update(carrier='AOD',aod_group=group,row_id=record['row_id'],column_id=record['column_id'])
                    axes[group]['rows'][record['row_id']]=record['position_um'][1]
                    axes[group]['columns'][record['column_id']]=record['position_um'][0]
                else:
                    atom.update(carrier='SLM',row_id=None,column_id=None)
                    for axis,key in (('rows','row_id'),('columns','column_id')):
                        if not any(a['carrier']=='AOD' and a['aod_group']==group and a[key]==record[key] for a in carriers.values()): axes[group][axis].pop(record[key],None)
        # Movement does not activate/deactivate axes; all still-active line
        # coordinates follow the most recent explicit resident trajectory.
        updates=sorted(((action,tr) for values in movements.values() for action,tr in values if action['t_start_us']<now<action['t_end_us']),key=lambda pair:pair[0]['t_start_us'])
        for action,tr in updates:
            group=action['payload']['aod_group']; fraction=min(1.,(now-action['t_start_us'])/(action['t_end_us']-action['t_start_us']))
            for axis,key,coordinate in (('rows','row_id',1),('columns','column_id',0)):
                if tr[key] in axes[group][axis]: axes[group][axis][tr[key]]=tr['from_um'][coordinate]+fraction*(tr['to_um'][coordinate]-tr['from_um'][coordinate])
        return axes
    def live(now):
        atoms=deepcopy(initial)
        for atom_id,values in movements.items():
            for action,tr in values:
                if action['t_start_us']>now: break
                fraction=min(1.,(now-action['t_start_us'])/(action['t_end_us']-action['t_start_us']))
                atoms[atom_id]['position_um']=[x+fraction*(y-x) for x,y in zip(tr['from_um'],tr['to_um'])]
        for action,records in transfers:
            if action['t_end_us']>now: break
            for record in records:
                atom=atoms[record['atom_id']]
                atom.update(carrier='AOD' if action['kind']=='pickup' else 'SLM',trap_id=record['to_trap_id'],aod_group=record['aod_group'],row_id=record['row_id'] if action['kind']=='pickup' else None,column_id=record['column_id'] if action['kind']=='pickup' else None)
        return atoms
    evidence=[]
    for (now,group),batch in sorted(pickups.items()):
        atoms=live(now); requested={r['atom_id'] for a,r in batch}
        all_axes=axis_state(now); rows=dict(all_axes[group]['rows']); cols=dict(all_axes[group]['columns'])
        for action,record in batch:
            atom=atoms[record['atom_id']]
            if atom['carrier']!='SLM' or atom['trap_id']!=record['from_trap_id']:
                audit.fail('CAPTURE_SOURCE_BINDING','Pickup is not from this current SLM carrier/trap',action_id=action['id'],resource=record['atom_id'])
            for lines,key,coordinate in ((rows,'row_id',1),(cols,'column_id',0)):
                line=record[key]; position=atom['position_um'][coordinate]
                if line in lines and abs(lines[line]-position)>EPS:
                    audit.fail('CAPTURE_LINE_ALIGNMENT','Shared line cannot capture two different coordinates',action_id=action['id'],resource=f'{group}/{line}')
                lines[line]=position
        captured={aid for aid,a in atoms.items() if a['carrier']=='SLM' and any(abs(a['position_um'][0]-x)<=tolerance for x in cols.values()) and any(abs(a['position_um'][1]-y)<=tolerance for y in rows.values())}
        if captured!=requested:
            audit.fail('CAPTURE_CARTESIAN_CLOSURE','Active row/column intersections capture a different set of SLM atoms',time_us=now,aod_group=group,omitted_atoms=sorted(captured-requested),unreachable_atoms=sorted(requested-captured))
        evidence.append({'time_us':now,'aod_group':group,'requested_count':len(requested),'captured_count':len(captured),'action_ids':sorted({a['id'] for a,r in batch})})
    # Every active Cartesian intersection is a trap, even if no atom occupies
    # that intersection. Check its swept path against all other carriers.
    from .geometry import _collision
    times=sorted({a[key] for a in plan['actions'] for key in ('t_start_us','t_end_us')})
    segments=0
    for ta,tb in zip(times,times[1:]):
        active_groups={a['payload']['aod_group'] for a in plan['actions'] if a['kind']=='move' and a['t_start_us']<=ta and a['t_end_us']>=tb}
        if not active_groups: continue
        before,after=live(ta),live(tb)
        axes_before,axes_after=axis_state(ta),axis_state(tb,before_end=True)
        for group in active_groups:
            rows={key:(value,axes_after[group]['rows'][key]) for key,value in axes_before[group]['rows'].items()}
            cols={key:(value,axes_after[group]['columns'][key]) for key,value in axes_before[group]['columns'].items()}
            for name,lines in (('rows',rows),('columns',cols)):
                ordered=sorted(lines,key=lambda key:lines[key][0])
                if any(lines[b][0]-lines[a][0]<=EPS or lines[b][1]-lines[a][1]<=EPS for a,b in zip(ordered,ordered[1:])):
                    audit.fail('ACTIVE_AXIS_ORDER','Full active axis inventory, including empty lines, crosses or merges',aod_group=group,axis=name,time_interval_us=[ta,tb])
            for row,col in product(rows,cols):
                begin=[cols[col][0],rows[row][0]]; end=[cols[col][1],rows[row][1]]
                for aid,atom in before.items():
                    if atom['carrier']=='AOD' and atom['aod_group']==group and atom['row_id']==row and atom['column_id']==col: continue
                    if _collision(begin,end,atom['position_um'],after[aid]['position_um']):
                        audit.fail('CARTESIAN_SWEEP_CAPTURE','An active row/column intersection crosses another carrier during motion',aod_group=group,time_interval_us=[ta,tb],resource=aid,row_id=row,column_id=col)
                segments+=1
    audit.metrics['pickup_capture_batches']=evidence
    audit.metrics['cartesian_intersection_segments_checked']=segments
    audit.metrics['full_active_axes_checked']=True
    return evidence

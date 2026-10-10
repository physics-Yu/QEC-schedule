"""Read-only parallel timeline and constrained critical-path accounting."""
from pathlib import Path
from collections import Counter,defaultdict
import argparse,gzip,hashlib,json
from audit_factory_time import category


def read(p):
    b=p.read_bytes();return json.loads(gzip.decompress(b) if p.suffix=='.gz' else b)


def audit(folder):
    summary=read(folder/'summary.json');rows=[];inputs={};kinds=Counter();critical=Counter();counts=Counter()
    for phase in summary['phases']:
        path=folder/phase['artifact'];raw=read(path);inputs[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
        plan=raw['physical_plan'];actions=raw['atom_program']['actions'];composition=plan['module_composition']
        instances=composition['instances'];source={o['id']:o for d in plan['physical_dags'] for o in d['nodes']}
        finish={};ancestors={};cause={};weights={};categories={};transfers=Counter();cuts=defaultdict(Counter)
        for a in actions:
            kind=a['payload'].get('name') if a['kind']=='gate' else a['kind'];counts[kind]+=1
            if kind=='CZ':counts['CZ_pairs']+=len(a['payload']['pairs']);counts['CZ_single_pair_pulses']+=int(len(a['payload']['pairs'])==1)
            cuts[a['t_start_us']][kind]+=1;cuts[a['t_end_us']][kind]-=1
            if a['kind'] in ('pickup','drop'):transfers[a['id'].rsplit('/action:',1)[0]]+=1
        source_only_finish={};retimed200={};active=Counter();cursor=phase['start_us'];union=Counter()
        for t,delta in sorted(cuts.items()):
            label='+'.join(sorted(k for k,v in active.items() if v)) or 'idle_or_result_latency'
            union[label]+=t-cursor;active.update(delta);cursor=t
        union['idle_or_result_latency']+=phase['end_us']-cursor
        for node,m in zip(composition['dependency_graph']['modules'],instances):
            mid=node['id'];deps={c['module_id'] for c in m['schedule_constraints']}
            duration=m['end_us']-m['start_us'];weights[mid]=duration
            pred=max(deps,key=lambda p:finish[p]) if deps else None
            finish[mid]=(finish[pred] if pred else 0.)+duration;cause[mid]=pred
            assert abs(finish[mid]-m['end_us'])<1e-7,(phase['id'],mid)
            cats={category(source[s]) for s in m['source_ids']};categories[mid]=next(iter(cats)) if len(cats)==1 else 'mixed:'+'+'.join(sorted(cats))
            source_only_finish[mid]=max((source_only_finish[d] for d in node['dependencies']),default=0.)+duration
            retimed200[mid]=max((retimed200[d] for d in deps),default=0.)+duration+100*transfers[m['instance_id']]
        leaf=max(finish,key=finish.get);chain=[];cost=Counter()
        while leaf is not None:chain.append(leaf);cost[categories[leaf]]+=weights[leaf];leaf=cause[leaf]
        duration=phase['end_us']-phase['start_us'];assert abs(sum(cost.values())-duration)<1e-7
        assert abs(sum(union.values())-duration)<1e-7
        total_work=sum(weights.values());counts['module_instances']+=len(instances);counts['physical_operations']+=len(source)
        row={'stage':phase['stage_id'],'epoch':phase['epoch'],'duration_us':duration,
             'serial_module_sum_us':total_work,'module_overlap_savings_us':total_work-duration,
             'critical_path_module_ids':list(reversed(chain)),'critical_path_categories_us':dict(cost),
             'action_kind_union_us':dict(union),'source_dependency_only_lower_bound_us':max(source_only_finish.values()),
             'fixed_schedule_200us_counterfactual':max(retimed200.values())}
        rows.append(row)
        if not phase['stage_id'].startswith('consume'):
            critical.update(cost);kinds.update(union)
    factory=[r for r in rows if not r['stage'].startswith('consume')]
    return {'schema_version':'FrameCnotTimingAudit/0.2','total_us':summary['duration_us'],
            'factory_through_ready_us':sum(r['duration_us'] for r in factory) if folder.name in ('T','TDG') else None,
            'non_consumption_phase_total_us':sum(r['duration_us'] for r in factory),
            'counts_full_protocol':dict(counts),'count_scope':'planned actions; conditionally skipped 1Q slots remain reserved; CZ is unconditional',
            'factory_critical_path_categories_us':dict(critical),'factory_action_kind_union_us':dict(kinds),
            'factory_module_overlap_savings_us':sum(r['module_overlap_savings_us'] for r in factory),
            'factory_fixed_schedule_200us_counterfactual':sum(r['fixed_schedule_200us_counterfactual'] for r in factory),
            'counterfactual_scope':'same new module graph, resource reservations, routes and branches; not recompiled or optimal; compare separately from actual100us',
            'critical_path_scope':'source plus declared resource plus conservative geometry-scene dependencies; not an unrestricted lower bound',
            'stages':rows,'input_sha256':inputs,'compiler_invoked':False,'quantum_state_simulated':False,'hardware_executed':False}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--gallery',required=True);a=p.parse_args();base=Path(a.gallery)
    for name in ('T','TDG','REJECT_RETRY'):
        result=audit(base/'protocols'/name);(base/('timing-'+name+'.json')).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k not in ('stages','input_sha256')},ensure_ascii=False))

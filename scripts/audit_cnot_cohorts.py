"""Block delivery if aligned logical CNOTs or magic readouts fragment."""
from pathlib import Path
from collections import defaultdict
import argparse,gzip,json,hashlib


def read(p):
    raw=p.read_bytes();return json.loads(gzip.decompress(raw) if p.suffix=='.gz' else raw)


def inspect(plan,label):
    source={o['id']:o for d in plan['physical_dags'] for o in d['nodes']};groups=defaultdict(list)
    actions=plan['atom_program']['actions'];sites={a.get('site_id',a['qubit_id']):a for a in plan['atom_program']['initial_state']['atoms']}
    for o in source.values():
        m=o.get('metadata',{}).get('logical_cohort')
        if m:groups[(m['local_id'],*(q.rsplit('/',1)[0] for q in o['qubits']))].append(o)
    rows=[]
    for key,ops in groups.items():
        assert len(ops)==9,(label,key,'COHORT_SOURCE_LOST')
        ids={o['id'] for o in ops};vectors={tuple(round(sites[o['qubits'][1]]['position_um'][i]-sites[o['qubits'][0]]['position_um'][i],8) for i in (0,1)) for o in ops}
        pulses=[a for a in actions if a['payload'].get('name')=='CZ' and any(s['physical_op_id'] in ids for s in a['payload'].get('pair_sources',[]))]
        covered=[s['physical_op_id'] for a in pulses for s in a['payload']['pair_sources'] if s['physical_op_id'] in ids]
        assert sorted(covered)==sorted(ids),(label,key,'COHORT_CZ_SOURCE_COVERAGE')
        aligned=len(vectors)==1
        if aligned:assert len(pulses)==1,(label,key,'ALIGNED_CNOT_FRAGMENTED',len(pulses))
        h_intervals=set()
        for sid in ids:
            pulse=next(a for a in pulses if any(s['physical_op_id']==sid for s in a['payload']['pair_sources']))
            pair=next(s for s in pulse['payload']['pair_sources'] if s['physical_op_id']==sid)
            hs=[a for a in actions if a['payload'].get('name')=='H' and sid in a['payload'].get('physical_op_ids',[])]
            assert len(hs)==2 and all(pair['atoms'][1] in a['atoms'] for a in hs),(label,key,'CNOT_PHYSICAL_TARGET_H_LOST')
            hs.sort(key=lambda a:a['t_start_us'])
            assert hs[0]['t_end_us']<=pulse['t_start_us'] and hs[1]['t_start_us']>=pulse['t_end_us']
            h_intervals.update((a['t_start_us'],a['t_end_us']) for a in hs)
        if aligned:assert len(h_intervals)==2,(label,key,'CNOT_H_LAYERS_FRAGMENTED')
        rows.append({'cohort':list(key),'source_pairs':9,'aligned_translation':aligned,'CZ_pulses':len(pulses),
                     'physical_target_H_operations':18,'physical_H_layers':len(h_intervals)})
    reads=defaultdict(list)
    for o in source.values():
        tail=o['id'].rsplit('/',1)[-1]
        for stem in ('magic_read_read_d','consume_output_read_d'):
            if tail.startswith(stem):reads[stem].append(o['id'])
    waves=[]
    for stem,ids in reads.items():
        matches=[a for a in actions if a['kind']=='measure' and set(a['payload']['physical_op_ids'])&set(ids)]
        assert len(matches)==len(ids)==9,(label,stem,'MAGIC_READ_SOURCE_COVERAGE')
        count=len({a['t_start_us'] for a in matches})
        assert count==1,(label,stem,'MAGIC_READOUT_FRAGMENTED',count)
        waves.append({'source_prefix':stem,'atoms':9,'waves':count})
    return {'label':label,'cohorts':rows,'magic_readouts':waves}


def audit(base):
    base=Path(base);rows=[];inputs={}
    for p in sorted(base.glob('*/physical-plan.json')):
        rows.append(inspect(read(p),p.parent.name));inputs[p.relative_to(base).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    for name in ('T','TDG','REJECT_RETRY'):
        folder=base/'protocols'/name
        for phase in read(folder/'summary.json')['phases']:
            p=folder/phase['artifact'];rows.append(inspect(read(p)['physical_plan'],name+'/'+phase['id']));inputs[p.relative_to(base).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted((base/'frame-continuations').glob('*/frame-session.json.gz')):
        data=read(p);inputs[p.relative_to(base).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
        for i,e in enumerate(data['entries']):rows.append(inspect(e['physical_plan'],p.parent.name+'/'+str(i)))
    result={'schema_version':'LogicalCnotCohortAcceptance/0.1','passed':True,'plans':len(rows),
            'cohorts':sum(len(r['cohorts']) for r in rows),'magic_readouts':sum(len(r['magic_readouts']) for r in rows),
            'scope':'declared nine-pair CNOTs with aligned entry geometry; source coverage and one-pulse/one-readout-wave checks; not arbitrary layout optimality',
            'rows':rows,'input_sha256':inputs}
    (base/'cohort-acceptance.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();r=audit(a.out)
    print(json.dumps({k:v for k,v in r.items() if k not in ('rows','input_sha256')}))

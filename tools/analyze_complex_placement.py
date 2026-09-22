"""Report all measured candidates, including surrogate/execution disagreement."""
import json
from collections import Counter
from pathlib import Path


def analyze(folder):
    folder=Path(folder)
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    report=read(folder/'comparison.json')
    search=read(folder/'search'/'search.json')
    rows=[]
    for trial in search['trials']:
        result=read(folder/'search'/f"trial-{trial['index']:04d}"/'result.json')
        metrics=result.get('metrics',{})
        total=trial['evaluation']['total_time_us']
        logical=metrics.get('logical_completion_elapsed_us')
        decisions=result.get('execution',{}).get('decision_log',[])
        phases={label:sum(d['duration_us'] for d in decisions if d['kind']==label)
                for label in ('Stage to EZ','CZ','Return to initial SLM','terminal')}
        rows.append(dict(index=trial['index'],origin=trial['origin'],score=trial['proposal_score'],
                         valid=trial['evaluation']['valid'],total_us=total,logical_us=logical,
                         after_last_gate_us=total-logical if total is not None and logical is not None else None,
                         loads=metrics.get('aod_load_count'),distance_um=metrics.get('total_atom_distance_um'),
                         phase_duration_us=phases,
                         terminal_transport_batches=sum(d['kind']=='Return to initial SLM' for d in decisions),
                         wall_seconds=trial['wall_seconds'],failure=trial['evaluation']['failure']))
    pulses={}
    for name in ('baseline','optimized'):
        data=read(folder/(name+'.json'))
        sizes=Counter(len(op['gate_ids']) for op in data['operations'] if op['kind']=='entangling_pulse')
        pulses[name]=dict(sorted(sizes.items()))
    baseline=rows[0]; valid=[r for r in rows if r['valid']]
    selected=rows[report['selected']['index']]
    early=min(valid,key=lambda r:r['logical_us'])
    return dict(case=folder.name,atoms=report['input']['atom_count'],gates=len(report['input']['gates']),
                cz=sum(g['gate_type']=='CZ' for g in report['input']['gates']),
                candidate_count=len(rows),valid_count=len(valid),baseline=baseline,selected=selected,
                improvement_percent=report['improvement_percent'],wall_seconds=report['wall_seconds'],
                earliest_last_gate=early,
                last_gate_improvement_percent=100*(baseline['logical_us']-early['logical_us'])/baseline['logical_us'],
                better_distance_but_slower=[r['index'] for r in valid
                    if r['score']<baseline['score'] and r['total_us']>baseline['total_us']],
                cz_pulse_histogram=pulses,rows=rows)


if __name__=='__main__':
    output=Path('artifacts/free-placement')
    reports=[analyze(output/case) for case in ('partners-12','grid-16')]
    (output/'complex-summary.json').write_text(json.dumps(reports,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(reports,indent=2))

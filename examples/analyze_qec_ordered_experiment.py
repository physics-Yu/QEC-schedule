"""Audit exported matched runs; derive cost breakdown without executing policy."""
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))


def analyze(directory):
    directory=Path(directory)
    report=json.loads((directory/'comparison.json').read_text(encoding='utf-8'))
    summary={'same_initial_state':report['same_initial_state'],'strategies':{}}
    stage={g['gate_id']:g['stage'] for g in report['input'].get('qec_protocol',{}).get('stages',[])}
    for r in report['results']:
        folder=directory/r['strategy'];plans=json.loads((folder/'plans.json').read_text(encoding='utf-8'))
        recording=json.loads((folder/'recording.json').read_text(encoding='utf-8'))
        times=defaultdict(float);counts=Counter();transverse=[]
        for op in recording['operations']:
            times[op['kind']]+=op['end']-op['start'];counts[op['kind']]+=1
            if op['kind']=='entangling_pulse' and any(stage.get(g)=='logical-cnot' for g in op['gate_ids']):
                transverse.append(op['gate_ids'])
        # Read committed plan geometry directly, independently of the planner.
        violations=[];straight_stops=[];moves=0
        for p in plans:
            before=p['initial_aod_configuration'];previous=None
            for op in p['operations']:
                if op['operation_type']!='aod_move':previous=None;continue
                after=op['target_configuration'];moves+=1
                axis='x_um' if before['y_um']==after['y_um'] else 'y_um' if before['x_um']==after['x_um'] else None
                if axis is None:violations.append((p['id'],op['id']))
                if previous and previous[1]==axis and axis is not None:
                    a=previous[0][axis];b=before[axis];c=after[axis]
                    if all((y-x)*(z-y)>=-1e-10 for x,y,z in zip(a,b,c)):
                        straight_stops.append((p['id'],op['id']))
                previous=(before,axis);before=after
        atoms=recording['atom_statistics']['atoms']
        summary['strategies'][r['strategy']]={
            'status':r['status'],'total_time_us':r['metrics']['simulation_time_us'],
            'time_by_operation_us':dict(times),'operation_counts':dict(counts),'move_segments':moves,
            'nonorthogonal_moves':violations,'redundant_straight_stops':straight_stops,
            'logical_cnot_cz_batches':transverse,'cz_batch_sizes':r['cz_batch_sizes'],
            'total_atom_distance_um':sum(a['distance_um'] for a in atoms.values()),
            'atom_loads':sum(a['load_count'] for a in atoms.values()),
            'atom_offloads':sum(a['offload_count'] for a in atoms.values()),
            'solver_build_seconds':sum(l.get('build_seconds',0) for l in r.get('solver_log',[])),
            'solver_check_seconds':sum(m.get('solver_seconds',0) for l in r.get('solver_log',[]) for m in l.get('models',[])),
            'validation_passed':r['effects_once'] and r['terminal_verified'] and r['replay_equal'] and
                r['quantum']['verified_logical_ghz2'] and r['quantum']['measurement_protocol_complete']}
    (directory/'analysis.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');args=p.parse_args()
    print(json.dumps(analyze(args.directory),ensure_ascii=False,indent=2))

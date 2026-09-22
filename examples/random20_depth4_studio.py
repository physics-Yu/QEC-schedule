"""Reproducible 20-atom, depth-four circuit for the existing Demo editor.

Two random perfect CZ matchings connect all twenty atoms. The circuit is fixed
before placement search; seeds are never selected using compiler performance.
"""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import random
from urllib.request import Request, urlopen

from neutral_atom_app.visualization.studio_config import catalog
from neutral_atom_app.visualization.workbench import validate_input


def make_input(seed=20260921):
    rng=random.Random(seed);n=20
    def matching():
        order=list(range(n));rng.shuffle(order)
        return [tuple(sorted(order[i:i+2])) for i in range(0,n,2)]
    first=matching()
    for draw in range(10000):
        second=matching()
        if set(first)&set(second):continue
        reached={0}
        while True:
            more=reached|{q for pair in first+second if reached.intersection(pair) for q in pair}
            if more==reached:break
            reached=more
        if len(reached)==n:break
    else:raise RuntimeError('No connected random matching within generation budget')
    gates=[]
    def add(kind,targets,column):
        gates.append(dict(id=f'R{len(gates):03d}',gate_type=kind,
                          qubit_ids=[f'Q{q:03d}' for q in targets],parameters=[],column=column))
    for q in range(n):add('H',[q],0)
    for pair in first:add('CZ',pair,1)
    for q in range(n):add(rng.choice(['H','X','Y','Z','T']),[q],2)
    for pair in second:add('CZ',pair,3)
    cfg=catalog();value=deepcopy(cfg['workspace_defaults'])
    algorithm=next(a for a in cfg['algorithms'] if a['id']=='ordered_greedy')
    value.update(atom_count=n,layout='grid',seed=seed,aod_rows=8,aod_columns=8,
                 aod_row_offsets_um=list(range(0,80,10)),aod_column_offsets_um=list(range(0,80,10)),
                 gates=gates,compilation=dict(strategy='legacy',implementation='ordered_greedy',
                     **cfg['compilation_defaults'],**algorithm['defaults']))
    value['compilation']['compile_timeout_s']=180
    value['placement_search']=dict(proposal_pool=256,evaluations=16,workers=4,
                                   terminal_mode='stable',expand_storage=True)
    value=validate_input(value)
    # Independent layer/depth audit; do not equate four logical columns to four pulses.
    depth={f'Q{i:03d}':0 for i in range(n)}
    for column in range(4):
        layer=[g for g in value['gates'] if g['column']==column]
        wires=[q for g in layer for q in g['qubit_ids']]
        assert len(wires)==n and len(set(wires))==n
        for g in layer:
            d=1+max(depth[q] for q in g['qubit_ids'])
            for q in g['qubit_ids']:depth[q]=d
    assert set(depth.values())=={4} and len(gates)==60
    return value,dict(seed=seed,atoms=n,logical_depth=4,gate_count=len(gates),
        counts=dict(Counter(g['gate_type'] for g in gates)),matching_draws=draw+1,
        first_pairs=first,second_pairs=second,interaction_components=1,
        note='20 H; 10 random CZ; 20 random H/X/Y/Z/T; 10 new random CZ. Logical depth is not physical pulse depth.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--submit',help='Optional running Atom Studio base URL')
    args=parser.parse_args()
    value,description=make_input()
    config=Path('configs/workbench/random20_depth4.json');config.parent.mkdir(parents=True,exist_ok=True)
    config.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    folder=Path('artifacts/random20-depth4');folder.mkdir(parents=True,exist_ok=True)
    (folder/'circuit-audit.json').write_text(json.dumps(description,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(description),flush=True)
    if args.submit:
        url=args.submit.rstrip('/')+'/api/placement'
        request=Request(url,data=json.dumps(value).encode(),headers={'Content-Type':'application/json'})
        with urlopen(request,timeout=30) as response:job=json.load(response)
        job['base']=args.submit.rstrip('/')
        (folder/'job.json').write_text(json.dumps(job,indent=2),encoding='utf-8')
        print(json.dumps(job),flush=True)


if __name__=='__main__':main()

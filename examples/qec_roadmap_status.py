"""Explicit attempt ledger; failed stages cannot start a new unapproved attempt.

This helper has no approval command. Approval must be supplied by the user in
the conversation before a reviewed ledger update and any retry can happen.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path


def update(path,stage_id,event,*,evidence=(),failure=None):
    path=Path(path);data=json.loads(path.read_text(encoding='utf-8'))
    stage=next(s for s in data['stages'] if s['id']==stage_id)
    now=datetime.now(timezone.utc).isoformat()
    if event=='start':
        if stage['status']!='pending':raise ValueError('Only an untouched pending stage can start automatically; failed stages require explicit user approval')
        earlier=data['stages'][:data['stages'].index(stage)]
        if any(s['status']!='passed' for s in earlier):raise ValueError('All prior stages must pass before starting this stage')
        stage['attempts'].append({'number':1,'formal':True,'status':'running','started_at':now,'evidence':list(evidence)})
        stage['status']='running'
    else:
        if stage['status']!='running':raise ValueError('Only a running attempt may finish')
        attempt=stage['attempts'][-1]
        attempt['finished_at']=now;attempt['evidence'].extend(evidence)
        if event=='pass':stage['status']='passed';attempt['status']='passed'
        elif event=='fail':
            if not failure or not failure.get('facts'):raise ValueError('A failed attempt needs concrete observed facts')
            failure['approval']={'status':'pending','user_message':None}
            attempt['failure']=failure;attempt['status']='failed';stage['status']='awaiting_approval'
        else:raise ValueError('Unknown event')
    data['updated_at']=now
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    return data


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage');parser.add_argument('event',choices=('start','pass','fail'))
    parser.add_argument('--status',default='artifacts/qec-roadmap/status.json');parser.add_argument('--details')
    args=parser.parse_args();details=json.loads(Path(args.details).read_text(encoding='utf-8')) if args.details else {}
    print(json.dumps(update(args.status,args.stage,args.event,**details),ensure_ascii=False))

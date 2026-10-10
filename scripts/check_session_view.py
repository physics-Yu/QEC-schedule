"""Tamper probes against fixed R5 windows; source artifacts remain read-only."""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from viewer import canonical
from viewer.session import read,session_projection


def main():
    source=ROOT/'examples/scenarios/T505-dag-session-fixed-runtime'
    windows=[read(p)[0] for p in sorted(source.glob('window-*.json.gz'))]
    trace=read(source/'event-trace.json.gz')[0]
    before=canonical({'windows':windows,'trace':trace})
    projection,_=session_projection(windows,trace)
    assert projection['actions']==[a for w in windows for a in w['atom_program']['actions']]
    assert canonical({'windows':windows,'trace':trace})==before
    checks=[{'case':'original_actions_and_absolute_times_preserved','passed':True}]
    def reject(label,mutate,expected):
        w,t=deepcopy(windows),deepcopy(trace);mutate(w,t)
        try:session_projection(w,t)
        except ValueError as exc:
            if expected not in str(exc):raise
            checks.append({'case':label,'passed':True,'rejection':str(exc)})
        else:raise AssertionError('Tamper accepted: '+label)
    def time_edit(w,t):w[0]['atom_program']['actions'][0]['t_end_us']+=1
    reject('retiming_rejected',time_edit,'VIEW_SESSION_SUBMITTED_HASH_MISMATCH')
    def entry_edit(w,t):
        w[1]['atom_program']['initial_state']['atoms'][0]['position_um'][0]+=1
        t['submitted_plans'][1]['plan_hash']=canonical(w[1]['atom_program'])
    reject('forged_window_entry_rejected',entry_edit,'VIEW_SESSION_ENTRY_DISCONTINUITY')
    reject('missing_window_rejected',lambda w,t:w.pop(),'VIEW_SESSION_WINDOW_COVERAGE')
    def event_edit(w,t):t['events'][0]['payload']['params']={'basis':'X'}
    reject('event_payload_mismatch_rejected',event_edit,'VIEW_EVENT_PLAN_MISMATCH')
    def result_edit(w,t):next(iter(t['results'].values()))['origin']='sampled'
    reject('fake_origin_change_rejected',result_edit,'VIEW_RESULT_ORIGIN_OR_READY')
    out=ROOT/'scripts/outputs/T704/session-view-checks.json'
    report={'schema_version':'r7-session-view-checks/0.1','source':str(source),'source_sha256':before,'checks':checks,'passed':True,'scope':'display binding and tamper rejection, not physical qualification or browser rendering'}
    out.write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print(json.dumps({'report':str(out),'passed':True,'checks':len(checks)},ensure_ascii=False))


if __name__=='__main__':main()

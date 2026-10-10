"""Freeze all regression fixtures through the existing R7 dispatch entry."""
from pathlib import Path
from argparse import Namespace
import argparse,sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from server_pipeline_job import dispatch


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('spec',type=Path);a=p.parse_args()
    inputs=list((ROOT/'configs').rglob('*.json'))+list((ROOT/'tests').rglob('*.py'))
    inputs+=list((ROOT/'tests/fixtures').glob('*.json'))
    inputs+=[ROOT/n for n in (
        'examples/atom/t405/reuse_workload.py',
        'examples/atom/t405/resource-world-server-v1/world.json.gz',
        'examples/scenarios/T505-reject-then-accept.json',
        'knowledge/roles/R5/dag-scheduler-example.json',
        'knowledge/roles/R1/evidence/T103/full-shor-entry/patch-placement.json',
        'knowledge/roles/R6/evidence/T604/inputs.json.gz',
        'knowledge/roles/R6/hierarchical-minimal.json',
        'knowledge/roles/R6/evidence/T605/frontend-placement-inputs.json.gz',
        'scripts/outputs/T704/server/20261006T152602272401Z-r4-factory-first-stage-205/result/examples/atom/t405/factory-stage-v1/input.json.gz')]
    dispatch(Namespace(spec=a.spec,input=inputs))

"""Use the established persistent server entry and an explicit small input set."""
from pathlib import Path
from argparse import Namespace
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from server_pipeline_job import dispatch

if __name__=='__main__':
    extras=list((ROOT/'configs').rglob('*.json'))
    extras+=list((ROOT/'tests').rglob('*.py'))
    extras+=[ROOT/'tests/fixtures/basic-se-schedule.json']
    extras+=[ROOT/'viewer'/n for n in ('components.html','components.css','components.js','lab-renderer.js','motion-preview.js','resource-schedule.js')]
    dispatch(Namespace(spec=ROOT/'scripts/outputs/T704/basic-shor-spec.json',input=extras))

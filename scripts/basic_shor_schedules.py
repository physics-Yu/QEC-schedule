"""Extract only static batch choices from already compiled complete components."""
from pathlib import Path
import gzip,hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from na_pipeline.runtime.component_schedule import extract_schedule
from na_pipeline.runtime.pipeline import save_artifact


def import_schedules(source,directory):
    source=Path(source);directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    if not source.is_dir():raise ValueError('COMPONENT_SOURCE_MISSING')
    index={};files={};duplicates=0
    paths=sorted(source.glob('*/physical-plan.json'))
    paths+=sorted((source/'protocols').glob('*/*.json.gz'))
    for path in paths:
        if path.name.startswith('checkpoint'):continue
        raw=path.read_bytes();data=json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)
        plan=data.get('physical_plan') if path.suffix=='.gz' else data
        if plan is None:continue
        key,schedule=extract_schedule(plan)
        schedule['source_artifact']={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()}
        files[str(path.relative_to(source))]=schedule['source_artifact']['sha256']
        if key in index:duplicates+=1;continue
        index[key]=schedule
    if not index:raise ValueError('EMPTY_COMPILED_SCHEDULE_LIBRARY')
    save_artifact(directory/'index.json',index,immutable=True)
    save_artifact(directory/'import.json',{'source':str(source),'files':files,'unique_schedules':len(index),
        'duplicate_shapes':duplicates,'compiled_again':False,'runtime_state_imported':False})
    print(json.dumps({'imported_component_schedules':len(index),'duplicates':duplicates}),flush=True)
    return index

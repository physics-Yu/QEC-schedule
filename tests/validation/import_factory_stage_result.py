"""Import the R6 report emitted into R7's already exported supervisor stdout."""
import argparse,json
from pathlib import Path

root=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser();parser.add_argument('--stdout',required=True);parser.add_argument('--manifest',default='knowledge/roles/R6/evidence/T605/factory-stage-input-manifest.json');args=parser.parse_args()
path=Path(args.stdout).resolve();prefix='R6_VALIDATION_ARTIFACTS_JSON='
with path.open(encoding='utf-8') as f:lines=[line[len(prefix):] for line in f if line.startswith(prefix)]
if len(lines)!=1:raise ValueError('Expected exactly one complete R6 report line')
payload=json.loads(lines[0]);manifest=json.loads((root/args.manifest).read_bytes())
if payload['receipt']['input_byte_sha256']!={v['path']:v['byte_sha256'] for v in manifest['inputs'].values()}:raise ValueError('Result belongs to a different frozen source stage')
if payload['report']['scope']!='first_factory_initialize_in_205_world' or payload['report']['full_program_passed']:raise ValueError('Incorrect qualification scope')
out=(root/manifest.get('output_directory','knowledge/roles/R6/evidence/T605/factory-stage-validation-v1')).resolve()
if not out.is_relative_to((root/'knowledge/roles/R6/evidence/T605').resolve()):raise ValueError('Output must stay in R6 evidence')
out.mkdir(parents=True,exist_ok=True)
for name in ('report','receipt'):
    raw=(json.dumps(payload[name],ensure_ascii=False,indent=2)+'\n').encode('utf-8');target=out/(name+'.json')
    if target.exists() and target.read_bytes()!=raw:raise ValueError('Refusing to replace different frozen validation evidence')
    target.write_bytes(raw)
print(json.dumps({'passed':payload['report']['passed'],'failures':len(payload['report']['failures']),'unverified':payload['report']['unverified'],'output':str(out)},ensure_ascii=False))

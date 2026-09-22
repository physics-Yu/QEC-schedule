"""Native C++ author benchmark or the same output in our physical environment."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_experiments.qmap_native import compatible_architecture, run

p = argparse.ArgumentParser()
p.add_argument('--input',type=Path,help='JSON {atom_count, gates: [{type, qubits}]}')
p.add_argument('--benchmark',choices=['graphstate','qft','qaoa','vqe_two_local'])
p.add_argument('--qubits',type=int,default=16)
p.add_argument('--routing',choices=['strict','relaxed'],default='strict')
p.add_argument('--output',type=Path,default=Path('artifacts/qmap-native/demo'))
p.add_argument('--timeout',type=float,default=300)
a = p.parse_args()
if a.input:
    request = json.loads(a.input.read_text(encoding='utf-8'))
elif a.benchmark:
    request = dict(benchmark=a.benchmark,atom_count=a.qubits)
else:
    request = dict(atom_count=a.qubits,gates=[dict(type='CZ',qubits=[i,i+1])
                   for layer in range(4) for i in range(0,a.qubits-1,2)])
request['routing'] = a.routing
local = 'benchmark' not in request
if local:
    request.setdefault('architecture',compatible_architecture(request['atom_count']))
result = run(request,a.output,local=local,timeout_s=a.timeout)
print(json.dumps({k:v for k,v in result.items() if k not in {'code','architecture'}},indent=2))
if result['status']=='failed':
    raise SystemExit(1)

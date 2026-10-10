"""Independent original-source Enola placement/scheduling observations.

Only public upstream entrypoints and their documented algorithm outputs are
observed. No controller/backend private state or successful receipt is read.
"""
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import sys,time

from .checker import _hash


class EnolaStageObserver:
    def __init__(self,source_root,*,fixture=False):
        self.root=Path(source_root).resolve(); self.fixture=fixture
        self.sources={str((self.root/path).resolve()):path for path in (
            'enola/placer/placer.py','enola/placer/placer_parital_mapping.py',
            'enola/scheduler/gate_scheduler.py','enola/router/router_mis.py')}
        self.entries={'place_qubit','run','gate_scheduling','graph_coloring_rustworkx'}
        self.counted=self.entries|{'make_movement','init_sa_solution','compatible_2D','maximalis_solve_sort'}
        self.records=[]; self.pending={}; self.counts=Counter(); self.paths={}; self.effective_budgets=[]

    def _profile(self,frame,event,result):
        name=frame.f_code.co_name
        if name not in self.counted: return
        filename=frame.f_code.co_filename
        if filename not in self.paths: self.paths[filename]=str(Path(filename).resolve())
        path=self.sources.get(self.paths[filename])
        if path is None: return
        if event=='call':
            self.counts[path+':'+name]+=1
            if name=='init_sa_solution':
                placer=frame.f_locals['self']
                fields=('chip_dim','n_qubit','l2','sa_l','sa_iter_limit','sa_init_perturb_num','sa_n_trials','sa_t','sa_t_frozen')
                self.effective_budgets.append({'source_file':path,'values':{f:deepcopy(getattr(placer,f)) for f in fields if hasattr(placer,f)}})
            if name in self.entries:
                params=frame.f_code.co_varnames[:frame.f_code.co_argcount]
                inputs={key:deepcopy(frame.f_locals[key]) for key in params if key!='self'}
                if 'self' in frame.f_locals and hasattr(frame.f_locals['self'],'l2'): inputs['l2']=frame.f_locals['self'].l2
                self.pending[id(frame)]=(time.perf_counter(),inputs,path,name)
        elif event=='return' and id(frame) in self.pending:
            begin,inputs,path,name=self.pending.pop(id(frame)); output=deepcopy(result)
            if name=='run' and path.startswith('enola/placer/'):
                placer=frame.f_locals['self']
                output={'best_mapping':deepcopy(placer.best_mapping),'best_cost':placer.best_cost,'effective_chip_dim':deepcopy(placer.chip_dim),'temperature_steps':placer.sa_n}
            self.records.append({'source_file':path,'function':name,'first_line':frame.f_code.co_firstlineno,
                                 'inputs':inputs,'output':output,'input_sha256':_hash(inputs),'output_sha256':_hash(output),
                                 'wall_seconds':time.perf_counter()-begin})

    def __enter__(self):
        if sys.getprofile() is not None: raise RuntimeError('Do not replace an existing profiler')
        self.source_hashes={p:sha256(Path(path).read_bytes()).hexdigest() for path,p in self.sources.items()}
        sys.setprofile(self._profile); return self

    def __exit__(self,*exc):
        sys.setprofile(None)
        self.source_unchanged=all(sha256(Path(path).read_bytes()).hexdigest()==self.source_hashes[p] for path,p in self.sources.items())

    def evidence(self):
        return {'schema_version':'R6EnolaStageObservation/0.1','fixture':self.fixture,'method':'sys.setprofile on original pinned source',
                'source_hashes':self.source_hashes,'source_unchanged':self.source_unchanged,'call_counts':dict(self.counts),
                'records':deepcopy(self.records),'effective_placer_budgets':deepcopy(self.effective_budgets),
                'quantum_state_simulated':False,'hardware_executed':False}

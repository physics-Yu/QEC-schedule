"""Read-only Python-call observation used by R6 qualification harnesses.

Observes the selected upstream source itself, including AST-extracted functions
whose code filename is preserved. This is outside the immutable strategy body.
"""
from copy import deepcopy
from collections import Counter
from hashlib import sha256
from pathlib import Path
import sys
import time

from .checker import _hash


class EnolaCallObserver:
    def __init__(self, source_file, *, fixture=False):
        self.path=Path(source_file).resolve()
        self.fixture=fixture
        self.records=[]
        self.pending={}
        self.allowed={'compatible_2D':('a','b'),'maximalis_solve_sort':('n','edges')}
        backend=Path(__file__).resolve().parents[1]/'backend'
        self.search_sources={str((backend/name).resolve()):functions for name,functions in {'enola_kernel.py':{'group_route'},'strategy_compile.py':{'compile','_layout','entangle'}}.items()}
        self.project_search_counts=Counter(); self.file_cache={}

    def _profile(self,frame,event,arg):
        name=frame.f_code.co_name
        if name not in self.allowed and name not in {'group_route','compile','_layout','entangle'}: return
        filename=frame.f_code.co_filename
        if filename not in self.file_cache: self.file_cache[filename]=str(Path(filename).resolve())
        actual=self.file_cache[filename]
        if name in self.search_sources.get(actual,set()) and event=='call': self.project_search_counts[Path(actual).name+':'+name]+=1
        if name not in self.allowed or actual!=str(self.path): return
        token=id(frame)
        if event=='call':
            names=self.allowed[frame.f_code.co_name]
            # Preserve actual positional parameter names in a separately
            # descriptive record; no private controller state is inspected.
            parameters=frame.f_code.co_varnames[:frame.f_code.co_argcount]
            inputs={key:deepcopy(frame.f_locals[key]) for key in parameters}
            self.pending[token]=(time.perf_counter(),inputs)
        elif event=='return' and token in self.pending:
            started,inputs=self.pending.pop(token)
            outputs=deepcopy(arg)
            self.records.append({'function':frame.f_code.co_name,'source_file':str(self.path),'first_line':frame.f_code.co_firstlineno,'inputs':inputs,'output':outputs,'input_sha256':_hash(inputs),'output_sha256':_hash(outputs),'wall_seconds':time.perf_counter()-started})

    def __enter__(self):
        if sys.getprofile() is not None: raise RuntimeError('Existing Python profiler must not be replaced by the R6 observer')
        self.source_hash=sha256(self.path.read_bytes()).hexdigest()
        self.project_source_hashes={path:sha256(Path(path).read_bytes()).hexdigest() for path in self.search_sources}
        sys.setprofile(self._profile)
        return self

    def __exit__(self,*exc):
        sys.setprofile(None)
        self.source_unchanged=sha256(self.path.read_bytes()).hexdigest()==self.source_hash
        self.project_sources_unchanged=all(sha256(Path(path).read_bytes()).hexdigest()==value for path,value in self.project_source_hashes.items())

    def evidence(self):
        compact={}
        for record in self.records:
            key=(record['function'],record['first_line'],record['input_sha256'],record['output_sha256'])
            if key not in compact: compact[key]={**deepcopy(record),'count':0}
            compact[key]['count']+=1
        return {'schema_version':'R6EnolaObservation/0.1','fixture':self.fixture,'source_file':str(self.path),'source_sha256':self.source_hash,'source_unchanged':self.source_unchanged,'records':list(compact.values()),'record_count':len(self.records),'project_search_counts':dict(self.project_search_counts),'project_source_hashes':self.project_source_hashes,'project_sources_unchanged':self.project_sources_unchanged,'method':'sys.setprofile on upstream functions and project compile/layout/route entrypoints; identical upstream returns counted','quantum_state_simulated':False,'hardware_executed':False}

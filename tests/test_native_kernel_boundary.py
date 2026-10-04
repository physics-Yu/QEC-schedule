"""The production executor must work with exploration packages unavailable."""
import subprocess
import sys
import os
from pathlib import Path


def test_kernel_executes_and_restores_without_legacy_or_compiler_imports():
    code = '''
import importlib.abc, sys
class RejectLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('neutral_atom_env', 'neutral_atom_strategies', 'neutral_atom_app', 'neutral_atom_experiments', 'mqt')):
            raise AssertionError('Execution imported an external package: '+fullname)
sys.meta_path.insert(0, RejectLegacy())
from neutral_atom_kernel import KernelExecutor, GateSpec, Operation, DeclaredReportSource
k=KernelExecutor({'Q000':(0,0)}, (GateSpec('m','MEASURE',('Q000',)),), report_source=DeclaredReportSource(bits=(1,)))
k.run(k.bind_block('read', (Operation('read','MEASURE',('Q000',),500,gate_ids=('m',)),)), until_us=250)
assert not k.observe().measurement_results
r=KernelExecutor.restore(k.checkpoint())
k.run(); r.run()
assert k.observe()==r.observe() and r.observe().measurement_results['m']==1
assert not any(n.startswith(('neutral_atom_env','neutral_atom_strategies','mqt')) for n in sys.modules)
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr

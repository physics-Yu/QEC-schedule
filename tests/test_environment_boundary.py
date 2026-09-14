"""Environment independence and external control are architectural contracts."""
import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import subprocess
import sys

import pytest

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, OperationType
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_app.control import ControlProgram
from neutral_atom_app.visualization.workbench import build_inputs
from neutral_atom_app.pipeline import run_circuit
from neutral_atom_strategies import make_strategy


ROOT = Path(__file__).resolve().parents[1]


def inputs():
    return build_inputs({'atom_count': 2, 'layout': 'grid', 'seed': 7,
                         'gates': [{'id': 'h0', 'gate_type': 'H', 'qubit_ids': ['Q000'], 'column': 0},
                                   {'id': 'h1', 'gate_type': 'H', 'qubit_ids': ['Q001'], 'column': 0}]})[1:]


def pulse(env):
    ids = frozenset(g.id for g in env.observe().ready_gates)
    p = ProgramBuilder(env.state, TaskIntent('explicit-H', TaskTarget(),
                       frozenset(env.observe().positions), phase='program', gate_effects=ids))
    p.add(OperationType.RAMAN_ROTATION, 'User-specified H batch', gate_ids=tuple(sorted(ids)))
    return p.finish('explicit-physical-program')


def test_environment_imports_and_executes_when_external_packages_are_blocked():
    code = '''
import importlib.abc, importlib, pkgutil, sys
class BlockExternal(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('neutral_atom_strategies', 'neutral_atom_app', 'neutral_atom_experiments')):
            raise AssertionError('Environment imported external control: '+fullname)
sys.meta_path.insert(0, BlockExternal())
import neutral_atom_env
for item in pkgutil.walk_packages(neutral_atom_env.__path__, neutral_atom_env.__name__+'.'):
    importlib.import_module(item.name)
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, OperationType
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_env.visualization import VisualRecorder
env=NeutralAtomEnv.restore(sys.stdin.read())
recorder=VisualRecorder(env.state)
p=ProgramBuilder(env.state,TaskIntent('batch',TaskTarget(),frozenset(env.state.atoms),phase='program',gate_effects=frozenset({'h0','h1'})))
p.add(OperationType.RAMAN_ROTATION,'H',gate_ids=('h0','h1'))
env.submit(p.finish('external-explicit-program'));env.run(recorder.observe)
assert env.state.time_us==1 and env.observe().completed
assert NeutralAtomEnv.restore(env.snapshot()).snapshot()==env.snapshot()
assert not any(n.startswith(('neutral_atom_strategies','neutral_atom_app','neutral_atom_experiments')) for n in sys.modules)
'''
    # Pass a real platform created outside the child; the child has no fixture imports.
    checkpoint = NeutralAtomEnv.create(*inputs()).snapshot()
    result = subprocess.run([sys.executable, '-c', code], input=checkpoint,
                            capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr


def test_static_package_direction_and_no_external_executor_bypass():
    failures = []
    for package, forbidden in (
        ('neutral_atom_env', ('neutral_atom_strategies', 'neutral_atom_app', 'neutral_atom_experiments')),
        ('neutral_atom_strategies', ('neutral_atom_app', 'neutral_atom_experiments')),
        ('neutral_atom_experiments', ('neutral_atom_app',)),
    ):
        for path in (ROOT/'src'/package).rglob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                names = ([node.module or ''] if isinstance(node, ast.ImportFrom) else
                         [a.name for a in node.names] if isinstance(node, ast.Import) else [])
                for name in names:
                    if name.startswith(forbidden):
                        failures.append((str(path), node.lineno, name))
                if package == 'neutral_atom_strategies' and isinstance(node, ast.ImportFrom):
                    if node.module == 'neutral_atom_env.simulation.executor' or any(a.name == 'Executor' for a in node.names):
                        failures.append((str(path), node.lineno, 'Direct Executor bypass'))
    assert failures == []


def test_observation_is_frozen_and_reports_only_committed_state():
    env = NeutralAtomEnv.create(*inputs())
    before = env.observe()
    with pytest.raises((FrozenInstanceError, AttributeError)):
        before.time_us = 99
    with pytest.raises(TypeError):
        before.positions['Q000'] = None
    assert not hasattr(before, 'quantum_state') and not hasattr(before, 'rng_state')
    plan = pulse(env)
    assert env.observe() == before
    env.submit(plan)
    assert not env.observe().completed
    env.run()
    assert env.observe().completed and env.observe().time_us == 1
    assert before.time_us == 0 and not before.completed


def test_invalid_or_stale_program_does_not_change_episode():
    env = NeutralAtomEnv.create(*inputs())
    plan = pulse(env)
    before = env.snapshot()
    with pytest.raises(ValidationError):
        env.submit(replace(plan, state_fingerprint='bad'))
    assert env.snapshot() == before
    env.submit(plan)
    env.run()
    after = env.snapshot()
    with pytest.raises(ValidationError):
        env.submit(plan)
    assert env.snapshot() == after


def test_fork_and_mid_program_checkpoint_continue_without_changing_parent():
    env = NeutralAtomEnv.create(*inputs())
    env.submit(pulse(env))
    env.step()
    before = env.snapshot()
    fork = env.fork()
    restored = NeutralAtomEnv.restore(before)
    fork.run(); restored.run()
    assert fork.snapshot() == restored.snapshot()
    assert env.snapshot() == before
    env.run()
    assert env.snapshot() == fork.snapshot()


def test_user_defined_controller_uses_the_same_environment_and_observers():
    class ExplicitH:
        id = 'user-H'
        def run(self, env, *, on_event=None):
            env.submit(pulse(env)); env.run(on_event)
            return 'completed-by-user-strategy'
    events = []
    result, state, recorder = run_circuit(*inputs(), strategy=ExplicitH(),
                                        on_event=lambda s, e: events.append(e))
    assert result == 'completed-by-user-strategy'
    assert state.time_us == 1 and state.dag.completed and events
    assert recorder.payload()['duration'] == 1


@pytest.mark.parametrize('name', ['greedy', 'critical_path', 'lookahead', 'basic', 'resident', 'returning'])
def test_existing_strategies_are_replaceable_through_environment(name):
    env = NeutralAtomEnv.create(*inputs())
    original = env.snapshot()
    strategy = make_strategy(name)
    assert env.snapshot() == original
    result = ControlProgram(strategy).run(env)
    assert result.status == 'completed' and env.state.dag.completed

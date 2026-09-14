"""External circuit control application; physics is owned by NeutralAtomEnv."""
from neutral_atom_env.platform import Platform, initialize, load_circuit
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_strategies.planning.eager_baseline import EagerBaseline
from neutral_atom_strategies.planning.compilers import make_compiler
from neutral_atom_strategies.scheduling.scheduler import EagerScheduler
from neutral_atom_env.environment import NeutralAtomEnv
from neutral_atom_strategies.api import make_strategy
from .control import ControlProgram
def run_circuit(circuit, platform, placement, *, strategy=None, compiler=None, policy=None, seed=0, on_event=None):
    if sum(value is not None for value in (strategy, compiler, policy)) > 1:
        raise ValueError('Pass one strategy, compiler, or a policy that owns its compiler')
    env = NeutralAtomEnv.create(circuit, platform, placement, seed=seed)
    state = env.state
    recorder = VisualRecorder(state)
    def observe(s, event):
        recorder.observe(s, event)
        if on_event is not None:
            on_event(s, event)
    if strategy is not None:
        selected = make_strategy(strategy) if isinstance(strategy, str) else strategy
        result = ControlProgram(selected).run(env, on_event=observe)
    else:
        result = EagerScheduler(env, policy=policy or EagerBaseline(compiler=compiler or make_compiler())).run(observe)
    return result, state, recorder

"""Profile one audited physical preparation with the complete QEC DAG present."""
import cProfile
import pstats
import sys
from dataclasses import replace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))


def run():
    from neutral_atom_env.experiments.surface_qec import experiment_input
    from neutral_atom_env.experiments.qec_layout import build_qec_inputs
    from neutral_atom_env.simulation.pipeline import initialize
    from neutral_atom_env.quantum.stabilizer import StabilizerState
    from neutral_atom_env.simulation.patch_greedy import patch_assignment
    from neutral_atom_env.motion.patch_array import PatchArrayCompiler
    from neutral_atom_env.motion.program import ProgramBuilder
    from neutral_atom_env.domain.operations import TaskIntent,TaskTarget
    from neutral_atom_env.simulation.executor import Executor
    _,c,p,h=build_qec_inputs(experiment_input())
    state=initialize(c,p,h)
    state=replace(state,quantum_state=StabilizerState.zero(tuple(sorted(state.atoms))))
    builder=ProgramBuilder(state,TaskIntent('profile-stage',TaskTarget(),frozenset(state.atoms),phase='prepare'))
    PatchArrayCompiler().transfer_group(builder,patch_assignment(state))
    builder.intent=replace(builder.intent,target=TaskTarget(tuple(sorted(builder.state.placement.atom_to_holder.items()))))
    plan=builder.finish('qec-profile')
    executor=Executor(state);executor.submit(plan);executor.run()
    print('stage events',state.version,'simulation us',state.time_us)


if __name__=='__main__':
    profiler=cProfile.Profile();profiler.runcall(run)
    pstats.Stats(profiler).strip_dirs().sort_stats('cumulative').print_stats(22)

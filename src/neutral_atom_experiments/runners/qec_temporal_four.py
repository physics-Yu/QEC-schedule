"""Four-patch reported-history guard and bounded grouped physical transfers."""
from neutral_atom_env.environment import NeutralAtomEnv
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_experiments.surface_qec_temporal_four import HISTORY_IDS, CORRECTION_PREFIX, validate_history
from neutral_atom_strategies.motion.partitioned_cohort import PartitionedCohortCompiler
from neutral_atom_strategies.scheduling.qec_joint import run_qec_joint
from neutral_atom_strategies.scheduling.m4 import M4Result


def run_qec_temporal_four(state,*,on_event=None,**options):
    env = state if isinstance(state, NeutralAtomEnv) else None
    state = env.state if env is not None else state
    ids={g.id for g in state.dag.circuit.gates}
    guarded=any(g.startswith(CORRECTION_PREFIX) for g in ids)
    if guarded and not set(HISTORY_IDS).issubset(ids):
        return M4Result('stalled',({'code':'INCOMPLETE_SYNDROME_HISTORY','phase':'temporal_history',
            'message':'Four-patch correction slots require all 128 reported syndrome bits'},),(),0,())
    checked=False
    if options.get('resume') is True and guarded and all(g in state.measurement_results for g in HISTORY_IDS):
        try:validate_history(state.measurement_results)
        except ValidationError as error:
            return M4Result('stalled',({'code':error.violation.code,'phase':'temporal_history',
                'message':error.violation.message},),(),0,())
        checked=True
    def frontier(current,ready):
        nonlocal checked
        if guarded and any(g.id.startswith(CORRECTION_PREFIX) for g in ready):
            validate_history(current.measurement_results);checked=True
    def observe(current,event):
        nonlocal checked
        if on_event:on_event(current,event)
        if guarded and not checked and all(g in current.measurement_results for g in HISTORY_IDS):
            validate_history(current.measurement_results);checked=True
    result=run_qec_joint(env if env is not None else state,on_event=observe,frontier_validator=frontier,
                         compiler_type=PartitionedCohortCompiler,**options)
    if result.status=='completed' and guarded and not checked:
        raise ValidationError('INCOMPLETE_SYNDROME_HISTORY','Four-patch history was not checked')
    return result

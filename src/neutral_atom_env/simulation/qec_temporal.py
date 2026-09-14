"""Joint physical scheduling with a reported-history guard for temporal QEC.

No noise configuration or quantum projection truth is passed to the decoder.
Ordinary edited Clifford circuits without temporal correction slots continue
through the same physical compiler; their protocol completeness is reported
separately from their ability to compile.
"""
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.experiments.surface_qec_temporal import HISTORY_IDS, CORRECTION_PREFIX, validate_history
from .qec_joint import run_qec_joint
from .m4 import M4Result


def run_qec_temporal(state, *, on_event=None, **options):
    ids={g.id for g in state.dag.circuit.gates}
    guarded=any(gid.startswith(CORRECTION_PREFIX) for gid in ids)
    if guarded and not set(HISTORY_IDS).issubset(ids):
        return M4Result('stalled', ({'code':'INCOMPLETE_SYNDROME_HISTORY',
            'message':'Temporal correction slots require all four reported syndrome rounds',
            'phase':'temporal_history'},), (), 0, ())
    checked=False

    def frontier(current, ready):
        nonlocal checked
        if guarded and any(g.id.startswith(CORRECTION_PREFIX) for g in ready):
            # Edited dependencies cannot let a correction precede its full
            # reported history, even when its CSS condition uses only 16 bits.
            validate_history(current.measurement_results)
            checked=True

    def observe(current, event):
        nonlocal checked
        # Preserve the actual committed event even if the history is rejected.
        if on_event:
            on_event(current,event)
        if guarded and not checked and all(gid in current.measurement_results for gid in HISTORY_IDS):
            validate_history(current.measurement_results)
            checked=True

    result=run_qec_joint(state,on_event=observe,frontier_validator=frontier,**options)
    if result.status=='completed' and guarded and not checked:
        raise ValidationError('INCOMPLETE_SYNDROME_HISTORY','No complete reported history was checked')
    return result

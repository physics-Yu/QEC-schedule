"""Pure ideal quantum effects shared by prediction, audit and actual execution."""
from dataclasses import replace
import json
import random

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import GateStatus
from neutral_atom_env.domain.operations import OperationType as K


def condition_applies(state,gate):
    for gid,bit in gate.condition:
        if gid not in state.measurement_results or state.dag.nodes[gid].status!=GateStatus.COMPLETED:
            raise ValidationError('CONDITION_NOT_READY','Conditional control needs committed measurement outcomes')
        if type(state.measurement_results[gid]) is not int or state.measurement_results[gid] not in (0,1):
            raise ValidationError('INVALID_MEASUREMENT_RESULT','Measurement result must be a bit')
    return all(state.measurement_results[gid]==bit for gid,bit in gate.condition)


def validate_tracked_unitary(state,gate):
    if state.quantum_state is not None and (gate.gate_type not in {'H','X','Y','Z','CZ'} or gate.parameters):
        raise ValidationError('UNSUPPORTED_TRACKED_GATE','Exact stabilizer tracking supports H/X/Y/Z/CZ; T and other non-Clifford gates are not approximated')


def complete_effects(state,op):
    """No DAG/time mutation; the caller installs all effects atomically with DAG."""
    if state.quantum_state is None and op.operation_type not in {K.MEASUREMENT,K.RESET} and not any(state.dag.nodes[g].gate.condition for g in op.effect_gate_ids):
        extra={'applied':True,'applied_gate_ids':op.effect_gate_ids}
        if op.operation_type==K.RAMAN_ROTATION and op.gate_ids:
            extra['applied_by_gate']={g:True for g in op.effect_gate_ids}
        return state,extra
    quantum=state.quantum_state;atoms=dict(state.atoms);results=dict(state.measurement_results)
    rng=random.Random();rng.setstate(state.rng_state)
    outcomes={};true_outcomes={};flips={};reset_outcomes={};applied={};changed_rng=False
    for gid in op.effect_gate_ids:
        gate=state.dag.nodes[gid].gate
        apply=condition_applies(state,gate);applied[gid]=apply
        if not apply:continue
        if op.operation_type in {K.MEASUREMENT,K.RESET}:
            if quantum is None:raise ValidationError('QUANTUM_STATE_REQUIRED','Physical readout/reset requires opt-in quantum state tracking')
            q=gate.qubit_ids[0];bit=rng.getrandbits(1);changed_rng=True
            if op.operation_type==K.MEASUREMENT:
                if gid in results:raise ValidationError('DUPLICATE_MEASUREMENT','Measurement gate already has a committed result')
                quantum,outcome=quantum.measure_z(q,bit)
                true_outcomes[gid]=outcome;flips[gid]=gate.readout_flip
                reported=outcome ^ int(gate.readout_flip)
                results[gid]=reported;outcomes[gid]=reported
                atoms[q]=replace(atoms[q],measured=True)
            else:
                quantum,outcome=quantum.reset_zero(q,bit);reset_outcomes[gid]=outcome
                atoms[q]=replace(atoms[q],measured=False)
        elif quantum is not None:
            validate_tracked_unitary(state,gate)
            quantum=quantum.apply_gate(gate.gate_type,gate.qubit_ids,gate.parameters)
    extra={'applied':any(applied.values()),'applied_gate_ids':tuple(g for g,v in applied.items() if v)}
    if op.operation_type==K.RAMAN_ROTATION and op.gate_ids:
        extra['applied_by_gate']=applied
    if outcomes:extra['measurement_results']=outcomes
    if any(flips.values()):
        extra.update(measurement_true_results=true_outcomes,readout_flips=flips)
    if reset_outcomes:extra['reset_projection_results']=reset_outcomes
    return replace(state,quantum_state=quantum,atoms=atoms,measurement_results=results,
                   rng_state=rng.getstate() if changed_rng else state.rng_state),extra


def validate_readout_trace(state):
    """Audit reported/true bit metadata, including earlier completed plans.

    Physical replay independently checks the collapsed quantum state. Fixed
    flips then uniquely determine each projection bit from its committed report.
    Use the serialized operation as provenance, not editable trace labels.
    """
    plans={}
    audit_fields={'measurement_true_results','readout_flips'}
    for raw in state.trace.records:
        entry=json.loads(raw);event=entry['event'];kind=event['event_type']
        if kind=='plan_started':
            plan=event['plan'];plans[plan['id']]={o['id']:o for o in plan['operations']}
            continue
        if kind not in {'operation_started','operation_completed'}:continue
        op=plans.get(event.get('plan_id'),{}).get(event.get('operation_id'))
        if op is None or op['operation_type']!='measurement':
            if audit_fields & entry.keys():
                raise ValidationError('READOUT_AUDIT_MISMATCH','Readout audit fields belong only to completed measurement operations')
            continue
        if kind=='operation_started':
            if audit_fields & entry.keys():
                raise ValidationError('READOUT_AUDIT_MISMATCH','Projection truth cannot be recorded before measurement completion')
            continue
        ids=tuple(op.get('gate_ids') or (op['gate_id'],))
        reported={g:state.measurement_results[g] for g in ids}
        recorded=entry.get('measurement_results')
        if (recorded!=reported or not isinstance(recorded,dict) or
                any(type(bit) is not int for bit in recorded.values())):
            raise ValidationError('READOUT_AUDIT_MISMATCH','Measurement trace outcome differs from committed reported bits (measurement_results)')
        flips={g:state.dag.nodes[g].gate.readout_flip for g in ids}
        if any(flips.values()):
            truth={g:reported[g] ^ int(flips[g]) for g in ids}
            actual_truth=entry.get('measurement_true_results');actual_flips=entry.get('readout_flips')
            if (actual_truth!=truth or actual_flips!=flips or not isinstance(actual_truth,dict)
                    or not isinstance(actual_flips,dict) or any(type(bit) is not int for bit in actual_truth.values())
                    or any(type(flip) is not bool for flip in actual_flips.values())):
                raise ValidationError('READOUT_AUDIT_MISMATCH','Readout truth/flip audit differs from the declared fixed flip and reported result')
        elif audit_fields & entry.keys():
            raise ValidationError('READOUT_AUDIT_MISMATCH','Ideal readout must retain its original trace representation')

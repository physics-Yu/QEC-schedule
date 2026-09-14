"""Retain one complete, rigid CZ cohort on its original working coordinates.

Only a new compiler family: all moves, pulses, handoffs and Raman eligibility
remain audited by the existing physical backend and scheduled validator.
"""
from dataclasses import dataclass,replace

from neutral_atom_env.domain.models import Position2D,HolderType as H
from neutral_atom_env.domain.operations import CaptureBinding,OperationType as K,TaskIntent,TaskTarget
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware.dynamic_traps import trap_state
from .patch_array import PatchArrayCompiler
from .program import ProgramBuilder


@dataclass(frozen=True)
class RetainedCohort:
    bindings: tuple[CaptureBinding,...]
    origin: Position2D

    @property
    def atoms(self):return frozenset(b.atom_id for b in self.bindings)


class PersistentCohortCompiler(PatchArrayCompiler):
    id='qec-persistent-cohort-v1'

    def validate_cohort(self,state,cohort):
        if state.aod.pose!=cohort.origin or state.transfer is not None or state.aod.is_moving:
            raise ValidationError('QEC_REUSE_POSITION','Retained cohort must be stationary at its capture coordinates')
        if dict(state.placement.mobile_occupancy)!={b.cell:b.atom_id for b in cohort.bindings}:
            raise ValidationError('QEC_REUSE_COHORT','Reuse requires the exact complete carried cohort')
        if any(state.slm_enabled[b.static_trap_id] for b in cohort.bindings):
            raise ValidationError('QEC_REUSE_SUPPORT','Retained source SLMs must remain extinguished')

    def _finish(self,p,planner_id):
        p.intent=replace(p.intent,target=TaskTarget(tuple(sorted(p.state.placement.atom_to_holder.items())),
            p.state.aod.configuration(),trap_state(p.state)))
        return p.finish(planner_id)

    def release(self,state,cohort):
        """A real aligned OFFLOAD plan, also usable as a read-only proposal."""
        self.validate_cohort(state,cohort)
        p=ProgramBuilder(state,TaskIntent(f'qec-release/{state.version}',TaskTarget(),cohort.atoms,phase='cleanup'))
        p.add(K.AOD_OFFLOAD,'Release retained cohort onto original SLM supports',bindings=cohort.bindings)
        return self._finish(p,'qec-cohort-release-v1'),p.state

    def pulse(self,state,members,shift,cohort=None):
        ids=frozenset(g for g,_,_ in members)
        mobiles=frozenset(m for _,_,m in members)
        p=ProgramBuilder(state,TaskIntent(f'qec-retain/{state.version}/{"-".join(sorted(ids))}',TaskTarget(),
            frozenset(q for _,a,b in members for q in (a,b)),phase='program',gate_effects=ids))
        reused=cohort is not None
        if reused:
            self.validate_cohort(state,cohort)
            if mobiles!=cohort.atoms or any(state.placement.atom_to_holder[a].holder_type!=H.STATIC for _,a,_ in members):
                raise ValidationError('QEC_REUSE_MEMBERS','Every carried atom must serve once against a static anchor')
        else:
            origin,bindings=self.bindings(state,mobiles)
            cohort=RetainedCohort(bindings,origin)
            self.route(p,origin)
            p.add(K.AOD_LOAD,'Load complete CZ cohort for persistent service',bindings=bindings)
        start=len(p.operations)
        target=Position2D(cohort.origin.x_um+shift[0],cohort.origin.y_um+shift[1])
        self.route(p,target,depart=cohort.bindings if not reused else (),label='Move retained CZ cohort to interaction geometry')
        outbound=p.operations[start:]
        p.add(K.ENTANGLING_PULSE,f'Global pulse: {len(members)} retained CZ pairs',gate_ids=tuple(g for g,_,_ in members))
        positions=[cohort.origin]+[op.target_pose for op in outbound]
        for point in reversed(positions[:-1]):
            # The source SLMs are OFF. This is ordinary motion, not an
            # approach exemption without an immediately following handoff.
            p.add(K.AOD_MOVE,'Separate retained atoms before single-qubit control',target=point)
        self.validate_cohort(p.state,cohort)
        return self._finish(p,self.id),cohort

"""Split tall rigid transfers into bounded AOD-height bands.

Each band uses the unmodified capture, sweep, support and route validators.
This is a finite geometric construction, not independent per-cell control.
"""
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_strategies.motion.qec_persistent import PersistentCohortCompiler


class PartitionedCohortCompiler(PersistentCohortCompiler):
    def transfer_group(self,p,destinations,label='Translate array'):
        remaining={q:site for q,site in destinations.items() if p.state.placement.atom_to_holder[q].holder_id!=site}
        if not remaining:return
        points={q:p.state.placement.position(q,p.state.world,p.state.aod) for q in remaining}
        shifts={(p.state.world.traps[site].position.x_um-points[q].x_um,
                 p.state.world.traps[site].position.y_um-points[q].y_um) for q,site in remaining.items()}
        if len(shifts)!=1:
            raise ValidationError('PATCH_SHAPE','Partitioned destinations still require one rigid translation')
        span=max(p.state.aod.configuration().y_um)-min(p.state.aod.configuration().y_um)
        if max(v.y_um for v in points.values())-min(v.y_um for v in points.values())<=span:
            return super().transfer_group(p,remaining,label)
        groups=[]
        for q in sorted(points,key=lambda q:(points[q].y_um,points[q].x_um,q)):
            if not groups or points[q].y_um-groups[-1][0]>span:
                groups.append((points[q].y_um,{}))
            groups[-1][1][q]=remaining[q]
        # Moving down: lower source band first. Moving up: upper band first.
        # These are candidates; passing the whole route remains mandatory.
        if next(iter(shifts))[1]>0:groups.reverse()
        for i,(_,group) in enumerate(groups):
            super().transfer_group(p,group,f'{label}: band {i+1}/{len(groups)}')

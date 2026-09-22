"""Partition only requested moves; whole-group capture closure is mandatory."""
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_strategies.motion.ordered_primitives import build_batch


def compatible_groups(state, assignments, *, interactions=True, require_closure=True):
    groups = []
    for assignment in assignments:
        for group in groups:
            try:
                build_batch(state, (*group, assignment), check_closure=False,
                            check_interactions=False, bounded_spares=True)
            except ValidationError:
                continue
            group.append(assignment)
            break
        else:
            groups.append([assignment])
    if not require_closure:
        return tuple(tuple(g) for g in groups)
    result = []
    for group in groups:
        try:
            build_batch(state, group, check_interactions=interactions, bounded_spares=True)
            result.append(tuple(group))
        except ValidationError:
            # Pairwise compatibility alone cannot certify a Cartesian product.
            # Each singleton is still checked by codegen before being accepted.
            result.extend((a,) for a in group)
    return tuple(result)

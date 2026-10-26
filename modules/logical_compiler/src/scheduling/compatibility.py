"""Pure group constraints for declared component waves, before atom expansion."""

from itertools import combinations, pairwise

from modules.codes.contracts.parallel import ComponentExecutionSpec, SharedAODClaim


def _within(used: int, capacity: int | None) -> bool:
    return capacity is None or used <= capacity


def _shared_capacity(claims: tuple[SharedAODClaim, ...]) -> bool:
    if any(claim.joint_family is not None for claim in claims):
        # These are proposals for a complete-world joint trace, not a merge of
        # isolated column bands. The execution owner must admit exact group
        # coverage and its measured aggregate capacities before committing.
        first = claims[0]
        return (
            first.joint_family is not None
            and len({c.joint_member for c in claims}) == len(claims)
            and all(
                (
                    c.joint_family,
                    frozenset(c.joint_code_ids),
                    c.aod_id,
                    c.max_rows,
                    c.max_columns,
                    c.readout_channel,
                    c.max_readout_atoms,
                    c.min_spacing,
                )
                == (
                    first.joint_family,
                    frozenset(first.joint_code_ids),
                    first.aod_id,
                    first.max_rows,
                    first.max_columns,
                    first.readout_channel,
                    first.max_readout_atoms,
                    first.min_spacing,
                )
                for c in claims
            )
        )
    for aod_id in {claim.aod_id for claim in claims}:
        group = tuple(claim for claim in claims if claim.aod_id == aod_id)
        first = group[0]
        if any(
            (
                item.row_trajectory_key,
                item.peak_rows,
                item.max_rows,
                item.max_columns,
                item.min_spacing,
            )
            != (
                first.row_trajectory_key,
                first.peak_rows,
                first.max_rows,
                first.max_columns,
                first.min_spacing,
            )
            for item in group
        ):
            return False
        assert first.peak_rows is not None
        if not _within(first.peak_rows, first.max_rows) or not _within(
            sum(item.peak_columns for item in group if item.peak_columns is not None),
            first.max_columns,
        ):
            return False
        ordered = sorted(group, key=lambda item: item.column_min)
        if any(
            right.column_min <= left.column_max
            or right.column_min - left.column_max < first.min_spacing
            for left, right in pairwise(ordered)
        ):
            return False
    for channel in {claim.readout_channel for claim in claims}:
        group = tuple(claim for claim in claims if claim.readout_channel == channel)
        capacity = group[0].max_readout_atoms
        if any(item.max_readout_atoms != capacity for item in group) or not _within(
            sum(
                item.peak_readout_atoms
                for item in group
                if item.peak_readout_atoms is not None
            ),
            capacity,
        ):
            return False
    return True


def _pair(left: ComponentExecutionSpec, right: ComponentExecutionSpec) -> bool:
    if set(left.participant_blocks) & set(right.participant_blocks) or set(
        left.exclusive_resources
    ) & set(right.exclusive_resources):
        return False
    for a in left.spaces:
        for b in right.spaces:
            if not (
                a.region.x_max < b.region.x_min
                or b.region.x_max < a.region.x_min
                or a.region.y_max < b.region.y_min
                or b.region.y_max < a.region.y_min
            ):
                return False
    return True


def compatible_specs(specs: tuple[ComponentExecutionSpec, ...]) -> bool:
    """Check declared waveform families, participant claims and aggregate capacity.

    Claims are supplied by the selected code. This function neither binds nor
    expands components. Shared control remains conditional on later physical
    validation of the actual combined grid and complete atom world. Exclusive
    operations can run alone. Invalid or incompatible groups return False.
    """
    if not specs:
        return False
    first = specs[0]
    if any(
        s.shared_aod is not None and s.shared_aod.joint_family is not None
        for s in specs
    ):
        return (
            all(
                s.parallel_mode == "shared_aod_lockstep"
                and s.shared_aod is not None
                and s.shared_aod.joint_family is not None
                and (
                    s.code_id in s.shared_aod.joint_code_ids
                    if s.shared_aod.joint_code_ids
                    else s.code_id == first.code_id
                )
                and s.waveform_key == first.waveform_key
                for s in specs
            )
            and all(_pair(a, b) for a, b in combinations(specs, 2))
            and _shared_capacity(
                tuple(s.shared_aod for s in specs if s.shared_aod is not None)
            )
        )
    if first.parallel_mode == "profile_parallel":
        keyed = any(spec.estimate_batch_key is not None for spec in specs)
        return (
            all(spec.parallel_mode == "profile_parallel" for spec in specs)
            and (
                not keyed
                or (
                    first.estimate_batch_key is not None
                    and all(
                        spec.estimate_batch_key == first.estimate_batch_key
                        for spec in specs
                    )
                )
            )
            and all(_pair(left, right) for left, right in combinations(specs, 2))
        )
    if first.parallel_mode == "exclusive":
        return len(specs) == 1
    if any(
        spec.parallel_mode != first.parallel_mode
        or len(spec.participant_blocks) != len(first.participant_blocks)
        or spec.code_id != first.code_id
        or (
            first.parallel_mode != "local_parallel"
            and spec.component_id != first.component_id
        )
        or spec.waveform_key is None
        or spec.waveform_key != first.waveform_key
        for spec in specs
    ):
        return False
    if any(not _pair(left, right) for left, right in combinations(specs, 2)):
        return False
    claims = tuple(spec.shared_aod for spec in specs if spec.shared_aod is not None)
    if (first.parallel_mode == "shared_aod_lockstep" and len(claims) != len(specs)) or (
        first.parallel_mode == "independent_aods_lockstep" and claims
    ):
        return False
    exclusive = {resource for spec in specs for resource in spec.exclusive_resources}
    if any(f"aod:{claim.aod_id}" in exclusive for claim in claims):
        return False
    return _shared_capacity(claims)

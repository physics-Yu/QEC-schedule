"""Independent integer checks for decoded depth certificates."""

from itertools import combinations

from .model import Problem, Witness


def physical(point: tuple[int, int]) -> tuple[int, int]:
    """Convert a trap index to micrometers (10 um pitch, 2 um pair gap)."""
    x, y = point
    return 10 * (x // 2) + 2 * (x % 2), 10 * y


def validate(problem: Problem, witness: Witness) -> list[str]:
    """Check occupancy, Cartesian pickup, actual interactions and order."""
    errors = []
    if len(witness.positions) != len(witness.carriers) + 1:
        return ["state_count"]
    if len(witness.gate_states) != len(problem.layers):
        return ["gate_count"]
    if problem.cyclic and witness.positions[-1] != witness.positions[0]:
        errors.append("final_home")
    for t, positions in enumerate(witness.positions):
        if len(positions) != problem.atoms or len(set(positions)) != problem.atoms:
            return [f"state {t}: occupancy"]
        if any(
            not (0 <= x < 2 * problem.columns and 0 <= y < problem.rows)
            for x, y in positions
        ):
            return [f"state {t}: bounds"]
    if problem.initially_idle:
        cells = {(x // 2, y) for x, y in witness.positions[0]}
        if len(cells) != problem.atoms:
            errors.append("initial_interaction")
    for t, carrier_tuple in enumerate(witness.carriers):
        carriers = set(carrier_tuple)
        if len(carriers) != len(carrier_tuple) or not carriers <= set(
            range(problem.atoms)
        ):
            return [f"move {t}: carriers"]
        before, after = witness.positions[t : t + 2]
        if before == after:
            errors.append(f"move {t}: empty_move")
        if any(
            before[q] != after[q] for q in range(problem.atoms) if q not in carriers
        ):
            errors.append(f"move {t}: stationary_atom_moved")
        for positions in (before, after):
            cols = {positions[q][0] for q in carriers}
            rows = {positions[q][1] for q in carriers}
            covered = {
                q for q, (x, y) in enumerate(positions) if x in cols and y in rows
            }
            if covered != carriers:
                errors.append(f"move {t}: Cartesian_ghost")
        for a, b in combinations(carriers, 2):
            for axis in (0, 1):
                old = (before[a][axis] > before[b][axis]) - (
                    before[a][axis] < before[b][axis]
                )
                new = (after[a][axis] > after[b][axis]) - (
                    after[a][axis] < after[b][axis]
                )
                if old != new:
                    errors.append(f"move {t}: order_or_sharing")
        if problem.motion == "rigid":
            vectors = {
                (
                    physical(after[q])[0] - physical(before[q])[0],
                    physical(after[q])[1] - physical(before[q])[1],
                )
                for q in carriers
            }
            if len(vectors) != 1:
                errors.append(f"move {t}: rigid_translation")
    previous = 0 if problem.initially_idle else -1
    for stage, t in enumerate(witness.gate_states):
        if not previous < t < len(witness.positions):
            return errors + ["stage_order"]
        previous = t
        positions = witness.positions[t]
        actual = {
            (a, b)
            for a, b in combinations(range(problem.atoms), 2)
            if positions[a][0] // 2 == positions[b][0] // 2
            and positions[a][1] == positions[b][1]
        }
        expected = {tuple(sorted(pair)) for pair in problem.layers[stage]}
        if actual != expected:
            errors.append(f"gate {stage}: actual_interactions")
    return errors

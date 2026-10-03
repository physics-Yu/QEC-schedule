"""Bounded QEC scheduling with caller-specified sparse working sites.

Only caller-listed carriers are staged, one atom per validated plan. Other
atoms remain present in the environment and in every ordinary physical check.
This strategy adds no quantum effects, geometry, timing or hardware exceptions.
The existing ``run_qec`` keeps its whole-array staging and defaults unchanged.
"""
from collections.abc import Mapping
from time import perf_counter

from neutral_atom_env.environment import as_environment
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderRef, HolderType, GateStatus, Position2D, ZoneType
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, OperationType
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_env.program.scheduled import scheduled_program
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_env.replay.serializer import primitive

from neutral_atom_strategies.motion.patch_array import PatchArrayCompiler
from neutral_atom_strategies.motion.single_trap import in_zone
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_strategies.scheduling.m4 import M4Result
from neutral_atom_strategies.scheduling.patch_greedy import preflight_group, batch_service
from neutral_atom_strategies.scheduling.qec import qec_cz_groups, readout_groups, readout_service


def run_qec_sparse(state, *, working_destinations, on_event=None, terminal=None,
                   max_decisions=2048, candidate_budget=256, route_expansions=100000,
                   cz_groups_factory=None, readout_groups_factory=None):
    """Execute an unchanged supported DAG at explicit existing EZ SLM sites.

    ``working_destinations`` maps every circuit operand to its working trap ID;
    additional atoms may be included deliberately. Other atoms are spectators.
    Stage/cleanup uses singleton transfers, so the supplied mapping need not be
    a rigid translation. Gate and readout services reuse the existing QEC
    strategy. All accepted plans still pass the ordinary environment validator.

    The terminal defaults to the initial holders, AOD geometry and trap masks.
    A resumed completed DAG still performs and validates its terminal cleanup.
    """
    env = as_environment(state)
    cz_partition = qec_cz_groups if cz_groups_factory is None else cz_groups_factory
    readout_partition = readout_groups if readout_groups_factory is None else readout_groups_factory
    state = env.state
    terminal = terminal if terminal is not None else initial_terminal(state)
    rejected, log = [], []
    decisions, phase = 0, 'initialization'
    compiler = None

    def drain():
        while env.pending:
            event = env.step()
            if on_event:
                on_event(env.state, event)

    def submit(plan, entry, started):
        nonlocal decisions
        if decisions >= max_decisions:
            raise ValidationError('DECISION_BUDGET_EXHAUSTED', 'Sparse QEC decision budget exhausted')
        entry.update(decision=decisions, start_us=state.time_us,
                     duration_us=plan.estimated_duration_us,
                     compile_wall_time_s=perf_counter() - started)
        env.submit(plan)
        log.append(entry)
        decisions += 1
        drain()

    def reject(error, entry):
        rejected.append(entry | {'violation': primitive(error.violation)})

    def result(status, error=None):
        diagnostics = () if error is None else ({
            'code': error.violation.code, 'message': error.violation.message,
            'phase': phase, 'decisions_completed': decisions,
            'unfinished_gates': [g.id for g in state.dag.circuit.gates
                                if state.dag.nodes[g.id].status != GateStatus.COMPLETED]},)
        return M4Result(status, diagnostics, tuple(rejected), decisions, tuple(log))

    def transfer_atom(atom, destination, *, cleanup=False):
        holder = HolderRef(HolderType.STATIC, destination)
        if state.placement.atom_to_holder[atom] == holder:
            return
        kind = 'terminal_atom' if cleanup else 'stage_atom'
        started = perf_counter()
        entry = {'kind': kind, 'atom': atom, 'destination': destination}
        try:
            p = ProgramBuilder(state, TaskIntent(
                f'qec-sparse-{kind}/{state.version}/{atom}', TaskTarget(((atom, holder),)),
                frozenset((atom,)), phase='cleanup' if cleanup else 'prepare'))
            compiler.transfer_group(p, {atom: destination},
                                    'Restore original carrier' if cleanup else 'Stage sparse carrier')
            plan = p.finish(f'qec-sparse-{kind}-v1')
        except ValidationError as error:
            reject(error, entry)
            raise
        submit(plan, entry, started)

    try:
        for value, name in ((max_decisions, 'max_decisions'), (candidate_budget, 'candidate_budget'),
                            (route_expansions, 'route_expansions')):
            if type(value) is not int or value < 1:
                raise ValidationError('QEC_SEARCH_BUDGET', f'{name} must be a positive integer')
        if state.quantum_state is None:
            raise ValidationError('QEC_QUANTUM_STATE_REQUIRED', 'Enable quantum state tracking before sparse QEC')
        if not isinstance(working_destinations, Mapping):
            raise ValidationError('QEC_WORKING_LAYOUT', 'Working destinations must be an atom-to-trap mapping')
        destinations = dict(working_destinations)
        if (any(not isinstance(q, str) or q not in state.atoms or not isinstance(site, str)
                or site not in state.world.traps for q, site in destinations.items()) or
                len(set(destinations.values())) != len(destinations)):
            raise ValidationError('QEC_WORKING_LAYOUT', 'Working sites need known atoms and distinct existing traps')
        operands = {q for gate in state.dag.circuit.gates for q in gate.qubit_ids}
        if not operands <= destinations.keys():
            raise ValidationError('QEC_WORKING_LAYOUT', 'Specify a working site for every circuit operand')
        if any(not in_zone(state, state.world.traps[site].position, ZoneType.ENTANGLEMENT)
               for site in destinations.values()):
            raise ValidationError('QEC_WORKING_LAYOUT', 'Working sites must lie in the existing entanglement zone')
        if any(q not in state.atoms or h.holder_type != HolderType.STATIC
               or h.holder_id not in state.world.traps for q, h in terminal.holders):
            raise ValidationError('QEC_TERMINAL_LAYOUT', 'Sparse QEC restores only known static terminal holders')
        if len({h.holder_id for _, h in terminal.holders}) != len(terminal.holders):
            raise ValidationError('QEC_TERMINAL_LAYOUT', 'Terminal atoms need distinct holders')
        compiler = PatchArrayCompiler(route_expansions)
        drain()

        if not state.dag.completed:
            phase = 'sparse_preparation'
            for atom, destination in sorted(destinations.items()):
                transfer_atom(atom, destination)
            while not state.dag.completed:
                if decisions >= max_decisions:
                    raise ValidationError('DECISION_BUDGET_EXHAUSTED', 'Sparse QEC decision budget exhausted')
                ready = list(state.dag.ready_gates())
                started, phase = perf_counter(), 'frontier'
                rotations = [g for g in ready if g.u_parameters is not None]
                if rotations:
                    gate = rotations[0]
                    same = [g for g in rotations if g.gate_type == gate.gate_type]
                    p = ProgramBuilder(state, TaskIntent(
                        f'qec-sparse-raman/{state.version}/{gate.id}', TaskTarget(),
                        frozenset(gate.qubit_ids), gate.id, 'effect', gate.id))
                    p.add(OperationType.RAMAN_ROTATION, 'Addressed sparse quantum control', gate_id=gate.id)
                    plan = p.finish('qec-sparse-raman-v1')
                    if len(same) > 1:
                        plan = scheduled_program(plan, state, tuple((g.id, 0.) for g in same[1:]))
                    submit(plan, {'kind': 'raman', 'gate_type': gate.gate_type,
                                  'batch_size': len(same), 'selected': ','.join(g.id for g in same)}, started)
                    continue
                cz, chosen, phase = [g for g in ready if g.gate_type == 'CZ'], None, 'cz_search'
                for attempt, (shift, members) in enumerate(cz_partition(state, cz)):
                    if attempt >= candidate_budget:
                        break
                    try:
                        preflight_group(state, compiler, shift, members)
                        chosen = (batch_service(state, compiler, shift, members), members)
                        break
                    except ValidationError as error:
                        reject(error, {'kind': 'cz', 'members': members, 'shift': shift})
                if chosen:
                    submit(chosen[0], {'kind': 'cz_batch', 'batch_size': len(chosen[1]),
                                      'selected': ','.join(g for g, _, _ in chosen[1])}, started)
                    continue
                phase = 'readout_search'
                for kind in ('MEASURE', 'RESET'):
                    pending = [g for g in ready if g.gate_type == kind]
                    for group in readout_partition(state, pending) if pending else ():
                        try:
                            plan, count = readout_service(state, compiler, group)
                            chosen = (plan, group, count)
                            break
                        except ValidationError as error:
                            reject(error, {'kind': 'readout', 'gates': [g.id for g in group]})
                    if chosen:
                        break
                if chosen:
                    submit(chosen[0], {'kind': 'readout', 'batch_size': len(chosen[1]),
                                      'reset_count': chosen[2],
                                      'selected': ','.join(g.id for g in chosen[1])}, started)
                    continue
                raise ValidationError('QEC_FRONTIER_EXHAUSTED',
                                      'No sparse quantum or readout candidate passed physical validation')

        phase = 'terminal_holders'
        for atom, holder in terminal.holders:
            transfer_atom(atom, holder.holder_id, cleanup=True)
        phase, started = 'terminal_supports', perf_counter()
        p = ProgramBuilder(state, TaskIntent(f'qec-sparse-terminal/{state.version}', terminal,
                                            frozenset(state.atoms), phase='cleanup'))
        if terminal.aod_configuration is not None:
            axes = terminal.aod_configuration
            compiler.route(p, Position2D(axes.x_um[0], axes.y_um[0]))
        if terminal.traps is not None and trap_state(p.state) != terminal.traps:
            p.add(OperationType.TRAP_SWITCH, 'Restore original supports', switch_state=terminal.traps)
        if p.operations:
            submit(p.finish('qec-sparse-terminal-v1'), {'kind': 'terminal_supports'}, started)
        validate_target(terminal, state)
        return result('completed')
    except ValidationError as error:
        return result('stalled', error)

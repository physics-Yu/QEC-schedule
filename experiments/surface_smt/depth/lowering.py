"""Lower solved depth schedules into ordinary validated Atom IR."""

from dataclasses import asdict
from types import SimpleNamespace
from typing import Any

from nadit_physical_compiler.capabilities import CZCapability, LocalControl
from nadit_physical_compiler.compilers.contracts import ProgramContext
from nadit_physical_compiler.device import (
    AOD,
    Device,
    Position,
    Region,
    SLMSite,
    Timing,
    Zone,
)
from nadit_physical_compiler.execution import FakeBackend
from nadit_physical_compiler.frontend import loads_qasm
from nadit_physical_compiler.serialization import encode_result
from nadit_physical_compiler.smt.checker import check_lowering
from nadit_physical_compiler.smt.contracts import Plan, Snapshot
from nadit_physical_compiler.smt.lowering import lower_plan
from nadit_physical_compiler.state import AtomLayout, AtomState, SLMHolder
from nadit_physical_compiler.validation import validate_result

from experiments.surface_smt.gate_oracle import (
    action_stim,
    source_stim,
    unitary,
)
from modules.codes.rotated_surface_d3.components.circuits import source_qasm
from modules.codes.rotated_surface_d3.definition import CHECKS

from .model import Problem, Witness
from .uniform import UniformWitness, validate_uniform
from .validation import physical, validate


def checks_metadata() -> dict[str, Any]:
    """Bind the fixed d3 code supports to physical wires for the shared viewer."""
    counts = {"X": 0, "Z": 0}
    checks = []
    for index, (basis, support) in enumerate(CHECKS):
        checks.append(
            {
                "id": f"{basis}{counts[basis]}",
                "basis": basis,
                "ancilla_qubit": 9 + index,
                "data_qubits": list(support),
            }
        )
        counts[basis] += 1
    return {"schema": "nadit.qec-overlay/1", "checks": checks}


def gate_source() -> str:
    """Retain the N/Z barriers and all gates; omit terminal measurements only."""
    return (
        "\n".join(
            line
            for line in source_qasm("se_round").splitlines()
            if "= measure" not in line
        )
        + "\n"
    )


def device_for(problem: Problem) -> Device:
    """Every coordinate in the finite endpoint bank is a fixed SLM trap."""
    bounds = Region(-1, -1, 10 * (problem.columns - 1) + 3, 10 * (problem.rows - 1) + 1)
    sites = tuple(
        SLMSite(f"s_{x}_{y}", Position(*physical((x, y))))
        for y in range(problem.rows)
        for x in range(2 * problem.columns)
    )
    return Device(
        "depth-shared-bank",
        (Zone("shared", bounds, ("cz", "rotate", "reset")),),
        sites,
        (AOD("transport", bounds, 1, motion=problem.motion),),
        Timing(15, 15, 1),
        cz=CZCapability("rydberg", 4.6, 0.36, allow_spectators=True),
        local=LocalControl("local", 1, 10),
    )


def move_snapshots(witness: Witness, step: int) -> tuple[Snapshot, Snapshot, Snapshot]:
    """Lower one certified MOVE through LOAD and STORE, preserving empty lines."""
    before, after = witness.positions[step : step + 2]
    carriers = witness.carriers[step]
    flags = tuple(q in carriers for q in range(len(before)))
    old = tuple(Position(*physical(p)) for p in before)
    new = tuple(Position(*physical(p)) for p in after)
    if isinstance(witness, UniformWitness):
        oldcols, oldrows = witness.grids[step]
        q = carriers[0]
        dx, dy = new[q].x - old[q].x, new[q].y - old[q].y
        newcols = tuple(x + dx for x in oldcols)
        newrows = tuple(y + dy for y in oldrows)
    else:
        oldcols = tuple(sorted({old[q].x for q in carriers}))
        oldrows = tuple(sorted({old[q].y for q in carriers}))
        newcols = tuple(sorted({new[q].x for q in carriers}))
        newrows = tuple(sorted({new[q].y for q in carriers}))
    return (
        Snapshot(old, flags, oldcols, oldrows),
        Snapshot(new, flags, newcols, newrows),
        Snapshot(new, (False,) * len(after)),
    )


def export(problem: Problem, witness: Witness) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate a d3 solution and emit its gate-only result and quantum evidence."""
    if isinstance(witness, UniformWitness):
        errors = validate_uniform(problem, witness)
    else:
        errors = validate(problem, witness)
    if errors:
        raise ValueError(errors)
    device = device_for(problem)
    source = gate_source()
    dag = loads_qasm(source)
    entry = AtomLayout(
        tuple(
            AtomState(q, Position(*physical(p)), SLMHolder(f"s_{p[0]}_{p[1]}"))
            for q, p in enumerate(witness.positions[0])
        ),
        (),
        tuple(range(problem.atoms)),
    )
    context = ProgramContext(dag, device, "transport", None, entry)
    states = [
        Snapshot(tuple(a.position for a in entry.atoms), (False,) * problem.atoms)
    ]
    transitions = []
    operations = []

    def append(kind, snapshot, ids=()):
        states.append(snapshot)
        transitions.append(kind)
        operations.append(tuple(ids))

    segments: list[list[int]] = [[]]
    barriers = []
    for node in dag.nodes:
        if node.name == "barrier":
            barriers.append(node.id)
            segments.append([])
        else:
            segments[-1].append(node.id)
    if len(barriers) != 6 or len(problem.layers) != 4:
        raise ValueError("Expected the existing six-barrier d3 extraction source.")
    predecessors: dict[int, set[int]] = {n.id: set() for n in dag.nodes}
    for a, b in dag.edges:
        predecessors[b].add(a)
    done: set[int] = set()

    def native_segment(index):
        pending = set(segments[index])
        while pending:
            ready = sorted(n for n in pending if predecessors[n] <= done)
            local = [n for n in ready if dag.nodes[n].name != "cz"]
            selected = local or ready
            if not selected:
                raise ValueError("Native segment has an uncompleted dependency.")
            if not local:
                expected = {n for n in pending if dag.nodes[n].name == "cz"}
                if set(selected) != expected:
                    raise ValueError("A fixed N/Z stage was not ready as one CZ pulse.")
            append("none", states[-1], selected)
            done.update(selected)
            pending.difference_update(selected)
        if index < len(barriers):
            append("none", states[-1], (barriers[index],))
            done.add(barriers[index])

    native_segment(0)
    for t in range(len(witness.carriers)):
        loaded, moved, stored = move_snapshots(witness, t)
        append("load", loaded)
        append("move", moved)
        append("store", stored)
        for stage, at in enumerate(witness.gate_states):
            if at == t + 1:
                native_segment(stage + 1)
    native_segment(5)
    plan = Plan(tuple(states), tuple(transitions), tuple(operations))
    result = lower_plan(context, plan, FakeBackend(0))
    return_home = problem.cyclic or isinstance(witness, UniformWitness)
    if return_home and result.exit_state != entry:
        raise ValueError(
            "Cyclic Atom IR did not restore atom identities, SLM homes and inactive AOD."
        )
    errors = check_lowering(context, plan, result)
    report = validate_result(
        result, entry_state=entry, device=device, dag=dag, detailed=True
    )
    if errors or not report["ok"]:
        raise ValueError((errors, report))
    expansion = SimpleNamespace(
        program=result.program,
        entry_state=entry,
        exit_state=result.exit_state,
        wire_atoms=tuple(range(17)),
    )
    actual, _ = action_stim(expansion, device)
    expected, _ = source_stim(source)
    if unitary(actual) != unitary(expected):
        raise ValueError("Clifford tableau mismatch.")
    from hashlib import sha256

    from nadit_physical_compiler.serialization import encode_device
    from nadit_physical_compiler.smt.solver import digest

    document = encode_result(
        result,
        entry_state=entry,
        job={
            "strategy": {"kind": "smt"},
            "research_profile": "free-layout-move-depth/1",
        },
        provenance={"compiler": {"kind": "surface_depth_smt", "version": "1"}},
        validation=report,
        dag=dag,
        device=device,
        inputs={
            "qasm_sha256": sha256(source.encode()).hexdigest(),
            "device_sha256": digest(encode_device(device)),
        },
    )
    document["experiment"] = {
        "problem": asdict(problem),
        "move_depth": len(witness.carriers),
        "readout_included": False,
        "return_home_required": return_home,
        "initially_idle": problem.initially_idle,
    }
    checks = {
        "independent_geometry": True,
        "semantic_validation": True,
        "actual_geometry_clifford_tableau": True,
        "cz_gates": 24,
        "cz_layers": 4,
        "measurements": 0,
        "free_initial_layout": True,
        "move_depth": len(witness.carriers),
        "final_home_restored": result.exit_state == entry,
    }
    return document, checks

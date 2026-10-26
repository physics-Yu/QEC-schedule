"""Two-participant CNOT admission and exact Clifford action from atom geometry."""

import json
from dataclasses import replace
from itertools import product
from pathlib import Path

import pytest
import stim
from nadit_physical_compiler.architectures import generate
from nadit_physical_compiler.device import Position, loads_device
from nadit_physical_compiler.state import AtomLayout, AtomState, SLMHolder

from modules.codes._support import atom_template
from modules.codes._support.atom_template import BindingRejected
from modules.codes.contracts.component import ComponentBinding, InvocationContext
from modules.codes.rotated_surface_d3.components.transversal import (
    CONTROL_ORIGIN,
    CONTROL_REFERENCE_HOMES,
    TARGET_ORIGIN,
    TARGET_REFERENCE_HOMES,
    TransversalCNOTComponent,
)
from modules.codes.rotated_surface_d3.definition import CHECKS, REFERENCE_COORDINATES
from modules.codes.rotated_surface_d3.tests.quantum_checks import (
    action_stim,
    pauli,
    source_stim,
)


@pytest.fixture(scope="module")
def pair_device():
    path = Path(__file__).parents[1] / "configs/nonzoned_cnot_reference.json"
    spec = json.loads(path.read_text())
    return loads_device(json.dumps(generate(spec["family"], spec["params"])))


@pytest.fixture(scope="module")
def pair_template(pair_device):
    return TransversalCNOTComponent().compile(
        pair_device,
        control_home_sites=CONTROL_REFERENCE_HOMES,
        target_home_sites=TARGET_REFERENCE_HOMES,
        control_origin=CONTROL_ORIGIN,
        target_origin=TARGET_ORIGIN,
        aod_id="transport",
    )


def bindings(shift=CONTROL_ORIGIN):
    return (
        ComponentBinding("control-A", shift, tuple(range(100, 117)), "transport"),
        ComponentBinding(
            "target-B",
            Position(shift.x + 100, shift.y),
            tuple(range(200, 217)),
            "transport",
        ),
    )


def world(device, participants):
    atoms = tuple(a for participant in participants for a in participant.atom_ids)
    homes = CONTROL_REFERENCE_HOMES + TARGET_REFERENCE_HOMES
    return AtomLayout(
        tuple(
            AtomState(a, device.site(s).position, SLMHolder(s))
            for a, s in zip(atoms, homes, strict=True)
        ),
        qubit_to_atom=atoms,
    )


def expand(template, device, shift=CONTROL_ORIGIN):
    participants = bindings(shift)
    return template.bind(*participants).expand(
        InvocationContext(
            "two-block-cnot", 1200, 500, device, world(device, participants)
        )
    )


def circuits(expansion, device):
    source, source_ids = source_stim(TransversalCNOTComponent().source_qasm)
    actual, actual_ids = action_stim(expansion, device)
    source.append("I", [33])
    actual.append("I", [33])
    assert source_ids == actual_ids == []
    return source, actual


def logicals(offset):
    x = pauli("X", tuple(offset + q for q in (0, 3, 6)), 34)
    z = pauli("Z", tuple(offset + q for q in (0, 1, 2)), 34)
    return {"X": x, "Z": z, "Y": 1j * x * z}


def test_two_participant_contract_and_no_implicit_round(pair_template, pair_device):
    component = TransversalCNOTComponent()
    assert component.source_qasm.count("cx ") == 9
    assert "reset " not in component.source_qasm
    assert "measure " not in component.source_qasm
    assert (
        len(component.description.roles) == len(set(component.description.roles)) == 34
    )
    assert pair_template.relative_displacement == Position(100, 0)
    output = expand(pair_template, pair_device)
    assert output.participant_bindings == bindings()
    assert output.exit_participant_bindings == bindings()
    assert output.exit_binding is None
    assert output.entry_state == output.exit_state
    assert output.measurements == output.correction_relations == ()
    assert output.action_end_us == output.results_ready_us
    assert output.acceptance_status == "not_applicable"
    assert len(output.output_syndrome_parities) == 16


def test_exact_source_and_atom_conjugation(pair_template, pair_device):
    output = expand(pair_template, pair_device)
    source, actual = circuits(output, pair_device)
    expected = stim.Tableau.from_circuit(source)
    observed = stim.Tableau.from_circuit(actual)
    assert observed == expected
    control, target = logicals(0), logicals(17)
    assert observed(control["X"]) == control["X"] * target["X"]
    assert observed(control["Z"]) == control["Z"]
    assert observed(target["X"]) == target["X"]
    assert observed(target["Z"]) == control["Z"] * target["Z"]
    named_checks = {}
    for index, (basis, support) in enumerate(CHECKS):
        a = pauli(basis, support, 34)
        b = pauli(basis, tuple(17 + q for q in support), 34)
        named_checks[f"control.{basis}{index % 4}"] = a
        named_checks[f"target.{basis}{index % 4}"] = b
        assert observed(a) == (a * b if basis == "X" else a)
        assert observed(b) == (a * b if basis == "Z" else b)
    relations = dict(output.output_syndrome_parities)
    assert relations.keys() == named_checks.keys()
    inverse = observed.inverse()
    for port, inputs in relations.items():
        inferred_input_observable = stim.PauliString(34)
        for reference in inputs:
            assert reference.startswith("input.")
            inferred_input_observable *= named_checks[reference.removeprefix("input.")]
        assert inverse(named_checks[port]) == inferred_input_observable
    for wire in (*range(9, 17), *range(26, 34)):
        for basis in "XZ":
            spectator = pauli(basis, (wire,), 34)
            assert observed(spectator) == spectator


def test_36_encoded_inputs_and_bell_state(pair_template, pair_device):
    output = expand(pair_template, pair_device)
    source, actual = circuits(output, pair_device)
    transform = stim.Tableau.from_circuit(source)
    control, target = logicals(0), logicals(17)
    generators = [
        pauli(basis, tuple(offset + q for q in support), 34)
        for offset in (0, 17)
        for basis, support in CHECKS
    ] + [pauli("Z", (q,), 34) for q in (*range(9, 17), *range(26, 34))]
    for axis_a, sign_a, axis_b, sign_b in product("XYZ", (-1, 1), "XYZ", (-1, 1)):
        prepared = stim.Tableau.from_stabilizers(
            [*generators, sign_a * control[axis_a], sign_b * target[axis_b]]
        )
        expected = stim.TableauSimulator()
        expected.set_inverse_tableau(
            stim.Tableau.from_stabilizers(
                [transform(p) for p in prepared.to_stabilizers()]
            ).inverse()
        )
        for circuit in (source, actual):
            sim = stim.TableauSimulator()
            sim.set_inverse_tableau(prepared.inverse())
            sim.do(circuit)
            assert sim.canonical_stabilizers() == expected.canonical_stabilizers()
            if (axis_a, sign_a, axis_b, sign_b) == ("X", 1, "Z", 1):
                assert sim.peek_observable_expectation(control["X"] * target["X"]) == 1
                assert sim.peek_observable_expectation(control["Z"] * target["Z"]) == 1
                assert sim.peek_observable_expectation(control["Z"]) == 0
                assert sim.peek_observable_expectation(target["X"]) == 0


def test_independent_identity_and_geometry_rejections(pair_template):
    control, target = bindings()
    for changed in (
        replace(target, block_id=control.block_id),
        replace(target, atom_ids=control.atom_ids),
        replace(target, atom_ids=target.atom_ids[:-1]),
        replace(target, aod_id="other-aod"),
        replace(target, origin=Position(110, 0)),
    ):
        with pytest.raises(BindingRejected):
            pair_template.bind(control, changed)
    with pytest.raises(ValueError):
        TransversalCNOTComponent(name="different_protocol")


def test_whole_pair_translation_reuses_actions_without_compile(
    pair_template, pair_device, monkeypatch
):
    shift = Position(125, 230)

    def region(bounds):
        return replace(
            bounds,
            x_min=bounds.x_min + shift.x,
            x_max=bounds.x_max + shift.x,
            y_min=bounds.y_min + shift.y,
            y_max=bounds.y_max + shift.y,
        )

    moved_device = replace(
        pair_device,
        zones=tuple(
            replace(zone, bounds=region(zone.bounds)) for zone in pair_device.zones
        ),
        slm_sites=tuple(
            replace(
                site,
                position=Position(site.position.x + shift.x, site.position.y + shift.y),
            )
            for site in pair_device.slm_sites
        ),
        aods=tuple(
            replace(aod, workspace=region(aod.workspace)) for aod in pair_device.aods
        ),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Joint binding and expansion must not compile.")

    monkeypatch.setattr(atom_template, "compile_physical", forbidden)
    original = expand(pair_template, pair_device)
    moved = expand(pair_template, moved_device, shift)
    assert moved.exit_state == moved.entry_state
    assert moved.participant_bindings == bindings(shift)
    assert stim.Tableau.from_circuit(
        circuits(original, pair_device)[1]
    ) == stim.Tableau.from_circuit(circuits(moved, moved_device)[1])


def test_compile_rejects_nonmatching_local_layout(pair_device):
    target_homes = list(TARGET_REFERENCE_HOMES)
    target_homes[0], target_homes[1] = target_homes[1], target_homes[0]
    with pytest.raises(ValueError, match="local layout"):
        TransversalCNOTComponent().compile(
            pair_device,
            control_home_sites=CONTROL_REFERENCE_HOMES,
            target_home_sites=tuple(target_homes),
            control_origin=CONTROL_ORIGIN,
            target_origin=TARGET_ORIGIN,
            aod_id="transport",
        )


def test_other_relative_position_requires_explicit_compilation(
    pair_device, pair_template
):
    target_homes = tuple(f"home_r{y}_c{x + 8}" for x, y in REFERENCE_COORDINATES)
    control, target = bindings()
    target = replace(target, origin=Position(80, 0))
    with pytest.raises(BindingRejected, match="explicitly compile"):
        pair_template.bind(control, target)
    compiled = TransversalCNOTComponent().compile(
        pair_device,
        control_home_sites=CONTROL_REFERENCE_HOMES,
        target_home_sites=target_homes,
        control_origin=CONTROL_ORIGIN,
        target_origin=target.origin,
        aod_id="transport",
    )
    ids = control.atom_ids + target.atom_ids
    homes = CONTROL_REFERENCE_HOMES + target_homes
    entry = AtomLayout(
        tuple(
            AtomState(atom, pair_device.site(site).position, SLMHolder(site))
            for atom, site in zip(ids, homes, strict=True)
        ),
        qubit_to_atom=ids,
    )
    output = compiled.bind(control, target).expand(
        InvocationContext("cnot-at-80", 0, 500, pair_device, entry)
    )
    assert compiled.relative_displacement == Position(80, 0)
    assert output.participant_bindings == (control, target)
    assert output.exit_state == entry
    source, actual = circuits(output, pair_device)
    assert stim.Tableau.from_circuit(source) == stim.Tableau.from_circuit(actual)

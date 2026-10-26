"""Destructive logical readout, retained atoms, and ideal parity interpretation."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
import stim
from nadit_physical_compiler.architectures import generate
from nadit_physical_compiler.atom_ir import Measure, Reset
from nadit_physical_compiler.device import Position, loads_device
from nadit_physical_compiler.state import AtomLayout, AtomState, SLMHolder

from modules.codes._support import atom_template
from modules.codes.contracts.component import (
    ComponentBinding,
    InvocationContext,
    validate_sequence,
)
from modules.codes.rotated_surface_d3.components import get_component
from modules.codes.rotated_surface_d3.components.measurement import (
    LogicalMeasurementComponent,
    read_ideal_observable,
)
from modules.codes.rotated_surface_d3.definition import CHECKS, REFERENCE_HOMES, ROLES
from modules.codes.rotated_surface_d3.tests.quantum_checks import (
    action_stim,
    pauli,
    source_stim,
    unitary,
)

NAMES = ("logical_mz", "logical_mx")
SUPPORTS = {"logical_mz": (0, 1, 2), "logical_mx": (0, 3, 6)}


@pytest.fixture(scope="module")
def device():
    path = Path(__file__).parents[1] / "configs/nonzoned_reference.json"
    spec = json.loads(path.read_text())
    return loads_device(json.dumps(generate(spec["family"], spec["params"])))


@pytest.fixture(scope="module")
def templates(device):
    return {
        name: LogicalMeasurementComponent(name).compile(
            device,
            home_sites=REFERENCE_HOMES,
            origin=Position(0, 0),
            aod_id="transport",
        )
        for name in NAMES
    }


def expand(template, device, *, origin=None, start=125, base=500):
    atoms = tuple(range(200, 217))
    world = AtomLayout(
        tuple(
            AtomState(a, device.site(s).position, SLMHolder(s))
            for a, s in zip(atoms, REFERENCE_HOMES, strict=True)
        ),
        qubit_to_atom=atoms,
    )
    return template.bind(
        ComponentBinding("W2", origin or Position(0, 0), atoms, "transport")
    ).expand(InvocationContext("factory/final/W2", start, base, device, world))


@pytest.mark.parametrize("name", NAMES)
def test_contract_and_real_readout_preserve_atoms_not_encoding(name, templates, device):
    component = LogicalMeasurementComponent(name)
    source = component.source_qasm
    assert source.count("= measure") == 9
    assert source.count("h q[") == (9 if name == "logical_mx" else 0)
    assert "reset" not in source and "cx " not in source
    assert component.description.roles == ROLES
    assert component.description.measurements == ROLES[:9]
    spec = component.measurement_spec
    assert spec.physical_ports == ROLES[:9]
    assert spec.logical_parity_ports == tuple(f"data[{q}]" for q in SUPPORTS[name])
    assert len(spec.same_basis_check_parities) == 4
    expected_checks = tuple(
        (f"{basis}{i % 4}", tuple(f"data[{q}]" for q in support))
        for i, (basis, support) in enumerate(CHECKS)
        if basis == spec.basis
    )
    assert spec.same_basis_check_parities == expected_checks
    result = expand(templates[name], device)
    assert result.entry_state == result.exit_state
    assert result.exit_binding.atom_ids == result.wire_atoms
    assert len(result.exit_state.atoms) == 17
    assert not result.correction_relations and not result.acceptance_conditions
    assert all(
        m.value is None and m.expected_ideal_value is None for m in result.measurements
    )
    read_atoms = []
    for step in result.program.steps:
        for action in step.actions:
            assert not isinstance(action, Reset)
            if isinstance(action, Measure):
                read_atoms.extend(atom for atom, _ in action.results)
    assert sorted(read_atoms) == list(result.wire_atoms[:9])
    assert result.results_ready_us > result.action_end_us


@pytest.mark.parametrize("name", NAMES)
def test_source_and_atom_measurement_projectors_exactly_match(name, templates, device):
    """Back-propagate every measured Z through actual pulses, for all input states."""
    expansion = expand(templates[name], device)
    source, source_ports = source_stim(LogicalMeasurementComponent(name).source_qasm)
    actual, actual_ids = action_stim(expansion, device)
    assert source_ports == list(range(9))
    ports_by_id = {
        m.result.measurement_id: i for i, m in enumerate(expansion.measurements)
    }
    actual_ports = [ports_by_id[mid] for mid in actual_ids]
    assert sorted(actual_ports) == list(range(9))
    source_tableau, actual_tableau = unitary(source), unitary(actual)
    assert source_tableau == actual_tableau
    basis = name[-1].upper()
    for table in (source_tableau, actual_tableau):
        inverse = table.inverse()
        for q in range(9):
            assert inverse.z_output(q) == pauli(basis, (q,))
        observable = stim.PauliString(17)
        for q in SUPPORTS[name]:
            observable *= inverse.z_output(q)
        assert observable == pauli(basis, SUPPORTS[name])
        for q in range(9, 17):
            assert table.x_output(q) == pauli("X", (q,))
            assert table.z_output(q) == pauli("Z", (q,))


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("input_basis", "XYZ")
@pytest.mark.parametrize("sign", (-1, 1))
def test_encoded_logical_distribution_including_noncanonical_sector(
    name, input_basis, sign, templates, device
):
    expansion = expand(templates[name], device)
    source, _ = source_stim(LogicalMeasurementComponent(name).source_qasm)
    actual, actual_ids = action_stim(expansion, device)
    logical_x, logical_z = pauli("X", (0, 3, 6)), pauli("Z", (0, 1, 2))
    logical = {"X": logical_x, "Y": 1j * logical_x * logical_z, "Z": logical_z}
    for sector in ((1,) * 8, (-1, 1, -1, 1, 1, -1, 1, -1)):
        prepared = stim.Tableau.from_stabilizers(
            [
                *(
                    value * pauli(b, support)
                    for value, (b, support) in zip(sector, CHECKS, strict=True)
                ),
                sign * logical[input_basis],
                *(pauli("Z", (q,)) for q in range(9, 17)),
            ]
        )
        # Exact Born expectation gives the parity distribution, without finite shots.
        for circuit in (source, actual):
            sim = stim.TableauSimulator()
            sim.set_inverse_tableau(prepared.inverse())
            sim.do_tableau(unitary(circuit), list(range(17)))
            expectation = sim.peek_observable_expectation(pauli("Z", SUPPORTS[name]))
            assert expectation == (sign if input_basis == name[-1].upper() else 0)
        # Also execute actual readout to check physical-ID-to-port interpretation.
        sim = stim.TableauSimulator(seed=73)
        sim.set_inverse_tableau(prepared.inverse())
        sim.do(actual)
        measured = expansion.with_results(
            dict(
                zip(actual_ids, map(int, sim.current_measurement_record()), strict=True)
            )
        )
        observable = read_ideal_observable(measured, at_us=measured.results_ready_us)
        if input_basis == name[-1].upper():
            assert observable.value == (1 - sign) // 2


@pytest.mark.parametrize("name", NAMES)
def test_observable_identity_ready_time_and_pending_values(name, templates, device):
    expansion = expand(templates[name], device)
    pending = read_ideal_observable(expansion, at_us=expansion.results_ready_us)
    assert pending.value is None and pending.evidence == "ideal_parity"
    assert pending.invocation_id == expansion.invocation_id and pending.block_id == "W2"
    support = SUPPORTS[name]
    assert pending.result_refs == tuple(
        expansion.measurements[q].result for q in support
    )
    assert pending.available_at_us == max(
        expansion.measurements[q].available_at_us for q in support
    )
    partial = expansion.with_results({500 + support[0]: 1})
    assert (
        read_ideal_observable(partial, at_us=expansion.results_ready_us).value is None
    )
    resolved = partial.with_results({500 + q: 0 for q in support[1:]})
    assert (
        read_ideal_observable(resolved, at_us=pending.available_at_us - 0.1).value
        is None
    )
    assert read_ideal_observable(resolved, at_us=pending.available_at_us).value == 1
    assert all(m.value is None for m in expansion.measurements)
    for invalid in (-1, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="time"):
            read_ideal_observable(resolved, at_us=invalid)


@pytest.mark.parametrize("name", NAMES)
def test_relative_binding_does_not_recompile(name, templates, device, monkeypatch):
    shift = Position(115, 210)

    def region(r):
        return replace(
            r,
            x_min=r.x_min + shift.x,
            x_max=r.x_max + shift.x,
            y_min=r.y_min + shift.y,
            y_max=r.y_max + shift.y,
        )

    moved_device = replace(
        device,
        zones=tuple(replace(z, bounds=region(z.bounds)) for z in device.zones),
        slm_sites=tuple(
            replace(
                s, position=Position(s.position.x + shift.x, s.position.y + shift.y)
            )
            for s in device.slm_sites
        ),
        aods=tuple(replace(a, workspace=region(a.workspace)) for a in device.aods),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Measurement expansion must not compile")

    monkeypatch.setattr(atom_template, "compile_physical", forbidden)
    original = expand(templates[name], device)
    moved = expand(templates[name], moved_device, origin=shift, start=900, base=700)
    assert moved.exit_state == moved.entry_state
    assert moved.exit_binding.origin == shift
    assert tuple(m.result.measurement_id for m in moved.measurements) == tuple(
        range(700, 709)
    )
    assert [m.available_at_us - moved.start_us for m in moved.measurements] == [
        m.available_at_us - original.start_us for m in original.measurements
    ]


@pytest.mark.parametrize("name", NAMES)
def test_retained_readout_and_capacity_are_explicit(name, templates, device):
    destructive = replace(device, readout=replace(device.readout, retain_atoms=False))
    with pytest.raises(ValueError, match="retain"):
        LogicalMeasurementComponent(name).compile(
            destructive,
            home_sites=REFERENCE_HOMES,
            origin=Position(0, 0),
            aod_id="transport",
        )
    small = replace(device, readout=replace(device.readout, max_atoms=1))
    with pytest.raises(atom_template.BindingRejected):
        expand(templates[name], small)
    template = LogicalMeasurementComponent(name).compile(
        small, home_sites=REFERENCE_HOMES, origin=Position(0, 0), aod_id="transport"
    )
    measured = expand(template, small)
    assert (
        len(measured.measurements) == 9 and measured.entry_state == measured.exit_state
    )


@pytest.mark.parametrize("name", NAMES)
def test_next_preparation_reuses_physical_exit_without_erasing_old_results(
    name, templates, device
):
    measured = expand(templates[name], device)
    prep = get_component("initialize_0").compile(
        device, home_sites=REFERENCE_HOMES, origin=Position(0, 0), aod_id="transport"
    )
    following = prep.bind(measured.exit_binding).expand(
        InvocationContext(
            "factory/next-epoch/W2",
            measured.action_end_us,
            600,
            device,
            measured.exit_state,
        )
    )
    validate_sequence((measured, following))
    assert following.start_us < measured.results_ready_us
    assert all(m.value is None for m in measured.measurements)
    assert {m.result for m in measured.measurements}.isdisjoint(
        m.result for m in following.measurements
    )
    resolved = measured.with_results({500 + q: q % 2 for q in range(9)})
    assert (
        read_ideal_observable(resolved, at_us=resolved.results_ready_us).value
        is not None
    )
    assert all(m.value is None for m in following.measurements)


def test_invalid_component_and_expansion(device):
    with pytest.raises(ValueError):
        LogicalMeasurementComponent("logical_my")
    template = get_component("initialize_plus").compile(
        device, home_sites=REFERENCE_HOMES, origin=Position(0, 0), aod_id="transport"
    )
    with pytest.raises(ValueError, match="logical measurement"):
        read_ideal_observable(expand(template, device), at_us=1e9)

"""Logical phase protocols, all measured branches, and compiled quantum actions."""

import json
from itertools import product
from pathlib import Path

import pytest
from nadit_physical_compiler.architectures import generate
from nadit_physical_compiler.device import Position, loads_device

from modules.codes.rotated_surface_d3.components.circuits import se_layers, source_qasm
from modules.codes.rotated_surface_d3.components.phase import (
    EXIT_SYNDROME_PARITIES,
    MEASURED_INPUT_PARITIES,
    PhaseComponent,
    phase_se_layers,
)
from modules.codes.rotated_surface_d3.definition import CHECKS, REFERENCE_HOMES, ROLES
from modules.codes.rotated_surface_d3.tests.phase_checks import (
    apply_terms,
    branches,
    data_signature,
    prepared,
    source_circuit,
    translated_expansion,
)
from modules.codes.rotated_surface_d3.tests.quantum_checks import (
    action_stim,
    pauli,
    postselect,
    unitary,
)
from modules.codes.rotated_surface_d3.tests.test_components import expand


@pytest.fixture(scope="module")
def phase_device():
    spec = json.loads(
        (Path(__file__).parents[1] / "configs/nonzoned_reference.json").read_text()
    )
    return loads_device(json.dumps(generate(spec["family"], spec["params"])))


@pytest.fixture(scope="module")
def phase_templates(phase_device):
    return {
        name: PhaseComponent(name).compile(
            phase_device,
            home_sites=REFERENCE_HOMES,
            origin=Position(0, 0),
            aod_id="transport",
        )
        for name in ("logical_s", "logical_sdag", "prepare_y")
    }


@pytest.mark.parametrize("name", ("logical_s", "logical_sdag"))
def test_canonical_phase_action(name):
    component = PhaseComponent(name)
    circuit, _ = source_circuit(component.source_qasm)
    x, z = pauli("X", (0, 3, 6)), pauli("Z", (0, 1, 2))
    y = 1j * x * z
    for sign in (-1, 1):
        for before, after in ((x, y), (y, -x), (z, z)):
            if name == "logical_sdag" and before != z:
                after = -after
            outputs = branches(circuit, prepared(sign * before))
            assert sum(p for _, _, p in outputs) == 1
            for sim, bits, _ in outputs:
                apply_terms(
                    sim,
                    component.correction_terms,
                    dict(zip(component.description.measurements, bits, strict=True)),
                )
                assert all(
                    sim.peek_observable_expectation(pauli(b, qs)) == 1
                    for b, qs in CHECKS
                )
                assert sim.peek_observable_expectation(sign * after) == 1


def test_unknown_phase_component_is_rejected():
    with pytest.raises(ValueError):
        PhaseComponent("s_transversal_on_data")


def test_se_protocols_are_separate_and_y_is_approved_composition():
    assert phase_se_layers() == (
        ((10, 2), (11, 4), (12, 8), (3, 13), (1, 14), (5, 15)),
        ((10, 1), (11, 3), (12, 7), (6, 13), (4, 14), (8, 15)),
        ((9, 1), (10, 5), (11, 7), (0, 14), (4, 15), (2, 16)),
        ((9, 0), (10, 4), (11, 6), (3, 14), (7, 15), (5, 16)),
    )
    assert se_layers() == (
        ((10, 1), (11, 3), (12, 7), (0, 14), (4, 15), (2, 16)),
        ((10, 2), (11, 4), (12, 8), (3, 14), (7, 15), (5, 16)),
        ((9, 0), (10, 4), (11, 6), (3, 13), (1, 14), (5, 15)),
        ((9, 1), (10, 5), (11, 7), (6, 13), (4, 14), (8, 15)),
    )
    y = PhaseComponent("prepare_y").source_qasm
    prefix = source_qasm("initialize_plus").replace("bit[8] m;", "bit[16] m;")
    assert y.startswith(prefix)
    assert y.count("cx ") == 48
    assert y.count("cz ") == 4
    assert y.count("= measure") == 16
    assert y.count("reset q[") == 25
    for name in ("logical_s", "logical_sdag"):
        qasm = PhaseComponent(name).source_qasm
        assert qasm.count("cx ") == 24
        assert qasm.count("cz ") == 4
        assert qasm.count("= measure") == 8
        assert qasm.count("reset q[") == 8


@pytest.mark.parametrize("name", ("logical_s", "logical_sdag"))
def test_all_input_sectors_and_local_output_relations(name):
    component = PhaseComponent(name)
    circuit, _ = source_circuit(component.source_qasm)
    x, z = pauli("X", (0, 3, 6)), pauli("Z", (0, 1, 2))
    y = 1j * x * z
    for signs in product((0, 1), repeat=8):
        incoming = dict(zip(ROLES[9:], signs, strict=True))
        expected_bits = tuple(
            sum(incoming[p] for p in factors) % 2
            for _, factors in MEASURED_INPUT_PARITIES
        )
        for before, after in ((x, y), (y, -x), (z, z)):
            if name == "logical_sdag" and before != z:
                after = -after
            outputs = branches(circuit, prepared(before, signs))
            assert len(outputs) == 1
            sim, bits, probability = outputs[0]
            assert bits == expected_bits
            assert probability == 1
            ports = dict(zip(component.description.measurements, bits, strict=True))
            expected_signs = tuple(
                sum(ports[p] for p in factors) % 2
                for _, factors in EXIT_SYNDROME_PARITIES
            )
            assert (
                tuple(
                    int(sim.peek_observable_expectation(pauli(b, qs)) < 0)
                    for b, qs in CHECKS
                )
                == expected_signs
            )
            assert sim.peek_observable_expectation(after) == 1
    assert component.correction_terms == ()


@pytest.mark.parametrize("name", ("logical_s", "logical_sdag"))
def test_phase_source_and_actual_atom_actions(name, phase_device, phase_templates):
    component = PhaseComponent(name)
    expansion = expand(phase_templates[name], phase_device)
    source, ports = source_circuit(component.source_qasm)
    actual, refs = action_stim(expansion, phase_device)
    assert ports == list(range(8))
    assert unitary(source) == unitary(actual)
    x, z = pauli("X", (0, 3, 6)), pauli("Z", (0, 1, 2))
    y = 1j * x * z
    for logical in (x, -x, y, -y, z, -z):
        for signs in ((0,) * 8, *((int(i == j) for i in range(8)) for j in range(8))):
            signs = tuple(signs)
            for sim, bits, probability in branches(source, prepared(logical, signs)):
                values = {100 + i: bit for i, bit in enumerate(bits)}
                observed, p_actual = postselect(
                    actual, [values[mid] for mid in refs], prepared(logical, signs)
                )
                assert probability == p_actual == 1
                assert sim.canonical_stabilizers() == observed.canonical_stabilizers()
    assert expansion.exit_state == expansion.entry_state
    assert len(expansion.measurements) == 8
    assert all(r.value is None for r in expansion.measurements)
    assert phase_templates[name].output_syndrome_parities == EXIT_SYNDROME_PARITIES
    assert expansion.output_syndrome_parities == EXIT_SYNDROME_PARITIES


def test_all_y_branches_source_and_actual_atom_actions(phase_device, phase_templates):
    component = PhaseComponent("prepare_y")
    expansion = expand(phase_templates[component.name], phase_device)
    source, ports = source_circuit(component.source_qasm)
    actual, refs = action_stim(expansion, phase_device)
    assert ports == list(range(16))
    outcomes = branches(source)
    assert len(outcomes) == 16
    assert sum(p for _, _, p in outcomes) == 1
    x, z = pauli("X", (0, 3, 6)), pauli("Z", (0, 1, 2))
    canonical = None
    for sim, bits, probability in outcomes:
        values = {100 + i: bit for i, bit in enumerate(bits)}
        observed, p_actual = postselect(actual, [values[mid] for mid in refs])
        assert probability == p_actual == 1 / 16
        assert sim.canonical_stabilizers() == observed.canonical_stabilizers()
        ports = dict(zip(component.description.measurements, bits, strict=True))
        apply_terms(observed, component.correction_terms, ports)
        assert all(
            observed.peek_observable_expectation(pauli(b, qs)) == 1 for b, qs in CHECKS
        )
        assert observed.peek_observable_expectation(1j * x * z) == 1
        if canonical is None:
            canonical = data_signature(observed)
        assert data_signature(observed) == canonical
    assert len(expansion.measurements) == 16
    assert len(expansion.correction_relations) == 4
    assert (
        expansion.measurements[8].available_at_us
        > expansion.measurements[0].available_at_us
    )
    assert expansion.exit_state == expansion.entry_state
    assert (
        phase_templates[component.name].output_syndrome_parities
        == EXIT_SYNDROME_PARITIES
    )
    assert expansion.output_syndrome_parities == EXIT_SYNDROME_PARITIES


@pytest.mark.parametrize("name", ("logical_s", "logical_sdag", "prepare_y"))
def test_phase_translation_and_no_cached_results(
    name, phase_device, phase_templates, monkeypatch
):
    import modules.codes._support.atom_template as backend
    from modules.codes._support.atom_binding import rebind_program

    def forbidden(*args, **kwargs):
        raise AssertionError("Expansion must not compile")

    monkeypatch.setattr(backend, "compile_physical", forbidden)
    first = expand(phase_templates[name], phase_device)
    translated, translated_device, renamed = translated_expansion(
        phase_templates[name], phase_device
    )
    normalized = rebind_program(
        translated.program,
        shift=Position(-120, -80),
        atoms={a: i for i, a in enumerate(translated.wire_atoms)},
        sites={v: k for k, v in renamed.items()},
        channels={"local": "local", "cz": "rydberg", "readout": "camera"},
        aod_id="transport",
        results={500 + i: 100 + i for i in range(len(first.measurements))},
    )
    assert normalized == first.program
    assert translated.exit_state == translated.entry_state
    assert unitary(action_stim(translated, translated_device)[0]) == unitary(
        action_stim(first, phase_device)[0]
    )
    other = expand(
        phase_templates[name], phase_device, invocation="later", base=700, start=9000
    )
    assert all(r.value is None for r in first.measurements + other.measurements)
    # Each invocation follows the complete global step clock. Adding 9000 to
    # already rounded local offsets is not bitwise equivalent in floating point.
    from nadit_physical_compiler.atom_ir import Measure

    for part in (first, other):
        cursor = part.start_us
        ready = {}
        for step in part.program.steps:
            for action in step.actions:
                if isinstance(action, Measure):
                    for _, result in action.results:
                        ready[result.measurement_id] = (
                            cursor
                            + action.duration_us
                            + phase_device.readout.latency_us
                        )
            cursor += step.duration_us
        assert {
            r.result.measurement_id: r.available_at_us for r in part.measurements
        } == ready
    assert not {r.result.measurement_id for r in first.measurements} & {
        r.result.measurement_id for r in other.measurements
    }


def test_sdag_restores_each_sector_and_logical_state():
    source_s, _ = source_circuit(PhaseComponent("logical_s").source_qasm)
    source_sdag, _ = source_circuit(PhaseComponent("logical_sdag").source_qasm)
    x, z = pauli("X", (0, 3, 6)), pauli("Z", (0, 1, 2))
    for signs in product((0, 1), repeat=8):
        for logical in (x, -x, 1j * x * z, -1j * x * z, z, -z):
            initial = prepared(logical, signs)
            expected = data_signature(initial)
            outputs = branches(source_s + source_sdag, initial)
            assert len(outputs) == 1
            observed, _, probability = outputs[0]
            assert probability == 1
            assert data_signature(observed) == expected

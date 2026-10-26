"""Local preparation corrections use real pulses without inventing syndrome bits."""

from dataclasses import replace
from math import sqrt

import numpy as np
import pytest

from modules.codes.contracts.component import InvocationContext
from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.rotated_surface_d3.components import get_component
from modules.codes.rotated_surface_d3.components.canonicalization import (
    CorrectionDecision,
    PreparationCanonicalization,
)
from modules.codes.rotated_surface_d3.components.injection import RawTComponent
from modules.codes.rotated_surface_d3.definition import CHECKS, REFERENCE_HOMES
from modules.codes.rotated_surface_d3.tests.dense_quantum import (
    action_state,
    data_branch,
    expectation,
    source_state,
)
from modules.codes.rotated_surface_d3.tests.quantum_checks import (
    action_stim,
    pauli,
    postselect,
    source_stim,
)
from modules.codes.rotated_surface_d3.tests.test_components import (
    device as device,  # noqa: PLC0414
)
from modules.codes.rotated_surface_d3.tests.test_components import expand
from modules.codes.rotated_surface_d3.tests.test_pauli import (
    actual_unitary,
    source_pauli_circuit,
)
from modules.codes.rotated_surface_d3.tests.test_raw_t_postselection_quantum import (
    sequence as sequence,  # noqa: PLC0414
)

PREPARATIONS = ("initialize_0", "initialize_plus", "raw_t_postselection")


def port(name):
    """Explicit ideal fixture; never an estimator for nonideal branch statistics."""
    return ProbabilityPort.from_dict(
        {
            "schema": "nadit.event_probability/1",
            "port_id": f"rotated_surface_d3.{name}.canonical_preparation",
            "protocol_id": f"rotated_surface_d3.{name}",
            "protocol_version": "2" if name == PREPARATIONS[2] else "1",
            "model": {
                "id": f"{name}.ideal_test",
                "kind": "test_fixture",
                "assumptions": ["Ideal joint preparation branches"],
                "parameters": {
                    "distance": 3,
                    "extra_rounds": 1,
                    "total_rounds": 2,
                    "round_policy": "explicit_control",
                }
                if name == PREPARATIONS[2]
                else {},
                "evidence": {},
            },
            "outcomes": [
                {
                    "key": f"class_{bits}",
                    "probability": 1 / 16,
                    "values": {"accepted": True, "byproduct_class": bits},
                    "branch_id": "deliver",
                }
                for bits in range(16)
            ],
            "branches": [{"key": "deliver", "transition": "deliver", "steps": []}],
        }
    )


@pytest.fixture(scope="module")
def corrections(device):
    from nadit_physical_compiler.device import Position

    return {
        name: PreparationCanonicalization(name).compile(
            device,
            probability_port=port(name),
            home_sites=REFERENCE_HOMES,
            origin=Position(0, 0),
            aod_id="transport",
        )
        for name in PREPARATIONS
    }


@pytest.fixture(scope="module")
def preparations(device, sequence):
    from nadit_physical_compiler.device import Position

    output = {"raw_t_postselection": sequence}
    for name in PREPARATIONS[:2]:
        template = get_component(name).compile(
            device,
            home_sites=REFERENCE_HOMES,
            origin=Position(0, 0),
            aod_id="transport",
        )
        output[name] = expand(template, device, invocation=name)
    return output


def decision_for(name, source, bits):
    identity = (
        source.parts[0].invocation_id
        if hasattr(source, "parts")
        else source.invocation_id
    )
    return CorrectionDecision(
        identity,
        f"{identity}/coarse-event",
        port(name).content_sha256,
        bits,
        True,
        source.results_ready_us,
    )


def context_for(source, device):
    return InvocationContext(
        "local-correction", source.results_ready_us, 10000, device, source.exit_state
    )


@pytest.mark.parametrize("name", PREPARATIONS[:2])
def test_all_initializer_branches_real_source_and_actions(
    name, corrections, preparations, device
):
    source = preparations[name]
    original, _ = source_stim(get_component(name).source_qasm)
    actual, _ = action_stim(source, device)
    logical = pauli("Z", (0, 1, 2)) if name == "initialize_0" else pauli("X", (0, 3, 6))
    for value in range(16):
        bits = tuple((value >> i) & 1 for i in range(4))
        observed = bits + (0,) * 4 if name == "initialize_0" else (0,) * 4 + bits
        source_sim, p_source = postselect(original, observed)
        atom_sim, p_atom = postselect(actual, observed)
        applied = corrections[name].expand_after(
            source, decision_for(name, source, value), context_for(source, device)
        )
        compiled = applied.expansion
        source_correction, _ = source_pauli_circuit(
            corrections[name].templates[value].source_qasm
        )
        atom_correction, results = action_stim(compiled, device)
        source_sim.do(source_correction)
        atom_sim.do(atom_correction)
        assert p_source == p_atom == 1 / 16
        assert source_sim.canonical_stabilizers() == atom_sim.canonical_stabilizers()
        assert atom_sim.peek_observable_expectation(logical) == 1
        assert all(
            atom_sim.peek_observable_expectation(pauli(b, qs)) == 1 for b, qs in CHECKS
        )
        assert not results and not compiled.measurements
        assert applied.source_measurements == source.measurements
        assert all(m.value is None for m in source.measurements)


def test_all_raw_branches_real_t_and_two_round_exit(corrections, preparations, device):
    from modules.codes.rotated_surface_d3.components.circuits import source_qasm
    from modules.codes.rotated_surface_d3.tests.injection_sequence_checks import (
        action_extraction,
        extract,
        source_extraction,
    )

    source = preparations["raw_t_postselection"]
    original = source_state(RawTComponent().source_qasm)
    actual = action_state(source.parts[0], device)
    se_source = source_extraction(source_qasm("se_round"))
    se_actions = action_extraction(source.parts[1], device)
    for value in range(16):
        bits = tuple((value >> i) & 1 for i in range(4))
        measured = (0, *bits[:2], 0, 0, *bits[2:], 0)
        source_data, _ = data_branch(original, dict(enumerate(measured)))
        atom_data, _ = data_branch(
            actual,
            dict(
                zip(
                    (m.result.measurement_id for m in source.parts[0].measurements),
                    measured,
                    strict=True,
                )
            ),
        )
        source_data, probability = data_branch(
            extract(se_source, source_data), dict(enumerate(measured))
        )
        atom_data, atom_probability = data_branch(
            extract(se_actions, atom_data),
            dict(
                zip(
                    (m.result.measurement_id for m in source.parts[1].measurements),
                    measured,
                    strict=True,
                )
            ),
        )
        assert probability == pytest.approx(1)
        assert atom_probability == pytest.approx(1)
        applied = corrections["raw_t_postselection"].expand_after(
            source,
            decision_for("raw_t_postselection", source, value),
            context_for(source, device),
        )
        _, source_matrix = source_pauli_circuit(
            corrections["raw_t_postselection"].templates[value].source_qasm
        )
        atom_matrix, _ = actual_unitary(applied.expansion)
        corrected_source, corrected_atom = (
            source_matrix @ source_data,
            atom_matrix @ atom_data,
        )
        assert abs(np.vdot(corrected_source, corrected_atom)) == pytest.approx(1)
        assert all(
            expectation(corrected_atom, [(q, b) for q in qs]) == pytest.approx(1)
            for b, qs in CHECKS
        )
        assert expectation(
            corrected_atom, ((0, "X"), (3, "X"), (6, "X"))
        ) == pytest.approx(1 / sqrt(2))
        assert expectation(
            corrected_atom, ((0, "Y"), (1, "Z"), (2, "Z"), (3, "X"), (6, "X"))
        ) == pytest.approx(1 / sqrt(2))
        assert source.acceptance_status == "pending"
        assert all(m.value is None for m in applied.source_measurements)


def test_guards_identity_time_hash_and_class(corrections, preparations, device):
    source = preparations["raw_t_postselection"]
    decision = decision_for("raw_t_postselection", source, 0)
    context = context_for(source, device)
    compiled = corrections["raw_t_postselection"]
    for changed in (
        replace(decision, source_invocation_id="wrong"),
        replace(decision, port_sha256="f" * 64),
        replace(decision, accepted=False, byproduct_class=None),
        replace(decision, available_at_us=context.start_us + 1),
    ):
        with pytest.raises(ValueError):
            compiled.expand_after(source, changed, context)
    with pytest.raises(ValueError):
        compiled.expand_after(
            source, decision, replace(context, start_us=context.start_us - 1)
        )
    with pytest.raises(ValueError):
        compiled.expand_after(source.parts[0], decision, context)
    rejected = source.with_results(
        {source.parts[0].measurements[0].result.measurement_id: 1}
    )
    with pytest.raises(ValueError):
        compiled.expand_after(rejected, decision, context)
    conflicting = source.with_results(
        {source.parts[0].measurements[1].result.measurement_id: 1}
    )
    with pytest.raises(ValueError):
        compiled.expand_after(conflicting, decision, context)
    for invalid in (-1, 16, True, 0.0):
        with pytest.raises(ValueError):
            replace(decision, byproduct_class=invalid)


def test_zero_class_is_a_real_empty_action_and_keeps_metadata(
    corrections, preparations, device
):
    source = preparations["initialize_plus"]
    applied = corrections["initialize_plus"].expand_after(
        source, decision_for("initialize_plus", source, 0), context_for(source, device)
    )
    assert applied.expansion.program.steps == ()
    assert applied.expansion.action_end_us == source.results_ready_us
    assert applied.expansion.exit_state == source.exit_state
    assert applied.expansion.exit_binding == source.exit_binding
    assert applied.expansion.correction_relations == ()
    assert applied.source_measurements == source.measurements


def test_known_later_round_bits_constrain_coarse_acceptance(
    corrections, preparations, device
):
    source = preparations["raw_t_postselection"]
    decision = decision_for("raw_t_postselection", source, 0)
    for index in (0, 1):
        known = source.with_results(
            {source.parts[1].measurements[index].result.measurement_id: 1}
        )
        assert known.acceptance_status == "pending"
        with pytest.raises(ValueError, match="contradicts"):
            corrections["raw_t_postselection"].expand_after(
                known, decision, context_for(source, device)
            )


def test_binding_relation_and_model_guards(corrections, preparations, device):
    source = preparations["initialize_0"]
    decision = decision_for("initialize_0", source, 3)
    context = context_for(source, device)
    compiled = corrections["initialize_0"]
    for changed in (
        replace(source, correction_relations=source.correction_relations[::-1]),
        replace(source, exit_binding=None),
        replace(source, exit_binding=replace(source.exit_binding, block_id="other")),
    ):
        with pytest.raises(ValueError):
            compiled.expand_after(changed, decision, context)
    with pytest.raises(ValueError):
        compiled.expand_after(
            source, decision, replace(context, invocation_id=source.invocation_id)
        )
    wrong_world = replace(context.world_state, qubit_to_atom=())
    with pytest.raises(ValueError):
        compiled.expand_after(
            source, decision, replace(context, world_state=wrong_world)
        )
    raw = preparations["raw_t_postselection"]
    raw_compiled = corrections["raw_t_postselection"]
    for field, change in (
        ("parameters", {"extra_rounds": 2}),
        ("evidence", {"template_content_sha256": "f" * 64}),
    ):
        document = port("raw_t_postselection").to_dict()
        document["model"][field] = change
        modified_port = ProbabilityPort.from_dict(document)
        modified = replace(raw_compiled, probability_port=modified_port)
        with pytest.raises(ValueError):
            modified.expand_after(
                raw,
                replace(
                    decision_for("raw_t_postselection", raw, 0),
                    port_sha256=modified_port.content_sha256,
                ),
                context_for(raw, device),
            )


def test_translated_template_reuse_has_no_compilation(corrections, device, monkeypatch):
    from nadit_physical_compiler.device import Position
    from nadit_physical_compiler.state import AtomLayout, AtomState, SLMHolder

    from modules.codes._support import atom_template
    from modules.codes.contracts.component import ComponentBinding

    initializer = get_component("initialize_plus").compile(
        device, home_sites=REFERENCE_HOMES, origin=Position(0, 0), aod_id="transport"
    )
    shift = Position(125, 230)

    def region(r):
        return replace(
            r,
            x_min=r.x_min + shift.x,
            x_max=r.x_max + shift.x,
            y_min=r.y_min + shift.y,
            y_max=r.y_max + shift.y,
        )

    translated = replace(
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
    ids = tuple(range(200, 217))
    entry = AtomLayout(
        tuple(
            AtomState(a, translated.site(s).position, SLMHolder(s))
            for a, s in zip(ids, REFERENCE_HOMES, strict=True)
        ),
        qubit_to_atom=ids,
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Correction expansion must reuse compiled templates")

    monkeypatch.setattr(atom_template, "compile_physical", forbidden)
    source = initializer.bind(
        ComponentBinding("shifted", shift, ids, "transport")
    ).expand(InvocationContext("shifted-prep", 1000, 700, translated, entry))
    applied = corrections["initialize_plus"].expand_after(
        source,
        decision_for("initialize_plus", source, 15),
        context_for(source, translated),
    )
    assert applied.expansion.exit_binding == source.exit_binding
    assert applied.expansion.exit_state == entry
    matrix, touched = actual_unitary(applied.expansion)
    assert touched == {0, 2, 6, 8}
    _, expected = source_pauli_circuit(
        corrections["initialize_plus"].templates[15].source_qasm
    )
    np.testing.assert_allclose(matrix, expected, atol=1e-12)


@pytest.mark.parametrize("invalid", ("raw_t", "se_round", "logical_x", ""))
def test_unsupported_preparation(invalid):
    with pytest.raises(ValueError):
        PreparationCanonicalization(invalid)


def test_port_mismatch_and_zero_probability_class(corrections, preparations, device):
    compiled = corrections["initialize_plus"]
    wrong = port("initialize_0")
    with pytest.raises(ValueError):
        replace(compiled, probability_port=wrong)
    with pytest.raises(ValueError):
        replace(compiled, templates=compiled.templates[:15])
    document = port("initialize_plus").to_dict()
    document["outcomes"][0]["probability"] = 0
    document["outcomes"][1]["probability"] = 2 / 16
    changed = ProbabilityPort.from_dict(document)
    compiled = replace(compiled, probability_port=changed)
    source = preparations["initialize_plus"]
    decision = replace(
        decision_for("initialize_plus", source, 0), port_sha256=changed.content_sha256
    )
    with pytest.raises(ValueError, match="possible"):
        compiled.expand_after(source, decision, context_for(source, device))

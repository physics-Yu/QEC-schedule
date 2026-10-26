"""Real component/event bridge without scheduler, clock, or fabricated bits."""

from dataclasses import replace

import numpy as np
import pytest
from nadit_physical_compiler.device import Position

from modules.codes._support import atom_template
from modules.codes.contracts.component import InvocationContext, validate_sequence
from modules.codes.rotated_surface_d3.components.canonicalization import (
    CorrectionDecision,
)
from modules.codes.rotated_surface_d3.protocols.factory_backend import (
    SurfaceFactoryBackend,
)
from modules.codes.rotated_surface_d3.protocols.factory_world import (
    FactoryWorldConfig,
    make_factory_world,
)
from modules.codes.rotated_surface_d3.protocols.raw_t_postselection import (
    RawTPostselectionExpansion,
)


@pytest.fixture(scope="module")
def factory():
    return make_factory_world()


@pytest.fixture(scope="module")
def backend(factory):
    return SurfaceFactoryBackend(factory.device)


def context(factory, name, *, start=0, base=100, world=None):
    return InvocationContext(
        name, start, base, factory.device, world or factory.world_state
    )


def decision(source, port, value=5):
    first = (
        source.parts[0] if isinstance(source, RawTPostselectionExpansion) else source
    )
    return CorrectionDecision(
        first.invocation_id,
        f"{first.invocation_id}/coarse",
        port.content_sha256,
        value,
        True,
        source.results_ready_us,
    )


def test_full_world_preparation_correction_consumption_and_feedback(backend, factory):
    work, resource = factory.bindings["W1"], factory.bindings["R"]
    prepare_work = backend.bind_call("initialize_plus", (work,))
    assert prepare_work.result_count == 8
    work_source = prepare_work.expand(context(factory, "W1/prepare"))
    work_port = backend.resolve_event("preparation:initialize_plus")
    corrected_work = backend.canonicalize(
        work_source,
        decision(work_source, work_port),
        context(
            factory,
            "W1/canonical",
            start=work_source.results_ready_us,
            base=108,
            world=work_source.exit_state,
        ),
        work_port,
    )
    prepare_resource = backend.bind_call(
        "rotated_surface_d3/raw_t_postselection", (resource,)
    )
    assert prepare_resource.result_count == 16
    raw = prepare_resource.expand(
        context(
            factory,
            "R/prepare",
            start=corrected_work.expansion.action_end_us,
            base=108,
            world=corrected_work.expansion.exit_state,
        )
    )
    assert isinstance(raw, RawTPostselectionExpansion) and len(raw.parts) == 2
    assert raw.parts[0].invocation_id == "R/prepare/round[0]"
    resource_port = backend.resolve_event("preparation:raw_t_postselection")
    canonical = backend.bind_canonicalization(
        "raw_t_postselection", raw, decision(raw, resource_port, 9), resource_port
    )
    assert canonical.result_count == 0
    corrected_resource = canonical.expand(
        context(
            factory,
            "R/canonical",
            start=raw.results_ready_us,
            base=124,
            world=raw.exit_state,
        )
    )
    cx_call = backend.bind_call("transversal_cnot", (work, resource))
    assert cx_call.result_count == 0
    cx = cx_call.expand(
        context(
            factory,
            "consume/cx",
            start=corrected_resource.expansion.action_end_us,
            base=124,
            world=corrected_resource.expansion.exit_state,
        )
    )
    readout = backend.bind_call("logical_mz", (resource,))
    assert readout.result_count == 9
    measured = readout.expand(
        context(
            factory, "consume/mz", start=cx.action_end_us, base=124, world=cx.exit_state
        )
    )
    phase = backend.bind_call("logical_s", (work,)).expand(
        context(
            factory,
            "consume/m1/s",
            start=measured.results_ready_us,
            base=133,
            world=measured.exit_state,
        )
    )
    parts = (
        work_source,
        corrected_work.expansion,
        *raw.parts,
        corrected_resource.expansion,
        cx,
        measured,
        phase,
    )
    validate_sequence(parts)
    for part in parts:
        assert len(part.exit_state.atoms) == 102
        assert part.exit_state == factory.world_state
        assert all(result.value is None for result in part.measurements)
    assert corrected_resource.source_measurements == raw.measurements
    assert corrected_work.source_measurements == work_source.measurements
    assert cx.participant_bindings == (work, resource)


def test_cache_contains_templates_without_invocation_results(
    backend, factory, monkeypatch
):
    binding = factory.bindings["W3"]
    first = backend.bind_call("logical_mx", (binding,))

    def forbidden(*args, **kwargs):
        raise AssertionError("Immutable compiled template should be reused")

    monkeypatch.setattr(atom_template, "compile_physical", forbidden)
    second = backend.bind_call("rotated_surface_d3/logical_mx", (binding,))
    a = first.expand(context(factory, "a", base=800))
    b = second.expand(context(factory, "b", base=900, start=10000))
    assert first.expander.template is second.expander.template
    assert a.invocation_id != b.invocation_id
    assert {m.result for m in a.measurements}.isdisjoint(
        m.result for m in b.measurements
    )
    assert all(m.value is None for m in a.measurements + b.measurements)
    assert (
        b.measurements[0].available_at_us - a.measurements[0].available_at_us == 10000
    )


def test_shifted_real_homes_and_multiple_aod_inventory():
    shifted = make_factory_world(
        FactoryWorldConfig(
            origin=Position(200, -30), atom_id_base=300, aod_ids=("primary", "spare")
        )
    )
    backend = SurfaceFactoryBackend(shifted.device)
    binding = replace(shifted.bindings["W5"], aod_id="spare")
    expansion = backend.bind_call("logical_mx", (binding,)).expand(
        context(shifted, "shifted")
    )
    assert expansion.exit_binding == binding
    assert expansion.exit_state == shifted.world_state
    assert len(expansion.exit_state.atoms) == 102
    assert tuple(m.atom_id for m in expansion.measurements) == binding.atom_ids[:9]


def test_multi_round_raw_has_exact_result_reservation(backend, factory):
    call = backend.bind_call(
        "raw_t_postselection", (factory.bindings["R"],), (("extra_rounds", 2),)
    )
    assert call.result_count == 24
    output = call.expand(context(factory, "three-rounds", base=5000))
    assert len(output.parts) == 3
    assert tuple(m.result.measurement_id for m in output.measurements) == tuple(
        range(5000, 5024)
    )
    with pytest.raises(ValueError, match="round"):
        backend.resolve_event("preparation:raw_t_postselection", {"extra_rounds": 2})


def test_canonicalization_is_gated_by_source_and_event_readiness(backend, factory):
    source = backend.bind_call("initialize_0", (factory.bindings["W2"],)).expand(
        context(factory, "zero")
    )
    port = backend.resolve_event("preparation:initialize_0")
    chosen = decision(source, port, 1)
    bound = backend.bind_canonicalization("initialize_0", source, chosen, port)
    with pytest.raises(ValueError, match="readiness"):
        bound.expand(
            context(
                factory,
                "too-early",
                start=source.results_ready_us - 1,
                world=source.exit_state,
            )
        )
    with pytest.raises(ValueError, match="source"):
        backend.bind_canonicalization(
            "initialize_plus",
            source,
            chosen,
            backend.resolve_event("preparation:initialize_plus"),
        ).expand(
            context(
                factory,
                "wrong-prep",
                start=source.results_ready_us,
                world=source.exit_state,
            )
        )


def test_code_owned_decision_factory_hides_raw_structure_and_class_rules(
    backend, factory
):
    source = backend.bind_call("raw_t_postselection", (factory.bindings["R"],)).expand(
        context(factory, "opaque-source")
    )
    port = backend.resolve_event("preparation:raw_t_postselection")
    selected = backend.correction_decision(
        source,
        event_id="chosen-prepare-event",
        probability_port=port,
        values={"accepted": True, "byproduct_class": 3},
        available_at_us=source.results_ready_us,
    )
    assert selected.source_invocation_id == source.parts[0].invocation_id
    assert selected.port_sha256 == port.content_sha256
    assert selected.byproduct_class == 3 and selected.accepted
    for bad in (
        {"accepted": True, "byproduct_class": 16},
        {"accepted": 1, "byproduct_class": 3},
        {"accepted": True, "byproduct_class": 3, "history": []},
    ):
        with pytest.raises(ValueError):
            backend.correction_decision(
                source,
                event_id="invalid",
                probability_port=port,
                values=bad,
                available_at_us=source.results_ready_us,
            )


@pytest.mark.parametrize(
    "selector",
    [
        "preparation:initialize_0",
        "preparation:initialize_plus",
        "preparation:raw_t_postselection",
        "t_consumption",
        "factory_mx",
    ],
)
def test_resolved_probability_models_are_code_owned_not_fixtures(backend, selector):
    port = backend.resolve_event(selector)
    assert port.to_dict()["model"]["kind"] == "ideal_exact"
    assert sum(outcome.probability for outcome in port.outcomes) == 1


def test_t_consumption_keeps_input_quality_in_the_magic_density(backend):
    p = 0.13
    port = backend.resolve_event("t_consumption", {"input_z_error": p})
    model = port.to_dict()["model"]
    assert model["parameters"]["input_z_error"] == p
    matrix = model["parameters"]["magic_density"]
    density = np.array(matrix["real"]) + 1j * np.array(matrix["imag"])
    expected = np.array(
        [
            [0.5, (1 - 2 * p) * np.exp(-1j * np.pi / 4) / 2],
            [(1 - 2 * p) * np.exp(1j * np.pi / 4) / 2, 0.5],
        ]
    )
    np.testing.assert_allclose(density, expected, atol=1e-15)
    assert tuple(o.probability for o in port.outcomes) == (0.5, 0.5)
    assert "Canonical T|+> resource" not in model["assumptions"]
    with pytest.raises(ValueError, match="together"):
        backend.resolve_event(
            "t_consumption", {"input_z_error": p, "magic_density": expected}
        )
    for bad in (-0.1, 1.1, True, float("nan")):
        with pytest.raises(ValueError):
            backend.resolve_event("t_consumption", {"input_z_error": bad})


def test_quality_helpers_feed_the_consumption_port_without_compiler_formula(backend):
    raw = backend.preparation_quality("raw_t_postselection", {"input_z_error": 0.04})
    port = backend.resolve_event("factory_mx", {"input_z_error": 0.04})
    output = backend.output_quality(port)
    assert raw["consumption_parameters"] == {"input_z_error": 0.04}
    assert output["consumption_parameters"]["input_z_error"] < 0.04
    consumption = backend.resolve_event(
        "t_consumption", output["consumption_parameters"]
    )
    assert (
        consumption.to_dict()["model"]["parameters"]["input_z_error"]
        == output["consumption_parameters"]["input_z_error"]
    )


@pytest.mark.parametrize(
    "selector,parameters",
    [
        ("factory_mx", {"history": []}),
        ("t_consumption", {"noise": {}}),
        ("preparation:initialize_plus", {"input_z_error": 0.1}),
        ("preparation:unknown", {}),
        ("unknown", {}),
    ],
)
def test_unknown_event_semantics_are_not_silently_ignored(
    backend, selector, parameters
):
    with pytest.raises(ValueError):
        backend.resolve_event(selector, parameters)


def test_invalid_binding_count_parameters_sites_and_device(backend, factory):
    binding = factory.bindings["W1"]
    cases = [
        ("initialize_plus", (), ()),
        ("transversal_cnot", (binding,), ()),
        ("logical_x", (binding, binding), ()),
        ("logical_x", (binding,), (("history", []),)),
        ("raw_t_postselection", (binding,), (("extra_rounds", 1), ("extra_rounds", 2))),
        ("raw_t_postselection", (binding,), (("extra_rounds", 0),)),
        ("other_code/logical_x", (binding,), ()),
    ]
    for name, participants, parameters in cases:
        with pytest.raises(ValueError):
            backend.bind_call(name, participants, parameters)
    invalid = replace(binding, site_ids=(("not-a-template-key", "home_r1_c1"),))
    with pytest.raises(ValueError):
        backend.bind_call("logical_x", (invalid,)).expand(context(factory, "bad-sites"))
    call = backend.bind_call("logical_x", (binding,))
    with pytest.raises(ValueError, match="Device"):
        call.expand(
            replace(
                context(factory, "wrong-device"),
                device=replace(factory.device, name="different"),
            )
        )

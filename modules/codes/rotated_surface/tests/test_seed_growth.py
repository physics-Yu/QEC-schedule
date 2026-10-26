"""Code-owned growth boundaries; stubs do not claim physical or quantum execution."""

from dataclasses import replace

import pytest
from nadit_physical_compiler.atom_ir import AtomProgram, AtomStep, Wait
from nadit_physical_compiler.device import Position
from nadit_physical_compiler.physical_ir import PhysicalDAG, ResultRef

from experiments.msd.standard import ExperimentSpec, build_world
from modules.codes.contracts.component import (
    ComponentBinding,
    ComponentDescription,
    ComponentExpansion,
    InvocationContext,
    MeasurementOutput,
)
from modules.codes.rotated_surface.components import SurfaceComponent
from modules.codes.rotated_surface.definition import definition
from modules.codes.rotated_surface.growth import GrowthComponent, injection_indices


def seed_fixture(distance=5):
    """Real geometry plus a synthetic source reference for protocol guard tests."""
    world = build_world(ExperimentSpec(distance))
    target = world.patch(0, "W1").binding
    indices = injection_indices(distance)
    seed = ComponentBinding(
        "canonical-d3-source",
        Position(target.origin.x, target.origin.y + 20 * (distance - 3)),
        tuple(target.atom_ids[i] for i in indices),
        target.aod_id,
    )
    source = ComponentExpansion(
        ComponentDescription(
            "rotated_surface_d3",
            "synthetic_source",
            "1",
            definition(3).roles,
            ("source_m",),
            (),
            (),
        ),
        "source",
        seed.block_id,
        0.0,
        world.state,
        world.state,
        seed.atom_ids,
        AtomProgram((AtomStep((Wait(duration_us=3),)),)),
        PhysicalDAG(17, 1, (), ()),
        (),
        (
            MeasurementOutput(
                "source", "source_m", ResultRef(9), seed.atom_ids[-1], 4, None
            ),
        ),
        (),
        ("synthetic_boundary_fixture_only",),
        seed,
        template_content_sha256="a" * 64,
    )
    outer = tuple(atom for i, atom in enumerate(target.atom_ids) if i not in indices)
    return world, target, source, outer


@pytest.mark.parametrize("distance", (5, 7))
def test_seed_growth_reuses_only_existing_deformation_and_ordinary_se_sources(distance):
    from modules.codes.rotated_surface.seed_growth import D3SeedGrowth

    protocol = D3SeedGrowth(distance)
    sources = protocol.component_sources
    assert protocol.growth_rounds == distance
    assert sources == (
        GrowthComponent(distance).source_qasm,
        *([SurfaceComponent("se_round", distance).source_qasm] * (distance - 1)),
    )
    assert all("\nt q[" not in source for source in sources)
    assert protocol.acceptance_ports == ()
    for q in injection_indices(distance)[:9]:
        assert f"reset q[{q}];" not in sources[0]
    assert len(protocol.description.measurements) == distance * (distance**2 - 1)
    assert "caller" in " ".join(protocol.description.entry_requirements).lower()


@pytest.mark.parametrize("distance,rounds", ((3, None), (4, None), (5, 1), (5, True)))
def test_seed_growth_rejects_unsupported_distance_or_incomplete_history(
    distance, rounds
):
    from modules.codes.rotated_surface.seed_growth import D3SeedGrowth

    with pytest.raises(ValueError):
        D3SeedGrowth(distance, growth_rounds=rounds)


@pytest.mark.parametrize(
    "fault", ("code", "roles", "binding", "source_hash", "validation")
)
def test_seed_input_rejects_invalid_source_references_without_claiming_canonical_truth(
    fault,
):
    from modules.codes.rotated_surface.seed_growth import D3SeedInput

    _, _, source, _ = seed_fixture()
    if fault == "code":
        source = replace(
            source,
            description=replace(source.description, code_id="rotated_surface_d5"),
        )
    elif fault == "roles":
        source = replace(
            source,
            description=replace(
                source.description, roles=tuple(reversed(source.description.roles))
            ),
        )
    elif fault == "binding":
        source = replace(source, exit_binding=None)
    elif fault == "source_hash":
        source = replace(source, template_content_sha256="missing")
    else:
        source = replace(source, validation_checks=())
    with pytest.raises(ValueError, match="D3_SEED"):
        D3SeedInput(source, provenance={"test_fixture": True})


def bound_fixture(monkeypatch, distance=5):
    from modules.codes.rotated_surface.seed_growth import D3SeedGrowth, D3SeedInput

    world, target, source, outer = seed_fixture(distance)
    compiled, contexts = [], []

    class StubTemplate:
        acceptance_ports = ()
        content_sha256 = "b" * 64

        def __init__(self, component, options):
            self.description = component.description
            self.home_sites = options["home_sites"]

        def bind(self, binding):
            description = self.description

            class Bound:
                def expand(self, context):
                    contexts.append(context)
                    code = definition(distance)
                    measurements = tuple(
                        MeasurementOutput(
                            context.invocation_id,
                            port,
                            ResultRef(context.result_id_base + i),
                            binding.atom_ids[code.data_count + i],
                            context.start_us + 7,
                            None,
                        )
                        for i, port in enumerate(code.check_roles)
                    )
                    return ComponentExpansion(
                        description,
                        context.invocation_id,
                        binding.block_id,
                        context.start_us,
                        context.world_state,
                        context.world_state,
                        binding.atom_ids,
                        AtomProgram((AtomStep((Wait(duration_us=5),)),)),
                        PhysicalDAG(code.atom_count, code.check_count, (), ()),
                        (),
                        measurements,
                        (),
                        ("synthetic_boundary_fixture_only",),
                        binding,
                        template_content_sha256="b" * 64,
                    )

            return Bound()

    def compile_stub(component, device, **options):
        assert device is world.device
        compiled.append(component.description.component_id)
        return StubTemplate(component, options)

    monkeypatch.setattr(GrowthComponent, "compile", compile_stub)
    monkeypatch.setattr(SurfaceComponent, "compile", compile_stub)
    template = D3SeedGrowth(distance).compile(
        world.device,
        home_sites=world.patch(0, "W1").home_sites,
        origin=target.origin,
        aod_id=target.aod_id,
    )
    provenance = {"scope": "synthetic_protocol_boundary", "source_chain": ["source"]}
    seed = D3SeedInput(source, provenance=provenance)
    provenance["source_chain"].append("caller-mutated")
    bound = template.bind(seed, target, outer_atom_ids=outer)
    return world, template, bound, compiled, contexts


def test_growth_continuation_keeps_source_world_id_stream_and_explicit_frame(
    monkeypatch,
):
    from modules.codes.rotated_surface.growth_decoder import GrowthFrame

    world, _template, bound, compiled, contexts = bound_fixture(monkeypatch)
    grown = bound.expand(
        InvocationContext("growth", 10, 100, world.device, world.state)
    )
    assert compiled == ["grow_from_d3", "se_round"]
    assert [context.invocation_id for context in contexts] == [
        f"growth/growth[{r}]" for r in range(5)
    ]
    assert [context.result_id_base for context in contexts] == [
        100 + 24 * r for r in range(5)
    ]
    assert [context.start_us for context in contexts] == [10 + 5 * r for r in range(5)]
    assert grown.exit_state == world.state
    assert grown.seed.provenance["source_chain"] == ["source"]
    assert "caller precondition" in grown.seed.to_dict()["input_state"]
    assert not hasattr(grown, "ready_for_use")
    assert not any(part.acceptance_conditions for part in grown.parts)
    with pytest.raises(ValueError, match="RESULTS_NOT_RECEIVED"):
        grown.decode(grown.results_ready_us)
    values = {
        m.result.measurement_id: int(i == 0)
        for part in grown.parts
        for i, m in enumerate(part.measurements)
    }
    received = grown.with_results(values)
    with pytest.raises(ValueError, match="RESULTS_NOT_READY"):
        received.decode(received.results_ready_us - 1)
    frame = received.decode(received.results_ready_us)
    assert isinstance(frame, GrowthFrame) and (frame.x or frame.z)
    assert received.exit_state == world.state
    assert all(m.value is None for part in grown.parts for m in part.measurements)
    with pytest.raises(ValueError, match="Unknown|UNKNOWN"):
        grown.with_results({9: 0})
    with pytest.raises(ValueError, match="previously received"):
        received.with_results({100: 0})


@pytest.mark.parametrize(
    "fault", ("seed_order", "target_order", "outer", "origin", "aod")
)
def test_growth_binding_rejects_wrong_roles_or_undeclared_outer_atoms(
    monkeypatch, fault
):
    from modules.codes.rotated_surface.seed_growth import D3SeedInput

    _world, template, bound, _compiled, contexts = bound_fixture(monkeypatch)
    seed, target, outer = bound.seed, bound.target_binding, bound.outer_atom_ids
    if fault == "seed_order":
        binding = replace(seed.binding, atom_ids=tuple(reversed(seed.binding.atom_ids)))
        seed = D3SeedInput(
            replace(seed.source, wire_atoms=binding.atom_ids, exit_binding=binding),
            provenance=seed.provenance,
        )
    elif fault == "target_order":
        target = replace(target, atom_ids=tuple(reversed(target.atom_ids)))
    elif fault == "outer":
        outer = outer[:-1]
    elif fault == "origin":
        target = replace(target, origin=Position(target.origin.x, target.origin.y + 10))
    else:
        target = replace(target, aod_id="another-aod")
    with pytest.raises(ValueError, match="D3_SEED_GROWTH"):
        template.bind(seed, target, outer_atom_ids=outer)
    assert contexts == []


@pytest.mark.parametrize(
    "fault", ("early", "source_invocation", "result_base", "world")
)
def test_growth_rejects_stale_context_before_expanding_any_primitive(
    monkeypatch, fault
):
    world, _template, bound, _compiled, contexts = bound_fixture(monkeypatch)
    context = InvocationContext("growth", 10, 100, world.device, world.state)
    if fault == "early":
        context = replace(context, start_us=3)
    elif fault == "source_invocation":
        context = replace(context, invocation_id="source")
    elif fault == "result_base":
        context = replace(context, result_id_base=9)
    else:
        context = replace(
            context,
            world_state=replace(
                world.state, qubit_to_atom=tuple(reversed(world.state.qubit_to_atom))
            ),
        )
    with pytest.raises(ValueError, match="D3_SEED_GROWTH"):
        bound.expand(context)
    assert contexts == []


def test_growth_checks_current_outer_atom_coordinates_before_any_primitive(monkeypatch):
    from modules.codes.rotated_surface.seed_growth import D3SeedInput

    world, _template, bound, _compiled, contexts = bound_fixture(monkeypatch)
    outside = world.patch(0, "W2").binding.atom_ids[0]
    replace_atom = bound.outer_atom_ids[0]
    target = replace(
        bound.target_binding,
        atom_ids=tuple(
            outside if atom == replace_atom else atom
            for atom in bound.target_binding.atom_ids
        ),
    )
    outer = tuple(
        outside if atom == replace_atom else atom for atom in bound.outer_atom_ids
    )
    altered = bound.template.bind(bound.seed, target, outer_atom_ids=outer)
    with pytest.raises(ValueError, match="CURRENT_ATOM_GEOMETRY"):
        altered.expand(InvocationContext("growth", 10, 100, world.device, world.state))
    assert contexts == []
    with pytest.raises(TypeError, match="COMPONENT_SOURCE"):
        D3SeedInput(object(), provenance={"fake_injection_event": True})


@pytest.mark.parametrize("fault", ("invocation", "duplicate_id", "old_source_id"))
def test_growth_result_history_rejects_forged_measurement_identity(monkeypatch, fault):
    world, _template, bound, _compiled, _contexts = bound_fixture(monkeypatch)
    grown = bound.expand(
        InvocationContext("growth", 10, 100, world.device, world.state)
    )
    first = grown.parts[0]
    measured = first.measurements[1]
    if fault == "invocation":
        measured = replace(measured, invocation_id="another-growth")
    else:
        measured = replace(
            measured, result=ResultRef(100 if fault == "duplicate_id" else 9)
        )
    first = replace(
        first, measurements=(first.measurements[0], measured, *first.measurements[2:])
    )
    with pytest.raises(ValueError, match="D3_SEED_GROWTH_RESULT_IDENTITY"):
        replace(grown, parts=(first, *grown.parts[1:]))


def test_growth_decode_rejects_another_code_distance(monkeypatch):
    from modules.codes.rotated_surface.growth_decoder import GrowthDecoder

    world, _template, bound, _compiled, _contexts = bound_fixture(monkeypatch)
    grown = bound.expand(
        InvocationContext("growth", 10, 100, world.device, world.state)
    )
    grown = grown.with_results(
        {m.result.measurement_id: 0 for part in grown.parts for m in part.measurements}
    )
    with pytest.raises(ValueError, match="DECODER_DISTANCE"):
        grown.decode(grown.results_ready_us, decoder=GrowthDecoder(7))

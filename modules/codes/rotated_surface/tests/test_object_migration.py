"""The migrated source preserves the agreed preparation and physical conventions."""

import pytest

from modules.codes.rotated_surface import RawTPostselection, definition, get_component
from modules.codes.rotated_surface.fast_factory import factory_recipe, required_variants
from modules.codes.rotated_surface.growth import GrowthComponent, injection_indices
from modules.codes.rotated_surface.growth_decoder import GrowthDecoder


@pytest.mark.parametrize("distance", (3, 5, 7))
def test_three_round_seed_and_accepted_only_growth_contract(distance):
    protocol = RawTPostselection(distance)
    assert protocol.injection_rounds == 3
    assert protocol.growth_rounds == (0 if distance == 3 else distance)
    assert protocol.identity["postselection_scope"] == "d3_injection_only"
    assert definition(distance).atom_count == 2 * distance**2 - 1
    if distance > 3:
        growth = GrowthComponent(distance)
        assert not growth.acceptance_ports
        for q in injection_indices(distance)[:9]:
            assert f"reset q[{q}];" not in growth.source_qasm


@pytest.mark.parametrize("distance", (3, 5, 7))
def test_s_keeps_entangling_fold_and_measured_syndrome(distance):
    source = get_component("logical_s", distance).source_qasm
    assert "cz " in source and "cx " in source
    assert source.count(" = measure ") == distance**2 - 1
    assert source.count("reset ") == distance**2 - 1


def test_growth_decoder_corrects_one_persistent_data_error_without_rejection():
    code = definition(5)
    q = 0
    syndrome = [int(b == "Z" and q in qs) for b, qs in code.checks]
    frame = GrowthDecoder(5).decode([[0] * code.check_count, syndrome, syndrome])
    for basis, support in code.checks:
        correction = frame.x if basis == "Z" else frame.z
        parity = sum((correction >> bit) & 1 for bit in support) % 2
        assert parity == int(basis == "Z" and q in support)


@pytest.mark.parametrize("distance", (3, 5, 7))
def test_factory_keeps_59_cnots_and_conditional_real_s(distance):
    recipe = factory_recipe(distance)
    cnots = sum(
        len(r.compute_calls) + len(r.uncompute_calls) + 1 for r in recipe.rotations
    )
    assert cnots == 59
    assert len(recipe.initial_preparations) == 5 and len(recipe.rotations) == 11
    raw = [p for p in recipe.initial_preparations if p.resource_kind is not None]
    raw += [r.preparation for r in recipe.rotations]
    assert len(raw) == 15
    assert all(dict(p.parameters) == {"injection_rounds": 3} for p in raw)
    assert all(
        r.consumption.branches[1].calls[0].component_id == "logical_s"
        for r in recipe.rotations
    )
    assert any(component == "logical_s" for component, _ in required_variants(distance))

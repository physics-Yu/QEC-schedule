"""Fast admission checks for concrete large-distance component providers."""

from importlib import import_module

import pytest

from modules.codes.registry import get_entry
from modules.codes.rotated_surface.catalog import COMPONENT_NAMES, get_protocol
from modules.codes.rotated_surface.growth import injection_indices


@pytest.mark.parametrize("distance", (9, 11))
def test_all_components_are_concrete_and_keep_small_injection(distance):
    provider = import_module(f"modules.codes.rotated_surface_d{distance}.components")
    geometry = import_module(f"modules.codes.rotated_surface_d{distance}.definition")
    assert geometry.CODE.atom_count == 2 * distance**2 - 1
    assert len(COMPONENT_NAMES) == len(set(COMPONENT_NAMES)) == 16
    for name in COMPONENT_NAMES:
        assert provider.get_component(name) == get_protocol(name, distance)
    raw = provider.get_component("raw_t")
    assert raw.source_qasm.count("\nt q[") == 1
    assert f"t q[{injection_indices(distance)[4]}];" in raw.source_qasm
    assert len(raw.acceptance_ports) == 4
    selected = provider.get_component("raw_t_postselection")
    assert selected.injection_rounds == 3
    assert selected.growth_rounds == distance
    assert selected.identity["injection_distance"] == 3
    assert (
        get_entry(f"rotated_surface_d{distance}", "clifford_t").code
        == f"rotated_surface_d{distance}"
    )


@pytest.mark.parametrize("name", ("t", "logical_t", "not_a_gate"))
def test_catalog_does_not_invent_unsupported_protocols(name):
    with pytest.raises(ValueError, match="Unsupported"):
        get_protocol(name, 9)

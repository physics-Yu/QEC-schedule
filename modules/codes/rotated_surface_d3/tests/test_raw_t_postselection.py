"""Required repeated-SE usage of the unchanged raw-T primitive."""

from dataclasses import replace

import pytest
from nadit_physical_compiler.device import Position

from modules.codes.contracts.component import ComponentBinding, InvocationContext
from modules.codes.rotated_surface_d3.definition import REFERENCE_HOMES
from modules.codes.rotated_surface_d3.protocols.raw_t_postselection import (
    RawTPostselection,
)
from modules.codes.rotated_surface_d3.tests.component_fixtures import (
    device as device,  # noqa: PLC0414
)
from modules.codes.rotated_surface_d3.tests.component_fixtures import (
    world,
)


@pytest.fixture(scope="module")
def protocol_template(device):
    return RawTPostselection(extra_rounds=1, round_policy="explicit_control").compile(
        device,
        home_sites=REFERENCE_HOMES,
        origin=Position(0, 0),
        aod_id="transport",
    )


def expand(template, device, *, ids=tuple(range(17)), base=100, start=200):
    return template.bind(
        ComponentBinding("A", Position(0, 0), ids, "transport")
    ).expand(InvocationContext("injection", start, base, device, world(device, ids)))


def test_normal_d3_has_three_rounds_and_twenty_detectors(protocol_template, device):
    normal = replace(protocol_template, extra_rounds=2, round_policy="distance")
    assert RawTPostselection().extra_rounds == normal.extra_rounds == 2
    result = expand(normal, device)
    assert result.version == "2"
    assert result.distance == 3 and result.total_rounds == 3
    assert result.round_policy == "distance"
    assert len(result.measurements) == 24 and len(result.detectors) == 20
    assert [p.description.component_id for p in result.parts] == [
        "raw_t",
        "se_round",
        "se_round",
    ]
    assert normal.content_sha256 != protocol_template.content_sha256
    with pytest.raises(ValueError, match="explicit_control"):
        replace(result, parts=result.parts[:2])

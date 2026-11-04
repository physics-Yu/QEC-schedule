"""Production component contracts, measured preparation, and action binding."""

import json
from pathlib import Path

import pytest
from nadit_physical_compiler.architectures import generate
from nadit_physical_compiler.device import Position, loads_device
from nadit_physical_compiler.state import AtomLayout, AtomState, SLMHolder

from modules.codes.contracts.component import (
    ComponentBinding,
    InvocationContext,
)
from modules.codes.rotated_surface_d3.components import get_component
from modules.codes.rotated_surface_d3.definition import REFERENCE_HOMES


@pytest.fixture(scope="module")
def device():
    path = Path(__file__).parents[1] / "configs/nonzoned_reference.json"
    spec = json.loads(path.read_text())
    return loads_device(json.dumps(generate(spec["family"], spec["params"])))


@pytest.fixture(scope="module")
def se_template(device):
    return get_component("se_round").compile(
        device,
        home_sites=REFERENCE_HOMES,
        origin=Position(0, 0),
        aod_id="transport",
    )


def world(device, ids=tuple(range(17))):
    return AtomLayout(
        tuple(
            AtomState(a, device.site(s).position, SLMHolder(s))
            for a, s in zip(ids, REFERENCE_HOMES, strict=True)
        ),
        qubit_to_atom=ids,
    )


def expand(
    template,
    device,
    *,
    ids=tuple(range(17)),
    invocation="test",
    base=100,
    start=0,
    entry=None,
):
    binding = ComponentBinding("block-A", Position(0, 0), ids, "transport")
    return template.bind(binding).expand(
        InvocationContext(invocation, start, base, device, entry or world(device, ids))
    )

"""Ideal two-round raw-T acceptance and bounded adversarial-fault evidence.

These tests do not constitute a circuit-level distance or logical-noise study.
The raw-T production component is unchanged and no inter-round correction runs.
"""

import pytest
from nadit_physical_compiler.device import Position

from modules.codes.contracts.component import ComponentBinding, InvocationContext
from modules.codes.rotated_surface_d3.definition import REFERENCE_HOMES
from modules.codes.rotated_surface_d3.protocols.raw_t_postselection import (
    RawTPostselection,
)
from modules.codes.rotated_surface_d3.tests.component_fixtures import (  # fixture export
    device as device,  # noqa: PLC0414
)
from modules.codes.rotated_surface_d3.tests.component_fixtures import world


@pytest.fixture(scope="module")
def sequence(device):
    template = RawTPostselection(
        extra_rounds=1, round_policy="explicit_control"
    ).compile(
        device,
        home_sites=REFERENCE_HOMES,
        origin=Position(0, 0),
        aod_id="transport",
    )
    return template.bind(
        ComponentBinding(
            "injection-patch", Position(0, 0), tuple(range(17)), "transport"
        )
    ).expand(InvocationContext("postselected-raw-t", 1200, 700, device, world(device)))


def values_for(part, bits):
    return {
        record.result.measurement_id: value
        for record, value in zip(part.measurements, bits, strict=True)
    }


def test_first_bulk_readout_flip_passes_old_rule_but_fails_round_parity(sequence):
    first, second = sequence.parts
    truth = (0, 1, 0, 0, 0, 1, 1, 0)
    recorded = list(truth)
    recorded[1] ^= 1
    first_values = values_for(first, recorded)
    assert first.with_results(first_values).acceptance_status == "accepted"
    rejected = sequence.with_results(first_values | values_for(second, truth))
    assert rejected.acceptance_status == "rejected"
    assert sum(detector.value for detector in rejected.detectors) == 1

"""Required repeated-SE usage of the unchanged raw-T primitive."""

import json
from dataclasses import replace
from itertools import product

import pytest
from nadit_physical_compiler.device import Position

from modules.codes.contracts.component import ComponentBinding, InvocationContext
from modules.codes.rotated_surface_d3.definition import REFERENCE_HOMES
from modules.codes.rotated_surface_d3.protocols.raw_t_postselection import (
    RawTPostselection,
    RawTPostselectionExpansion,
)
from modules.codes.rotated_surface_d3.tests.test_components import (
    device as device,  # noqa: PLC0414
)
from modules.codes.rotated_surface_d3.tests.test_components import (
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


def test_explicit_historical_control_has_two_rounds_and_all_twelve_detectors(
    protocol_template, device
):
    result = expand(protocol_template, device)
    assert [p.description.component_id for p in result.parts] == ["raw_t", "se_round"]
    assert len(result.measurements) == 16 and len(result.detectors) == 12
    assert result.parts[1].start_us == result.parts[0].action_end_us
    assert result.parts[1].start_us < result.parts[0].results_ready_us
    assert result.exit_state == result.parts[0].entry_state
    assert result.correction_relations == result.parts[0].correction_relations
    assert result.acceptance_status == "pending"
    assert not result.ready_for_use(result.results_ready_us)
    assert [len(d.measurements) for d in result.detectors] == [1] * 4 + [2] * 8
    for detector in result.detectors:
        assert detector.value is None
        assert detector.available_at_us == max(
            m.available_at_us for m in detector.measurements
        )
    assert result.template_content_sha256 == protocol_template.content_sha256


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


def test_all_bulk_branches_preserved_and_cross_round_mismatch_rejected(
    protocol_template, device
):
    result = expand(protocol_template, device)
    for bulk in product((0, 1), repeat=4):
        bits = (0, *bulk[:2], 0, 0, *bulk[2:], 0)
        values = {
            m.result.measurement_id: b
            for m, b in zip(result.measurements, bits * 2, strict=True)
        }
        accepted = result.with_results(values)
        assert accepted.acceptance_status == "accepted"
        assert all(d.value == 0 for d in accepted.detectors)
        assert not accepted.ready_for_use(accepted.results_ready_us - 1)
        assert accepted.ready_for_use(accepted.results_ready_us)
        for check in range(8):
            changed = values | {
                result.parts[1].measurements[check].result.measurement_id: 1
                - bits[check]
            }
            rejected = result.with_results(changed)
            assert rejected.parts[0].acceptance_status == "accepted"
            assert rejected.acceptance_status == "rejected"
    assert all(m.value is None for m in result.measurements)


def test_pending_values_ids_and_time_are_not_filled_in(protocol_template, device):
    result = expand(
        protocol_template, device, ids=tuple(range(100, 117)), base=700, start=9000
    )
    first = result.parts[0]
    local_only = {
        m.result.measurement_id: 0
        for m in first.measurements
        if m.port in ("X0", "X3", "Z0", "Z3")
    }
    pending = result.with_results(local_only)
    assert pending.parts[0].acceptance_status == "accepted"
    assert pending.acceptance_status == "pending"
    assert not pending.ready_for_use(1e9)
    assert all(m.available_at_us >= 9000 for m in result.measurements)
    assert {m.result.measurement_id for m in result.measurements} == set(
        range(700, 716)
    )
    with pytest.raises(ValueError):
        result.with_results({9999: 0})
    with pytest.raises(ValueError):
        result.with_results({700: True})
    with pytest.raises(ValueError):
        result.with_results({700: 0}).with_results({700: 1})


def test_additional_rounds_are_checked_and_omission_is_rejected(
    protocol_template, device
):
    for invalid in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            RawTPostselection(extra_rounds=invalid)
    longer = expand(replace(protocol_template, extra_rounds=2), device)
    assert len(longer.measurements) == 24 and len(longer.detectors) == 20
    assert longer.template_content_sha256 != protocol_template.content_sha256
    with pytest.raises(ValueError):
        RawTPostselectionExpansion(longer.parts[:1], "incomplete")
    mismatched = replace(longer.parts[1], block_id="other")
    with pytest.raises(ValueError):
        RawTPostselectionExpansion((longer.parts[0], mismatched), "wrong")


def test_export_qualifies_provenance_and_keeps_results_pending(
    protocol_template,
    device,
    tmp_path,
):
    from modules.codes.rotated_surface_d3.examples.raw_t_postselection_export import (
        export_raw_t_postselection,
    )

    binding = ComponentBinding("A", Position(0, 0), tuple(range(17)), "transport")
    trace, summary, count = export_raw_t_postselection(
        tmp_path,
        device,
        binding,
        protocol_template.raw_t,
        InvocationContext("export", 0, 900, device, world(device)),
        extra_rounds=1,
        round_policy="explicit_control",
    )
    record = json.loads((tmp_path / "raw_t_postselection.json").read_text())
    assert count == summary["measurements"] == 16 and summary["detectors"] == 12
    assert summary["ready_for_use"] is False
    assert summary["acceptance_status"] == "pending"
    assert summary["quantitative_error_rate"] is None
    assert record["terminal_boundary"] == "open_after_last_se"
    assert all(m["value"] is None for m in record["measurements"])
    assert all(d["value"] is None and d["expected"] == 0 for d in record["detectors"])
    # The viewer receives no fake measurements, and two local operation-ID spaces
    # are qualified bijectively instead of colliding in the combined schedule.
    assert trace["measurements"] == []
    ids = [op["operation_id"] for op in trace["operations"]]
    assert len(set(ids)) == len(ids)
    provenance = record["viewer_source_id_map"]
    assert {p["invocation_id"] for p in provenance.values()} == {
        "export/round[0]",
        "export/round[1]",
    }
    assert trace["program_duration_us"] == pytest.approx(summary["action_end_us"])
    for step in trace["steps"]:
        for action in step["actions"]:
            assert all(str(i) in provenance for i in action["source_ids"])


def test_relative_sequence_rebinds_without_compilation(
    protocol_template, device, monkeypatch
):
    from modules.codes._support import atom_template

    shift = Position(125, 230)

    def region(r):
        return replace(
            r,
            x_min=r.x_min + shift.x,
            x_max=r.x_max + shift.x,
            y_min=r.y_min + shift.y,
            y_max=r.y_max + shift.y,
        )

    moved = replace(
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
        raise AssertionError(
            "A bound injection sequence must reuse both compiled templates."
        )

    monkeypatch.setattr(atom_template, "compile_physical", forbidden)
    ids = tuple(range(200, 217))
    result = protocol_template.bind(
        ComponentBinding("shifted", shift, ids, "transport")
    ).expand(InvocationContext("moved", 7000, 2000, moved, world(moved, ids)))
    assert result.exit_binding.origin == shift and result.exit_binding.atom_ids == ids
    assert result.template_content_sha256 == protocol_template.content_sha256
    assert all(
        m.atom_id in ids and m.available_at_us > 7000 for m in result.measurements
    )
    assert len(result.detectors) == 12 and result.acceptance_status == "pending"

"""Exercise source transport templates beyond the former admission shortcuts."""

import json
from pathlib import Path

from relaxed_transport_support import _peak_carried
from staged_reference_support import _audit

from nadit_physical_compiler.atom_ir import AtomProgram, Move
from nadit_physical_compiler.contracts import AtomFragment
from nadit_physical_compiler.device import Position
from nadit_physical_compiler.motion import check_move
from nadit_physical_compiler.replay import apply_step, replay
from nadit_physical_compiler.transport import StagedStrictTransport
from nadit_physical_compiler.transport.rules import StrictRules
from nadit_physical_compiler.transport.staged_emission import emit_stages
from nadit_physical_compiler.transport.staging import StageEvent, generate_stages
from reference.cases import ReferenceCase, load_cases

REFERENCE = Path(__file__).parents[1] / "reference"


def _assert_complete(case: ReferenceCase, fragment: AtomFragment) -> int:
    _audit(case, fragment)
    assert replay(AtomProgram(fragment.steps), case.entry, case.device) == case.target
    return _peak_carried(case, fragment)


def test_recorded_source_collision_is_corrected_with_the_same_six_atom_batch(
    tmp_path: Path,
) -> None:
    record = json.loads(
        (REFERENCE / "unsafe_sparse_gate.json").read_text(encoding="utf-8")
    )
    path = tmp_path / "recorded_sparse_gate.json"
    path.write_text(
        json.dumps(
            {
                "nm_per_um": record["nm_per_um"],
                "slms": record["slms"],
                "cases": [record["case"]],
            }
        ),
        encoding="utf-8",
    )
    case = load_cases(path)[0]
    destinations = {atom.id: atom for atom in case.target.atoms}
    rules = StrictRules(case.device.aod("transport"), case.device.timing)
    recorded_events = tuple(
        StageEvent(
            event["kind"],
            tuple((atom, Position(x, y)) for atom, x, y in event["positions"]),
        )
        for event in record["reference_run"]["events"]
    )
    original = emit_stages(
        recorded_events, case.moves, case.entry, destinations, case.device, rules
    )
    event_index = record["reference_run"]["collisions"][0]["event_index"]
    current = case.entry
    for step in original.steps[:event_index]:
        current = apply_step(current, step, case.device)
    collision = original.steps[event_index].actions[0]
    assert isinstance(collision, Move)
    checked = check_move(case.device, current, collision.grid, dict(collision.targets))
    assert checked.rule == "occupied"

    corrected_events = generate_stages(
        case.moves, case.entry, destinations, case.geometry
    )
    corrected = emit_stages(
        corrected_events, case.moves, case.entry, destinations, case.device, rules
    )
    assert _assert_complete(case, corrected) == 6
    compiled = StagedStrictTransport("transport", case.geometry).construct(
        case.entry, case.target, case.device
    )
    assert _assert_complete(case, compiled) == 6

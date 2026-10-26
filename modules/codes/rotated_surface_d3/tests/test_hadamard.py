"""Independent checks of physical H, data transport, and changed output roles."""

import json
from collections import Counter
from dataclasses import replace
from math import prod
from pathlib import Path

import pytest
import stim
from nadit_physical_compiler.architectures import generate
from nadit_physical_compiler.atom_ir import Load, LocalU, Move, Rotation, Store
from nadit_physical_compiler.device import Position, loads_device
from nadit_physical_compiler.state import AtomLayout, AtomState, SLMHolder

from modules.codes._support import atom_template
from modules.codes._support.atom_binding import rebind_program
from modules.codes._support.atom_template import BindingRejected
from modules.codes.contracts.component import (
    ComponentBinding,
    InvocationContext,
    validate_sequence,
)
from modules.codes.rotated_surface_d3.components import get_component
from modules.codes.rotated_surface_d3.definition import CHECKS
from modules.codes.rotated_surface_d3.tests.quantum_checks import (
    action_stim,
    pauli,
    postselect,
    source_stim,
    unitary,
)

PERMUTATION = (2, 5, 8, 1, 4, 7, 0, 3, 6)
INVERSE = (6, 3, 0, 7, 4, 1, 8, 5, 2)
IDS = tuple(range(200, 217))
SECTORS = ((1,) * 8, (-1, 1, -1, 1, 1, -1, 1, 1))


@pytest.fixture(scope="module")
def profile():
    from modules.codes.rotated_surface_d3.components.hadamard import H_REFERENCE_HOMES

    path = Path(__file__).parents[1] / "configs/nonzoned_h_reference.json"
    spec = json.loads(path.read_text())
    device = loads_device(json.dumps(generate(spec["family"], spec["params"])))
    return device, H_REFERENCE_HOMES


@pytest.fixture(scope="module")
def template(profile):
    device, homes = profile
    return get_component("logical_h").compile(
        device, home_sites=homes, origin=Position(0, 0), aod_id="transport"
    )


def world(device, homes):
    return AtomLayout(
        tuple(
            AtomState(atom, device.site(site).position, SLMHolder(site))
            for atom, site in zip(IDS, homes, strict=True)
        ),
        qubit_to_atom=IDS,
    )


def expand(template, device, homes, *, entry=None, origin=None):
    binding = ComponentBinding("A", origin or Position(0, 0), IDS, "transport")
    return template.bind(binding).expand(
        InvocationContext("H-A", 700, 900, device, entry or world(device, homes))
    )


def actual_output_wires(expansion, device, homes):
    """Derive output-role wires from actual final positions, not exit metadata."""
    result = []
    for site in homes:
        matches = [
            atom.id
            for atom in expansion.exit_state.atoms
            if atom.position == device.site(site).position
            and atom.holder == SLMHolder(site)
        ]
        assert len(matches) == 1
        result.append(expansion.wire_atoms.index(matches[0]))
    return tuple(result)


def output_pauli(basis, roles, output_wires):
    return pauli(basis, tuple(output_wires[q] for q in roles))


def encoded_state(basis, sign, sector):
    lx, lz = pauli("X", (0, 3, 6)), pauli("Z", (0, 1, 2))
    logical = {"X": lx, "Y": 1j * lx * lz, "Z": lz}[basis]
    checks = [
        value * pauli(b, support)
        for value, (b, support) in zip(sector, CHECKS, strict=True)
    ]
    return stim.Tableau.from_stabilizers(
        [*checks, sign * logical, *(pauli("Z", (q,)) for q in range(9, 17))]
    )


def test_h_source_actions_actual_rotation_and_output_binding(template, profile):
    device, homes = profile
    expansion = expand(template, device, homes)
    source, source_measurements = source_stim(get_component("logical_h").source_qasm)
    actual, actual_measurements = action_stim(expansion, device)
    expected = stim.Circuit("I 16\nH 0 1 2 3 4 5 6 7 8")
    assert unitary(source) == unitary(actual) == unitary(expected)
    assert not source_measurements and not actual_measurements
    counts = Counter(type(a) for step in expansion.program.steps for a in step.actions)
    assert set(counts) <= {Load, Move, Store, Rotation, LocalU}
    # The approved H plus physical permutation now uses the shorter six-stroke route.
    assert counts[Load] == counts[Move] == counts[Store] == 6
    assert expansion.program.duration_us == 282
    assert expansion.entry_state != expansion.exit_state
    assert not expansion.exit_state.aod_grids
    assert not expansion.measurements and not expansion.correction_relations
    assert expansion.results_ready_us == expansion.action_end_us
    assert actual_output_wires(expansion, device, homes) == INVERSE + tuple(
        range(9, 17)
    )
    for old, new in enumerate(PERMUTATION):
        assert expansion.exit_state.atom(IDS[old]).holder == SLMHolder(homes[new])
    assert expansion.exit_binding is not None
    assert expansion.exit_binding.atom_ids == tuple(IDS[q] for q in INVERSE) + IDS[9:]
    assert expansion.exit_state.qubit_to_atom == expansion.entry_state.qubit_to_atom
    expected_parities = {
        **{f"X{i}": (f"input.Z{i}",) for i in range(4)},
        **{f"Z{i}": (f"input.X{3 - i}",) for i in range(4)},
    }
    assert dict(expansion.output_syndrome_parities) == expected_parities


@pytest.mark.parametrize("basis", "XYZ")
@pytest.mark.parametrize("sign", (-1, 1))
def test_h_six_states_with_explicit_syndrome_signs(basis, sign, template, profile):
    device, homes = profile
    expansion = expand(template, device, homes)
    source, _ = source_stim(get_component("logical_h").source_qasm)
    actual, _ = action_stim(expansion, device)
    output_wires = actual_output_wires(expansion, device, homes)
    lx = output_pauli("X", (0, 3, 6), output_wires)
    lz = output_pauli("Z", (0, 1, 2), output_wires)
    observables = {"X": lx, "Y": 1j * lx * lz, "Z": lz}
    target_basis = {"X": "Z", "Y": "Y", "Z": "X"}[basis]
    for sector in SECTORS:
        expected_sign = sign
        if basis in "YZ":
            expected_sign *= prod(sector[4:])
        if basis == "Y":
            expected_sign *= -1
        expected_checks = sector[4:] + tuple(reversed(sector[:4]))
        results = []
        for circuit in (source, actual):
            sim = stim.TableauSimulator()
            sim.set_inverse_tableau(encoded_state(basis, sign, sector).inverse())
            sim.do(circuit)
            assert [
                sim.peek_observable_expectation(output_pauli(b, qs, output_wires))
                for b, qs in CHECKS
            ] == list(expected_checks)
            for out_basis, observable in observables.items():
                assert sim.peek_observable_expectation(observable) == (
                    expected_sign if out_basis == target_basis else 0
                )
            results.append(sim.canonical_stabilizers())
        assert results[0] == results[1]


def remap_wires(circuit, mapping):
    """Express a following component in the first component's atom-wire basis."""
    result = stim.Circuit("I 16")
    for inst in circuit:
        result.append(
            inst.name,
            [mapping[target.value] for target in inst.targets_copy()],
            inst.gate_args_copy(),
        )
    return result


def test_h_then_ordinary_se_uses_returned_binding(template, profile):
    device, homes = profile
    h = expand(template, device, homes)
    assert h.exit_binding is not None
    se_template = get_component("se_round").compile(
        device, home_sites=homes, origin=Position(0, 0), aod_id="transport"
    )
    se = se_template.bind(h.exit_binding).expand(
        InvocationContext("SE-after-H", h.action_end_us, 1000, device, h.exit_state)
    )
    validate_sequence((h, se))
    first, _ = action_stim(h, device)
    second, measurement_ids = action_stim(se, device)
    second = remap_wires(second, tuple(h.wire_atoms.index(a) for a in se.wire_atoms))
    lx = output_pauli("X", (0, 3, 6), INVERSE)
    lz = output_pauli("Z", (0, 1, 2), INVERSE)
    observables = (lx, 1j * lx * lz, lz)
    for sector in SECTORS:
        expected_checks = sector[4:] + tuple(reversed(sector[:4]))
        values = {
            port.result.measurement_id: (1 - value) // 2
            for port, value in zip(se.measurements, expected_checks, strict=True)
        }
        for basis in "XYZ":
            sim = stim.TableauSimulator()
            sim.set_inverse_tableau(encoded_state(basis, 1, sector).inverse())
            sim.do(first)
            before = [sim.peek_observable_expectation(obs) for obs in observables]
            sim, probability = postselect(
                second, [values[mid] for mid in measurement_ids], sim
            )
            assert probability == 1
            assert [
                sim.peek_observable_expectation(obs) for obs in observables
            ] == before
    stale_binding = ComponentBinding("A", Position(0, 0), IDS, "transport")
    with pytest.raises(BindingRejected):
        se_template.bind(stale_binding).expand(
            InvocationContext("stale-SE", h.action_end_us, 1000, device, h.exit_state)
        )


def test_h_rejects_occupied_buffer_and_tampered_exit(template, profile):
    device, homes = profile
    reference = expand(template, device, homes)
    buffer_site = next(
        site
        for step in reference.program.steps
        for action in step.actions
        if isinstance(action, Store)
        for _, site in action.bindings
        if site not in homes
    )
    entry = world(device, homes)
    blocked = replace(
        entry,
        atoms=entry.atoms
        + (AtomState(999, device.site(buffer_site).position, SLMHolder(buffer_site)),),
    )
    with pytest.raises(BindingRejected):
        expand(template, device, homes, entry=blocked)
    with pytest.raises(ValueError):
        replace(template, exit_role_permutation=tuple(range(17)))
    with pytest.raises(BindingRejected):
        forged = replace(template, exit_home_sites=(), exit_role_permutation=())
        expand(forged, device, homes)


def test_h_translated_transport_reuse(template, profile, monkeypatch):
    device, homes = profile
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

    def forbidden(*args, **kwargs):
        raise AssertionError("H expansion must reuse compiled actions")

    monkeypatch.setattr(atom_template, "compile_physical", forbidden)
    original = expand(template, device, homes)
    moved = expand(template, translated, homes, origin=shift)
    normalized = rebind_program(
        moved.program,
        shift=Position(-shift.x, -shift.y),
        atoms={atom: atom for atom in IDS},
        sites={s.id: s.id for s in device.slm_sites},
        channels={
            "local": device.local.channel,
            "cz": device.cz.channel,
            "readout": device.readout.channel,
        },
        aod_id="transport",
        results={},
    )
    assert normalized == original.program
    assert actual_output_wires(moved, translated, homes) == INVERSE + tuple(
        range(9, 17)
    )
    assert moved.exit_binding.origin == shift

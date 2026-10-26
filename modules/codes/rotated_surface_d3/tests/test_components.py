"""Production component contracts, measured preparation, and action binding."""

import json
from dataclasses import replace
from itertools import combinations, product
from pathlib import Path

import pytest
import stim
from nadit_physical_compiler.architectures import generate
from nadit_physical_compiler.device import Position, loads_device
from nadit_physical_compiler.state import AtomLayout, AtomState, SLMHolder

from modules.codes.contracts.component import (
    ComponentBinding,
    InvocationContext,
    validate_sequence,
)
from modules.codes.rotated_surface_d3.components import get_component
from modules.codes.rotated_surface_d3.definition import CHECKS, REFERENCE_HOMES, ROLES
from modules.codes.rotated_surface_d3.tests.quantum_checks import (
    action_stim,
    pauli,
    postselect,
    source_stim,
    unitary,
)


@pytest.fixture(scope="module")
def device():
    path = Path(__file__).parents[1] / "configs/nonzoned_reference.json"
    spec = json.loads(path.read_text())
    return loads_device(json.dumps(generate(spec["family"], spec["params"])))


@pytest.fixture(scope="module")
def templates(device):
    return {
        name: get_component(name).compile(
            device,
            home_sites=REFERENCE_HOMES,
            origin=Position(0, 0),
            aod_id="transport",
        )
        for name in ("initialize_0", "initialize_plus", "se_round")
    }


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


def test_measured_initialization_protocol(templates):
    for name, template in templates.items():
        circuit = get_component(name).source_qasm
        assert circuit.count("cx ") == 24
        assert circuit.count("= measure") == 8
        assert template.description.measurements == tuple(
            f"{b}{i % 4}" for i, (b, _) in enumerate(CHECKS)
        )
        assert len(template.correction_terms) == (0 if name == "se_round" else 4)
    assert get_component("initialize_0").source_qasm.count("reset q[") == 17
    assert get_component("initialize_plus").source_qasm.count("reset q[") == 17
    assert get_component("se_round").source_qasm.count("reset q[") == 8


def test_instances_do_not_cache_values_or_clock(templates, device):
    template = templates["initialize_0"]
    a = expand(template, device)
    b = expand(
        template,
        device,
        ids=tuple(range(100, 117)),
        invocation="other",
        base=200,
        start=9000,
    )
    assert all(r.value is None for r in a.measurements + b.measurements)
    resolved = a.with_results({r.result.measurement_id: 0 for r in a.measurements})
    assert all(r.value == 0 for r in resolved.measurements)
    assert all(r.value is None for r in a.measurements)
    assert b.measurements[0].available_at_us == a.measurements[0].available_at_us + 9000
    assert {r.result.measurement_id for r in a.measurements}.isdisjoint(
        r.result.measurement_id for r in b.measurements
    )
    assert a.exit_state == a.entry_state
    assert b.exit_state == b.entry_state


def test_sequential_calls_preserve_pending_results(templates, device):
    initial = expand(templates["initialize_0"], device, invocation="prep")
    se = expand(
        templates["se_round"],
        device,
        invocation="round1",
        base=108,
        start=initial.action_end_us,
        entry=initial.exit_state,
    )
    assert se.entry_state == initial.exit_state
    assert se.start_us == initial.action_end_us
    assert se.correction_relations == ()
    assert initial.results_ready_us > initial.action_end_us
    assert all(r.available_at_us >= se.start_us for r in se.measurements)
    validate_sequence((initial, se))
    with pytest.raises(ValueError):
        validate_sequence((initial, replace(se, measurements=initial.measurements)))


def test_invalid_binding_and_results(templates, device):
    template = templates["se_round"]
    with pytest.raises(ValueError):
        template.bind(ComponentBinding("A", Position(0, 0), (0,) * 17, "transport"))
    with pytest.raises(ValueError):
        expand(template, device, start=-1)
    result = expand(template, device)
    with pytest.raises(ValueError):
        result.with_results({999999: 0})
    with pytest.raises(ValueError):
        result.with_results({100: 2})
    with pytest.raises(ValueError):
        expand(template, replace(device, timing=replace(device.timing, load_us=11)))


def test_public_lookup_rejects_unknown():
    with pytest.raises(ValueError):
        get_component("unitary_initialize_0")


def test_template_identity_covers_actions_and_interpretation(templates):
    from nadit_physical_compiler.atom_ir import AtomStep, Wait

    original = templates["se_round"]
    changed = replace(
        original,
        relative_program=replace(
            original.relative_program,
            steps=original.relative_program.steps + (AtomStep((Wait(duration_us=1),)),),
        ),
    )
    interpretation = replace(original, acceptance_ports=("X0",))
    assert original.source_sha256 == changed.source_sha256
    assert original.compiler_source_sha256 == changed.compiler_source_sha256
    assert original.content_sha256 == replace(original).content_sha256
    assert (
        len(
            {
                original.content_sha256,
                changed.content_sha256,
                interpretation.content_sha256,
            }
        )
        == 3
    )


def test_description_has_entry_exit_and_roles(templates):
    for template in templates.values():
        assert template.description.roles == ROLES
        assert template.description.entry_requirements
        assert template.description.exit_guarantees
        assert template.description.code_id == "rotated_surface_d3"


@pytest.mark.parametrize("name", ("initialize_0", "initialize_plus"))
def test_all_preparation_branches_source_and_atoms(name, templates, device):
    component = get_component(name)
    expansion = expand(templates[name], device)
    source, source_ports = source_stim(component.source_qasm)
    actual, actual_refs = action_stim(expansion, device)
    assert source_ports == list(range(8))
    assert unitary(source) == unitary(actual)
    logical = pauli("Z", (0, 1, 2)) if name == "initialize_0" else pauli("X", (0, 3, 6))
    stabilizers = [pauli(b, qs) for b, qs in CHECKS]
    total = 0
    for random_bits in product((0, 1), repeat=4):
        values = (
            tuple(random_bits) + (0,) * 4
            if name == "initialize_0"
            else (0,) * 4 + tuple(random_bits)
        )
        result_bits = {
            r.result.measurement_id: v
            for r, v in zip(expansion.measurements, values, strict=True)
        }
        source_sim, p_source = postselect(source, values)
        atom_sim, p_atom = postselect(actual, [result_bits[mid] for mid in actual_refs])
        assert p_source == p_atom == 1 / 16
        total += p_source
        assert source_sim.canonical_stabilizers() == atom_sim.canonical_stabilizers()
        assert atom_sim.peek_observable_expectation(logical) == 1
        assert [atom_sim.peek_observable_expectation(s) for s in stabilizers] == [
            1 - 2 * v for v in values
        ]
        resolved = expansion.with_results(result_bits)
        # Verification alone evaluates the declared relation. Production code
        # neither applies these Paulis nor manages a global frame.
        for relation in resolved.correction_relations:
            if result_bits[relation.result.measurement_id]:
                correction = stim.PauliString(17)
                for atom, basis in relation.pauli_atoms:
                    correction[expansion.wire_atoms.index(atom)] = basis
                atom_sim.do_pauli_string(correction)
        assert all(atom_sim.peek_observable_expectation(s) == 1 for s in stabilizers)
        assert atom_sim.peek_observable_expectation(logical) == 1
    assert total == 1


def test_se_measurement_operators_and_input_errors(templates, device):
    expansion = expand(templates["se_round"], device)
    source, _ = source_stim(get_component("se_round").source_qasm)
    actual, ids = action_stim(expansion, device)
    assert unitary(source) == unitary(actual)
    stabilizers = [pauli(b, qs) for b, qs in CHECKS]
    inverse = unitary(actual).inverse()
    for i, s in enumerate(stabilizers):
        assert inverse.z_output(9 + i) == s * pauli("Z", (9 + i,))
    lx, lz = pauli("X", (0, 3, 6)), pauli("Z", (0, 1, 2))
    errors = [stim.PauliString(17)] + [pauli(b, (q,)) for q in range(9) for b in "XYZ"]
    for logical in (lz, lx, 1j * lx * lz):
        prepared = stim.Tableau.from_stabilizers(
            [*stabilizers, logical, *(pauli("Z", (q,)) for q in range(9, 17))]
        )
        for error in errors:
            sim = stim.TableauSimulator(seed=23)
            sim.set_inverse_tableau(prepared.inverse())
            sim.do_pauli_string(error)
            expected = {
                100 + i: int(not error.commutes(s)) for i, s in enumerate(stabilizers)
            }
            sim, p = postselect(actual, [expected[mid] for mid in ids], sim)
            assert p == 1
            assert sim.peek_observable_expectation(logical) == (
                1 if error.commutes(logical) else -1
            )


@pytest.mark.parametrize("name", ("initialize_0", "initialize_plus"))
def test_quantum_composition_without_frame_manager(name, templates, device):
    initial = expand(templates[name], device, invocation="prepare")
    se = expand(
        templates["se_round"],
        device,
        invocation="extract",
        base=108,
        start=initial.action_end_us,
        entry=initial.exit_state,
    )
    validate_sequence((initial, se))
    first, ids1 = action_stim(initial, device)
    second, ids2 = action_stim(se, device)
    for bits in product((0, 1), repeat=4):
        values = (
            tuple(bits) + (0,) * 4 if name == "initialize_0" else (0,) * 4 + tuple(bits)
        )
        m1 = {100 + i: v for i, v in enumerate(values)}
        m2 = {108 + i: v for i, v in enumerate(values)}
        sim, p = postselect(first, [m1[mid] for mid in ids1])
        before = sim.canonical_stabilizers()
        sim, p2 = postselect(second, [m2[mid] for mid in ids2], sim)
        assert p == 1 / 16 and p2 == 1
        assert sim.canonical_stabilizers() == before


@pytest.mark.parametrize("name", ("initialize_0", "initialize_plus", "se_round"))
def test_actual_translation_and_resource_remap_without_recompile(
    name, templates, device, monkeypatch
):
    from nadit_physical_compiler.device import Region

    import modules.codes._support.atom_template as backend
    from modules.codes._support.atom_binding import rebind_program

    template = templates[name]
    reference = expand(template, device)
    dx, dy = 120.0, 80.0

    def region(r):
        return Region(r.x_min + dx, r.y_min + dy, r.x_max + dx, r.y_max + dy)

    renamed = {s.id: "tile_" + s.id for s in device.slm_sites}
    translated = replace(
        device,
        zones=tuple(replace(z, bounds=region(z.bounds)) for z in device.zones),
        slm_sites=tuple(
            replace(
                s,
                id=renamed[s.id],
                position=Position(s.position.x + dx, s.position.y + dy),
            )
            for s in device.slm_sites
        ),
        pair_arrays=tuple(
            replace(
                a,
                left=tuple(tuple(renamed[s] for s in row) for row in a.left),
                right=tuple(tuple(renamed[s] for s in row) for row in a.right),
            )
            for a in device.pair_arrays
        ),
        aods=tuple(
            replace(a, id="tile_transport", workspace=region(a.workspace))
            for a in device.aods
        ),
        local=replace(device.local, channel="tile_local"),
        cz=replace(device.cz, channel="tile_cz"),
        readout=replace(device.readout, channel="tile_readout"),
    )
    ids = tuple(range(200, 217))
    entry = AtomLayout(
        tuple(
            AtomState(a, translated.site(renamed[s]).position, SLMHolder(renamed[s]))
            for a, s in zip(ids, REFERENCE_HOMES, strict=True)
        ),
        qubit_to_atom=ids,
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Expansion must not compile")

    monkeypatch.setattr(backend, "compile_physical", forbidden)
    actual = template.bind(
        ComponentBinding("B", Position(dx, dy), ids, "tile_transport")
    ).expand(InvocationContext("translated", 2000, 500, translated, entry))
    normalized = rebind_program(
        actual.program,
        shift=Position(-dx, -dy),
        atoms={a: i for i, a in enumerate(ids)},
        sites={v: k for k, v in renamed.items()},
        channels={"local": "local", "cz": "rydberg", "readout": "camera"},
        aod_id="transport",
        results={500 + i: 100 + i for i in range(8)},
    )
    assert normalized == reference.program
    assert actual.exit_state == entry
    assert unitary(action_stim(actual, translated)[0]) == unitary(
        action_stim(reference, device)[0]
    )


def test_binding_rejects_fixed_readout_and_blocked_guest(templates, device):
    from nadit_physical_compiler.device import Region

    from modules.codes._support.atom_template import BindingRejected

    template = templates["se_round"]
    bad_device = replace(
        device,
        zones=tuple(
            replace(z, bounds=Region(500, 500, 600, 600))
            if "measure" in z.operations
            else z
            for z in device.zones
        ),
    )
    with pytest.raises(BindingRejected):
        expand(template, bad_device)
    entry = world(device)
    # A stationary atom in a required guest trap invalidates at least one pulse
    # or transport. Full world occupancy must not be silently ignored.
    site = device.site("guest_r1_c1")
    blocked = replace(
        entry, atoms=entry.atoms + (AtomState(99, site.position, SLMHolder(site.id)),)
    )
    with pytest.raises(ValueError):
        expand(template, device, entry=blocked)


def test_whole_readout_capacity_and_pending_result_semantics(templates, device):
    from modules.codes._support.atom_template import BindingRejected

    small = replace(device, readout=replace(device.readout, max_atoms=1))
    with pytest.raises(BindingRejected):
        expand(templates["initialize_0"], small)
    initial = expand(templates["initialize_0"], device)
    noisy = initial.with_results(
        {r.result.measurement_id: 1 for r in initial.measurements}
    )
    assert all(r.value == 1 for r in noisy.measurements)
    assert all(r.expected_ideal_value == 0 for r in noisy.measurements[4:])
    assert len(noisy.correction_relations) == 4  # no inferred decoder action
    with pytest.raises(ValueError):
        noisy.with_results({100: 0})


def test_nz_hook_directions_of_production_source():
    from modules.codes.rotated_surface_d3.definition import DATA_COORDINATES

    circuit, _ = source_stim(get_component("se_round").source_qasm)
    gates = []
    for inst in circuit:
        if inst.name in ("R", "M"):
            continue
        if inst.name == "CX":
            targets = [t.value for t in inst.targets_copy()]
            gates.extend(
                stim.CircuitInstruction("CX", targets[i : i + 2])
                for i in range(0, len(targets), 2)
            )
        else:
            gates.append(inst)
    count = 0
    for i, (basis, support) in enumerate(CHECKS):
        if len(support) != 4:
            continue
        anc = 9 + i
        locations = [
            k
            for k, inst in enumerate(gates)
            if inst.name == "CX" and anc in [t.value for t in inst.targets_copy()]
        ]
        suffix = stim.Circuit("I 16")
        for inst in gates[locations[1] + 1 :]:
            suffix.append(inst)
        tableau = stim.Tableau.from_circuit(suffix)
        error = tableau.x_output(anc) if basis == "X" else tableau.z_output(anc)
        data = [q for q in range(9) if error[q]]
        assert len(data) == 2
        axis = 1 if basis == "X" else 0
        assert DATA_COORDINATES[data[0]][axis] == DATA_COORDINATES[data[1]][axis]
        count += 1
    assert count == 4


def test_mathematical_code_distance():
    stabilizers = [pauli(b, qs, 9) for b, qs in CHECKS]
    lx, lz = pauli("X", (0, 3, 6), 9), pauli("Z", (0, 1, 2), 9)
    assert not lx.commutes(lz)
    assert all(lx.commutes(s) and lz.commutes(s) for s in stabilizers)
    stim.Tableau.from_stabilizers([*stabilizers, lz])
    group = [stim.PauliString(9)]
    for s in stabilizers:
        group += [g * s for g in group]
    signatures = {str(g)[1:] for g in group}
    assert len(signatures) == 256
    for weight in (1, 2):
        for support in combinations(range(9), weight):
            for axes in product("XYZ", repeat=weight):
                p = stim.PauliString(9)
                for q, axis in zip(support, axes, strict=True):
                    p[q] = axis
                if all(p.commutes(s) for s in stabilizers):
                    assert str(p)[1:] in signatures
    assert str(lx)[1:] not in signatures and lx.weight == 3

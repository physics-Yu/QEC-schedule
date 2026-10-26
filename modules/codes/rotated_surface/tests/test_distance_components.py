"""Independent ideal checks for the distance-parameterized component family."""

import pytest
import qiskit.qasm3
import stim

from modules.codes.rotated_surface import definition, get_component
from modules.codes.rotated_surface.circuits import se_layers
from modules.codes.rotated_surface_d3 import definition as d3
from modules.codes.rotated_surface_d3.components import get_component as get_d3


def circuit(source, *, seed_basis=None):
    """Parse QASM independently; replace only the seed T for channel tomography."""
    qc = qiskit.qasm3.loads(source)
    result = stim.Circuit(f"I {qc.num_qubits - 1}")
    names = {
        "reset": "R",
        "h": "H",
        "cx": "CX",
        "cz": "CZ",
        "s": "S",
        "sdg": "S_DAG",
        "x": "X",
        "y": "Y",
        "z": "Z",
        "measure": "M",
    }
    for inst in qc.data:
        targets = [qc.find_bit(q).index for q in inst.qubits]
        name = inst.operation.name
        if name == "barrier":
            result.append("TICK")
        elif name == "t":
            assert seed_basis in ("X", "Y", "Z")
            if seed_basis == "Y":
                result.append("S", targets)
            elif seed_basis == "Z":
                result.append("H", targets)
        else:
            result.append(names[name], targets)
    return result


def pauli(code, basis, support):
    result = stim.PauliString(code.atom_count)
    for q in support:
        result[q] = basis
    return result


def prepared(code, logical, signs):
    generators = [
        (-1) ** bit * pauli(code, b, qs)
        for (b, qs), bit in zip(code.checks, signs, strict=True)
    ]
    generators += [logical]
    generators += [
        pauli(code, "Z", (q,)) for q in range(code.data_count, code.atom_count)
    ]
    sim = stim.TableauSimulator(seed=11)
    sim.set_inverse_tableau(stim.Tableau.from_stabilizers(generators).inverse())
    return sim


@pytest.mark.parametrize("distance", (3, 5, 7, 9, 11))
def test_css_rank_logical_strings_and_disjoint_extraction(distance):
    code = definition(distance)
    checks = [pauli(code, b, support) for b, support in code.checks]
    assert len(checks) == code.data_count - 1
    assert all(a.commutes(b) for a in checks for b in checks)
    x, z = pauli(code, "X", code.logical_x), pauli(code, "Z", code.logical_z)
    assert not x.commutes(z)
    assert all(x.commutes(p) and z.commutes(p) for p in checks)
    stim.Tableau.from_stabilizers(checks + [x], allow_underconstrained=True)
    assert len(code.roles) == code.atom_count == 2 * distance * distance - 1
    for phase in (False, True):
        layers = se_layers(code, phase=phase)
        assert sum(map(len, layers)) == 4 * distance * (distance - 1)
        for pairs in layers:
            flat = [q for pair in pairs for q in pair]
            assert len(flat) == len(set(flat))


def test_d3_definition_and_source_equivalence():
    code = definition(3)
    assert code.checks == d3.CHECKS
    assert code.roles == d3.ROLES
    assert code.reference_coordinates == d3.REFERENCE_COORDINATES
    for name in (
        "initialize_0",
        "initialize_plus",
        "se_round",
        "logical_x",
        "logical_y",
        "logical_z",
        "logical_s",
        "logical_sdag",
        "prepare_y",
        "logical_mx",
        "logical_mz",
        "raw_t",
    ):
        assert get_component(name, 3).source_qasm == get_d3(name).source_qasm


@pytest.mark.parametrize("distance", (3, 5, 7))
@pytest.mark.parametrize("name", ("logical_s", "logical_sdag"))
def test_real_phase_gate_logical_action_and_sector_equations(distance, name):
    code = definition(distance)
    component = get_component(name, distance)
    source = circuit(component.source_qasm)
    x, z = pauli(code, "X", code.logical_x), pauli(code, "Z", code.logical_z)
    y = 1j * x * z
    sectors = [(0,) * code.check_count]
    sectors += [
        tuple(int(i == j) for i in range(code.check_count))
        for j in range(code.check_count)
    ]
    for signs in sectors:
        incoming = dict(zip(code.check_roles, signs, strict=True))
        for before, after in ((x, y), (y, -x), (z, z)):
            if name == "logical_sdag" and before != z:
                after = -after
            sim = prepared(code, before, signs)
            sim.do(source)
            bits = dict(
                zip(
                    component.description.measurements,
                    sim.current_measurement_record(),
                    strict=True,
                )
            )
            assert sim.peek_observable_expectation(after) == 1
            for port, terms in component.measured_input_parities:
                assert bits[port] == bool(sum(incoming[p] for p in terms) % 2)
            for check, terms in component.output_syndrome_parities:
                i = code.check_roles.index(check)
                b, support = code.checks[i]
                expected = (-1) ** (sum(bits[p] for p in terms) % 2)
                assert (
                    sim.peek_observable_expectation(pauli(code, b, support)) == expected
                )


@pytest.mark.parametrize("distance", (3, 5, 7))
@pytest.mark.parametrize(
    "name", ("initialize_0", "initialize_plus", "prepare_y", "raw_t")
)
def test_preparation_channel_and_returned_corrections(distance, name):
    code = definition(distance)
    component = get_component(name, distance)
    bases = (
        ("X", "Y", "Z")
        if name == "raw_t"
        else ({"initialize_0": "Z", "initialize_plus": "X", "prepare_y": "Y"}[name],)
    )
    for basis in bases:
        source = circuit(component.source_qasm, seed_basis=basis)
        for seed in range(8):
            sim = stim.TableauSimulator(seed=seed)
            sim.do(source)
            bits = dict(
                zip(
                    component.description.measurements,
                    sim.current_measurement_record(),
                    strict=True,
                )
            )
            for port in component.acceptance_ports:
                assert bits[port] == 0
            for term in component.correction_terms:
                if bits[term.measurement_port]:
                    correction = stim.PauliString(code.atom_count)
                    for role, axis in term.pauli_roles:
                        correction[int(role[5:-1])] = axis
                    sim.do_pauli_string(correction)
            assert all(
                sim.peek_observable_expectation(pauli(code, b, qs)) == 1
                for b, qs in code.checks
            )
            logical = (
                pauli(code, "X", code.logical_x)
                if basis == "X"
                else pauli(code, "Z", code.logical_z)
                if basis == "Z"
                else 1j
                * pauli(code, "X", code.logical_x)
                * pauli(code, "Z", code.logical_z)
            )
            assert sim.peek_observable_expectation(logical) == 1


@pytest.mark.parametrize("distance", (True, 1, 2, 4, 3.0, "5"))
def test_invalid_distance_rejected(distance):
    with pytest.raises(ValueError, match="odd integer"):
        definition(distance)


def _binary_rank(vectors):
    """Independent pivot elimination; do not call production algebra helpers."""
    pivots = {}
    for vector in vectors:
        while vector:
            pivot = vector.bit_length() - 1
            if pivot in pivots:
                vector ^= pivots[pivot]
            else:
                pivots[pivot] = vector
                break
    return len(pivots)


@pytest.mark.parametrize("distance", (3, 5, 7, 9, 11, 13, 15))
def test_raw_acceptance_spans_every_deterministic_seed_parity(distance):
    from modules.codes.rotated_surface.circuits import raw_plus_qubits

    code = definition(distance)
    n = code.data_count
    checks = [
        sum(1 << q for q in support) << (0 if basis == "X" else n)
        for basis, support in code.checks
    ]
    plus = set(raw_plus_qubits(code))
    # The arbitrary central seed has no stabilizer of its own. Every other
    # product-state qubit contributes one independent X or Z generator.
    product = [(1 << q) << (0 if q in plus else n) for q in range(n) if q != n // 2]
    intersection_rank = (
        _binary_rank(checks) + _binary_rank(product) - _binary_rank(checks + product)
    )
    accepted = get_component("raw_t_direct_control", distance).acceptance_ports
    assert intersection_rank == len(accepted)
    deterministic = [checks[code.check_roles.index(port)] for port in accepted]
    assert _binary_rank(deterministic) == len(accepted)
    assert _binary_rank(product + deterministic) == len(product)


@pytest.mark.parametrize("distance", (3, 5, 7, 9, 11))
def test_every_raw_correction_column_preserves_the_arbitrary_seed(distance):
    code = definition(distance)
    component = get_component("raw_t_direct_control", distance)
    n, center = code.data_count, distance // 2
    central_x = set(range(center, n, distance))
    central_z = set(range(center * distance, (center + 1) * distance))
    for term in component.correction_terms:
        xs = {
            int(role[5:-1]) for role, basis in term.pauli_roles if basis in ("X", "Y")
        }
        zs = {
            int(role[5:-1]) for role, basis in term.pauli_roles if basis in ("Z", "Y")
        }
        # Check the full stabilizer syndrome column and both encoded seed axes.
        for port, (basis, support) in zip(code.check_roles, code.checks, strict=True):
            opposite = zs if basis == "X" else xs
            assert len(opposite & set(support)) % 2 == int(
                port == term.measurement_port
            )
        assert len(zs & central_x) % 2 == 0
        assert len(xs & central_z) % 2 == 0

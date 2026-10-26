"""Independent Clifford branch calculations for phase-component verification."""

from dataclasses import replace

import qiskit.qasm3
import stim
from nadit_physical_compiler.device import Position, Region
from nadit_physical_compiler.state import AtomLayout, AtomState, SLMHolder

from modules.codes.contracts.component import ComponentBinding, InvocationContext
from modules.codes.rotated_surface_d3.definition import CHECKS, REFERENCE_HOMES
from modules.codes.rotated_surface_d3.tests.quantum_checks import pauli


def source_circuit(source):
    """Parse physical QASM independently of the production compiler frontend."""
    qc = qiskit.qasm3.loads(source)
    circuit = stim.Circuit("I 16")
    ports = []
    gates = {
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
        if inst.operation.name == "barrier":
            circuit.append("TICK")
            continue
        circuit.append(
            gates[inst.operation.name], [qc.find_bit(q).index for q in inst.qubits]
        )
        if inst.operation.name == "measure":
            ports.extend(qc.find_bit(c).index for c in inst.clbits)
    return circuit, ports


def prepared(logical, signs=(0,) * 8):
    """Prepare a complete independent stabilizer state in a specified sector."""
    stabs = [
        (-1) ** bit * pauli(basis, support)
        for (basis, support), bit in zip(CHECKS, signs, strict=True)
    ]
    tableau = stim.Tableau.from_stabilizers(
        [*stabs, logical, *(pauli("Z", (q,)) for q in range(9, 17))]
    )
    sim = stim.TableauSimulator(seed=19)
    sim.set_inverse_tableau(tableau.inverse())
    return sim


def branches(circuit, initial=None):
    """Enumerate all nonzero-probability measurement branches, without sampling."""
    states = [(initial or stim.TableauSimulator(seed=19), (), 1.0)]
    for inst in circuit:
        if inst.name != "M":
            for sim, _, _ in states:
                sim.do(inst)
            continue
        for target in inst.targets_copy():
            updated = []
            for sim, bits, probability in states:
                expectation = sim.peek_z(target.value)
                for bit in (0, 1):
                    weight = (1 + (-1) ** bit * expectation) / 2
                    if weight:
                        child = sim.copy()
                        child.postselect_z(target.value, desired_value=bool(bit))
                        updated.append((child, (*bits, bit), probability * weight))
            states = updated
    return states


def apply_terms(sim, terms, values):
    """Apply a declared relation only inside the independent verification."""
    for term in terms:
        if values[term.measurement_port]:
            p = stim.PauliString(17)
            for role, basis in term.pauli_roles:
                assert role.startswith("data[")
                p[int(role[5:-1])] = basis
            sim.do_pauli_string(p)


def data_signature(sim):
    """Discard measured ancillas when comparing independently prepared branches."""
    reduced = stim.TableauSimulator()
    reduced.set_inverse_tableau(sim.current_inverse_tableau())
    reduced.set_num_qubits(9)
    return reduced.canonical_stabilizers()


def translated_expansion(template, device):
    """Bind the complete resource tile at another origin with new identities."""
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
    expansion = template.bind(
        ComponentBinding("B", Position(dx, dy), ids, "tile_transport")
    ).expand(InvocationContext("translated", 2000, 500, translated, entry))
    return expansion, translated, renamed

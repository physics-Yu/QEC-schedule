"""Versioned d=3 rotated CSS circuits with explicit measurement sign fixes."""

from copy import deepcopy
from hashlib import sha256
import json

VERSION = "0.1.0"
SCHEMA = "physical-program/0.2.0-draft"
CONVENTION = "surface17-row-major-x-vertical/1"
DATA = tuple(f"d{i}" for i in range(9))
CHECKS = (
    ("x0", "X", (0, 1, 3, 4), (0.5, 0.5)),
    ("x1", "X", (1, 2), (1.5, -0.5)),
    ("x2", "X", (4, 5, 7, 8), (1.5, 1.5)),
    ("x3", "X", (6, 7), (0.5, 2.5)),
    ("z0", "Z", (0, 3), (-0.5, 0.5)),
    ("z1", "Z", (1, 2, 4, 5), (1.5, 0.5)),
    ("z2", "Z", (3, 4, 6, 7), (0.5, 1.5)),
    ("z3", "Z", (5, 8), (2.5, 1.5)),
)
FORMALS = DATA + tuple(c[0] for c in CHECKS)
LOGICAL_X = (0, 3, 6)
LOGICAL_Z = (0, 1, 2)
OFFSETS = {"NW": (-0.5, -0.5), "NE": (0.5, -0.5),
           "SW": (-0.5, 0.5), "SE": (0.5, 0.5)}
ORDER = {"X": ("NW", "NE", "SW", "SE"), "Z": ("NW", "SW", "NE", "SE")}
SOURCES = ["R8-FACT-013@0.1.0", "R8-FACT-017@0.1.0",
           "https://arxiv.org/html/1404.3747v2#S2.T2"]


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode("utf-8")).hexdigest()


def surface17_definition() -> dict:
    """Return a fresh JSON descriptor, including all eight positive generators."""
    return {"code": "rotated_surface", "distance": 3, "convention": CONVENTION,
            "data_qubits": list(DATA),
            "stabilizers": [{"id": name, "pauli": basis,
                             "support": [f"d{i}" for i in support], "sign": 1,
                             "ancilla": name, "code_coordinate": list(center)}
                            for name, basis, support, center in CHECKS],
            "logical_x": [f"d{i}" for i in LOGICAL_X],
            "logical_z": [f"d{i}" for i in LOGICAL_Z],
            "cnot_corner_order": {k: list(v) for k, v in ORDER.items()},
            "coordinate_units": "dimensionless_code_diagram",
            "sources": list(SOURCES)}


def _op(id, kind, qubits, params, *, writes=(), condition=None, after=()):
    return {"kind": "op", "op": {
        "id": id, "kind": kind, "qubits": list(qubits), "params": dict(params),
        "reads": [] if condition is None else [condition["bit"]],
        "writes": list(writes), "after": list(after),
        "source_ids": [f"R3:{CONVENTION}:{id}"], "condition": condition}}


def _syndrome_nodes():
    nodes = [_op(f"reset_{q}", "reset", [q], {"basis": "Z"}) for q in FORMALS[9:]]
    nodes += [_op(f"prepare_{q}", "gate", [q], {"name": "H"}) for q in FORMALS[9:13]]
    for layer in range(4):
        for anc, basis, support, center in CHECKS:
            corner = ORDER[basis][layer]
            dx, dy = OFFSETS[corner]
            x, y = center[0] + dx, center[1] + dy
            if not (0 <= x < 3 and 0 <= y < 3):
                continue
            index = int(3 * y + x)
            assert index in support
            data = f"d{index}"
            qubits = [anc, data] if basis == "X" else [data, anc]
            node = _op(f"cx_{anc}_{corner}", "gate", qubits, {"name": "CX"})
            node["op"]["metadata"] = {"syndrome_layer": layer, "corner": corner, "check_id": anc}
            nodes.append(node)
    nodes += [_op(f"read_basis_{q}", "gate", [q], {"name": "H"}) for q in FORMALS[9:13]]
    nodes += [_op(f"measure_{q}", "measure", [q], {"basis": "Z"}, writes=[f"m_{q}"])
              for q in FORMALS[9:]]
    return nodes


def _sign_fix_masks(check_basis):
    """Find pure CSS sign fixes, NOT a noisy syndrome decoder."""
    checks = [sum(1 << i for i in support) for _, b, support, _ in CHECKS if b == check_basis]
    logical = LOGICAL_X if check_basis == "X" else LOGICAL_Z
    logical_mask = sum(1 << i for i in logical)
    answers = []
    for target in range(4):
        candidates = [mask for mask in range(1, 512)
                      if all((mask & check).bit_count() % 2 == int(j == target)
                             for j, check in enumerate(checks))
                      and (mask & logical_mask).bit_count() % 2 == 0]
        answers.append(min(candidates, key=lambda mask: (mask.bit_count(), mask)))
    return answers


def _template(id, qubits, nodes, stage, **extra):
    return {"template_id": id, "qubits": list(qubits), "body": nodes,
            "metadata": {"protocol": "surface17", "protocol_version": VERSION,
                         "code": "rotated_surface", "distance": 3,
                         "convention": CONVENTION, "orientation": "x_vertical_z_horizontal",
                         "boundary": "standalone_patch", "stage": stage,
                         "gate_set": ["H", "X", "Z", "CX", "MZ", "RESET_Z"],
                         "sources": list(SOURCES), **extra}}


def _templates():
    templates = {}
    sid = "s17.syndrome.v1"
    templates[sid] = _template(sid, FORMALS, _syndrome_nodes(), "memory_round",
                              cnot_corner_order={k: list(v) for k, v in ORDER.items()})
    for state in ("zero", "plus"):
        id = f"s17.prepare_{state}.v1"
        nodes = [_op(f"init_{q}", "reset", [q], {"basis": "Z"}) for q in DATA]
        if state == "plus":
            nodes += [_op(f"init_h_{q}", "gate", [q], {"name": "H"}) for q in DATA]
        nodes += _syndrome_nodes()
        check_basis, correction = ("X", "Z") if state == "zero" else ("Z", "X")
        masks = _sign_fix_masks(check_basis)
        sign_fixes = {}
        # The correction must follow the whole projection, including checks of
        # the opposite type. These after edges preserve this explicit protocol.
        measured = [f"measure_{q}" for q in FORMALS[9:]]
        for index, mask in enumerate(masks):
            result = f"m_{check_basis.lower()}{index}"
            sign_fixes[result] = [f"d{i}" for i in range(9) if mask & (1 << i)]
            for q in sign_fixes[result]:
                nodes.append(_op(f"fix_{index}_{q}", "gate", [q], {"name": correction},
                                 condition={"bit": result, "equals": 1}, after=measured))
        templates[id] = _template(id, FORMALS, nodes, f"prepare_{state}",
                                  sign_fixes=sign_fixes, sign_fix_gate=correction,
                                  sign_fix_scope="ideal_projection_signs_not_noise_decoding")
    id = "s17.transversal_cx.v1"
    templates[id] = _template(
        id, [f"{p}{i}" for p in ("c", "t") for i in range(9)],
        [_op(f"cx_{i}", "gate", [f"c{i}", f"t{i}"], {"name": "CX"}) for i in range(9)],
        "logical_cx", pairing="matching_data_index", direction="control_to_target",
        preconditions=["same_code_convention", "prepared_compatible_patches"],
    )
    id = "s17.measure_z_reset.v1"
    nodes = [_op(f"measure_{q}", "measure", [q], {"basis": "Z"}, writes=[f"m_{q}"]) for q in DATA]
    nodes += [_op(f"reset_{q}", "reset", [q], {"basis": "Z"}) for q in FORMALS]
    templates[id] = _template(id, FORMALS, nodes, "destructive_z_readout_reset",
                              logical_z_result_parity=[f"m_d{i}" for i in LOGICAL_Z],
                              output_state="all_physical_qubits_zero_not_encoded")
    return templates


def build_two_block_slice(rounds=1) -> dict:
    """Build a constant-size structure, regardless of the number of rounds."""
    if type(rounds) is not int or rounds < 1:
        raise ValueError("rounds must be a positive integer (bool is not accepted)")
    templates = _templates()
    qubits = []
    for block in ("control", "target"):
        for q in FORMALS:
            center = (int(q[1:]) % 3, int(q[1:]) // 3) if q.startswith("d") else next(c[3] for c in CHECKS if c[0] == q)
            qubits.append({"id": f"{block}/{q}", "block_id": block,
                           "role": "data" if q in DATA else "syndrome", "aod_group": "data",
                           "code_coordinate": list(center), "logical_id": block})
    body = []

    def call(block, phase, template, repeat=1):
        body.append({"kind": "call", "id": f"{phase}_{block}", "template_id": template,
                     "bindings": {q: f"{block}/{q}" for q in FORMALS}, "repeat": repeat,
                     "source_ids": [f"two_block_slice:{phase}:{block}"]})

    call("control", "prepare", "s17.prepare_plus.v1")
    call("target", "prepare", "s17.prepare_zero.v1")
    for block in ("control", "target"):
        call(block, "pre", "s17.syndrome.v1", rounds)
    body.append({"kind": "call", "id": "logical_cx", "template_id": "s17.transversal_cx.v1",
                 "bindings": {f"{p}{i}": f"{block}/d{i}" for p, block in (("c", "control"), ("t", "target")) for i in range(9)},
                 "repeat": 1, "source_ids": ["two_block_slice:logical_cx"]})
    for block in ("control", "target"):
        call(block, "post", "s17.syndrome.v1", rounds)
    for block in ("control", "target"):
        call(block, "readout", "s17.measure_z_reset.v1")
    program = {"schema_version": SCHEMA, "artifact_id": f"r3-two-block-s17-rounds-{rounds}-v{VERSION}",
               "producer_version": f"na_pipeline.qec/{VERSION}",
               "provenance": {"producer": "R3", "task_id": "T301", "kb_revision": "kb-0003",
                              "interface_version": "IF-MVP-001/0.2.0-draft", "fixture": False,
                              "source_program": "two_block_slice_reference_circuit"},
               "execution_kind": "compile_plan", "quantum_state_simulated": False,
               "hardware_executed": False, "loss_enabled": False,
               "device_ref": None, "capability_profile": "surface17-h-cx-measure-z-reset-conditional-pauli",
               "input_hashes": {"code_definition": _digest(surface17_definition()),
                                "templates": _digest(templates)},
               "qubits": qubits, "templates": templates, "body": body,
               "metadata": {"code_definition": surface17_definition(),
                            "rounds_before_and_after_cx": rounds,
                            "result_origin_required": "fake",
                            "logical_observables": [
                                {"id": f"logical_z_{block}", "kind": "result_parity",
                                 "results": [f"readout_{block}/r0/m_d{i}" for i in LOGICAL_Z],
                                 "status": "not_evaluated", "basis": "Z"}
                                for block in ("control", "target")],
                            "unverified": ["fault_tolerance", "noise", "physical_routing",
                                           "quantum_state", "real_decoder", "factory15to1",
                                           "lattice_surgery", "shor_lowering"]}}
    return deepcopy(program)

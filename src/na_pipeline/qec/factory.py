"""Adaptive physical 15-to-1 program; execution and token ownership belong to R5."""

from copy import deepcopy
from hashlib import sha256
import json
from math import isfinite
import re

from .factory_primitives import BLOCKS, FACTORY_BLOCKS, QUBITS, Circuit, template
from .surface17 import FORMALS
from .program import iter_physical_ops

MATRIX = (
    (0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1),
    (0, 0, 1, 0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1, 1),
    (0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 1, 0, 0, 1, 1),
    (1, 0, 0, 0, 1, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1),
    (0, 0, 0, 0, 1, 1, 1, 0, 1, 1, 0, 1, 0, 0, 1),
)


class FactoryProtocolError(ValueError):
    def __init__(self, code, message, *, stage_id=None, result_id=None):
        self.code, self.stage_id, self.result_id = code, stage_id, result_id
        super().__init__(f"{code}: {message}; stage={stage_id}; result={result_id}")


def _name(name, label):
    if not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9_.:-]+", name) is None:
        raise FactoryProtocolError("INVALID_ID", f"{label} must be namespace-safe")


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def distillation_matrix() -> dict:
    return {"rows": [list(row) for row in MATRIX], "source": "https://arxiv.org/html/1808.02892v3#S3.E1",
            "column_supports": [[f"W{r}" for r in range(5) if MATRIX[r][col]] for col in range(15)],
            "input_state": "A_plus", "unconverted_output_state": "A_minus", "conversion": "S_on_same_W4"}


def build_factory15to1_protocol(*, data_block_id="live_data", request_id="T_request_0", gate="T", epoch=0, factory_id="factory0", production_only=False) -> dict:
    for value, label in ((data_block_id, "data_block_id"), (request_id, "request_id"), (factory_id, "factory_id")):
        _name(value, label)
    if (data_block_id in FACTORY_BLOCKS or data_block_id == "join_probe"
            or data_block_id in {f"{factory_id}:{b}" for b in FACTORY_BLOCKS}
            or type(epoch) is not int or epoch < 0):
        raise FactoryProtocolError("INVALID_BINDING", "live data must be distinct and epoch a nonnegative integer")
    if gate not in {"T", "TDG"}:
        raise FactoryProtocolError("UNSUPPORTED_REQUEST", "gate must be T or TDG")
    pid = f"{factory_id}-e{epoch}-{request_id}-{gate}"
    templates, stages = {}, {}
    binding = {f"{b}_{q}": f"{data_block_id if b == 'D' else factory_id + ':' + b}/{q}"
               for b in BLOCKS for q in FORMALS}
    binding["join_probe"] = f"{factory_id}:join_probe"
    qubits = [{"id": binding[f"{b}_{q}"], "block_id": data_block_id if b == "D" else f"{factory_id}:{b}",
               "role": "data" if q.startswith("d") else "syndrome", "aod_group": "data" if b == "D" else "magic"}
              for b in BLOCKS for q in FORMALS]
    qubits.append({"id": binding["join_probe"], "block_id": factory_id, "role": "syndrome", "aod_group": "magic"})

    def add_stage(id, circuit, next_id=None, branch=None, purpose=None, reuse_key=None):
        tid = "factory." + (reuse_key or id) + ".v1"
        candidate = template(tid, circuit, purpose or id)
        if production_only and not id.startswith('consume'):
            candidate['qubits']=[q for q in candidate['qubits'] if not q.startswith('D_')]
        if tid in templates and templates[tid] != candidate:
            raise AssertionError("unsafe template reuse")
        templates[tid] = candidate
        call_id = pid + "." + id
        stages[id] = {"kind": "physical", "id": id, "template_id": tid, "call_id": call_id,
                      "next": next_id, "purpose": purpose or id}
        if branch:
            local_result, zero, one = branch
            stages[id]["branch"] = {"result_id": f"{call_id}/r0/{local_result}", "zero": zero, "one": one}

    init = Circuit()
    raw_inputs = []
    for col in range(4):
        b = next(f"W{r}" for r in range(5) if MATRIX[r][col])
        init.prepare(b, "A", f"raw{col}")
        raw_inputs.append({"index": col, "stage_id": "initialize", "block": b, "seed_local_op": f"raw{col}_seed_phase"})
    init.prepare("W4", "plus", "work_plus")
    if not production_only:init.syndrome("D", "live_data_hold")
    add_stage("initialize", init, "rotate_04", purpose="four_raw_A_inputs_and_output_plus")

    for col in range(4, 15):
        support = [f"W{r}" for r in range(5) if MATRIX[r][col]]
        pivot, controls = support[-1], support[:-1]
        rid, cid, fid = f"rotate_{col:02d}", f"correct_{col:02d}", f"finish_{col:02d}"
        rotation = Circuit()
        if col == 4:
            rotation.prepare("M", "A", "raw")
        for i, control in enumerate(controls):
            rotation.transversal(control, pivot, f"fanin_{i}")
        rotation.transversal(pivot, "M", "inject_cnot")
        mz = rotation.read_logical("M", "Z", "magic_read")
        add_stage(rid, rotation, branch=(mz, fid, cid), purpose=f"column_{col}_Z_product_T")
        stages[rid]["rotation"] = {"raw_input_index": col, "support": support, "pivot": pivot, "phase_sign": 1}
        raw_inputs.append({"index": col, "stage_id": rid if col == 4 else f'finish_{col-1:02d}',
                           "block": "M", "seed_local_op": "raw_seed_phase" if col == 4 else "raw_next_seed_phase"})
        if col > 4:
            stages[rid]['entry_magic_input'] = {'schema_version':'factory-prepared-input/0.1',
                'producer_stage_id':f'finish_{col-1:02d}','raw_input_index':col,'block':'M',
                'condition':'producer stage committed all preparation, SE, readout and reset actions on the same carriers'}
        correction = Circuit()
        correction.clifford_phase(pivot, 1, "phase_fix")
        add_stage(cid, correction, fid, purpose=f"conditional_S_on_{pivot}", reuse_key=f"correct_S_{pivot}")
        finish = Circuit()
        for i, control in enumerate(reversed(controls)):
            finish.transversal(control, pivot, f"uncompute_{i}")
        for b in (("W0", "W1", "W2", "W3", "W4") if production_only else ("W0", "W1", "W2", "W3", "W4", "D")):
            finish.syndrome(b, f"hold_{b}")
        # M was destructively read and cleaned by the preceding rotation. Its
        # next preparation commutes with all W/D uncompute and maintenance.
        # Expose both physical fronts together instead of hiding preparation
        # behind the next runtime stage boundary. The shared finish is reached
        # on both correction branches; no result or acceptance is speculated.
        if col < 14:
            finish.prepare('M','A','raw_next')
        next_id = f"rotate_{col + 1:02d}" if col < 14 else "terminal_checks"
        add_stage(fid, finish, next_id, purpose=f"restore_parity_and_QEC_after_column_{col}")
        if col < 14:
            stages[fid]['prepared_magic_output'] = {'schema_version':'factory-prepared-input/0.1',
                'consumer_stage_id':next_id,'raw_input_index':col+1,'block':'M',
                'same_carriers':True,'runtime_state_cached':False}

    terminal = Circuit()
    checks = [terminal.read_logical(f"W{i}", "X", f"terminal_W{i}") for i in range(4)]
    terminal.add("acceptance", "classical", params={"operation": "all_zero"}, reads=checks, writes=["accept"])
    add_stage("terminal_checks", terminal, branch=("accept", "reject_cleanup", "convert_output"),
              purpose="four_distillation_X_checks_not_surface_syndromes")
    convert = Circuit()
    convert.clifford_phase("W4", 1, "output_same_carrier_S")
    convert.syndrome("W4", "output_hold")
    add_stage("convert_output", convert, "ready", purpose="A_minus_to_A_plus_same_W4")
    stages["ready"] = {"kind": "lifecycle", "id": "ready", "event": "ready", "next": "reserve_delivery",
                       "requires": ["accepted_terminal_checks", "output_conversion_complete", "same_output_atoms"]}
    stages["reserve_delivery"] = {"kind": "lifecycle", "id": "reserve_delivery", "event": "reserve_and_deliver",
                                  "next": "consume", "request_id": request_id, "data_block_id": data_block_id,
                                  "requires": ["exclusive_token_claim", "live_data_preserved", "same_output_atoms"]}
    consume = Circuit()
    consume.transversal("D", "W4", "consume_cnot")
    p = consume.read_logical("W4", "Z", "consume_output")
    zero_next, one_next = ("consume_cleanup", "consume_correction") if gate == "T" else ("consume_correction", "consume_cleanup")
    add_stage("consume", consume, branch=(p, zero_next, one_next), purpose=f"{gate}_on_existing_live_data")
    fix = Circuit()
    fix.clifford_phase("D", 1 if gate == "T" else -1, "consume_phase_fix")
    add_stage("consume_correction", fix, "consume_cleanup", purpose="S_or_SDG_consumption_correction")
    cleanup = Circuit()
    cleanup.cleanup_factory("consume_cleanup")
    cleanup.syndrome("D", "live_data_after_consumption")
    add_stage("consume_cleanup", cleanup, "consumed", purpose="release_factory_preserve_live_data")
    reject = Circuit()
    reject.cleanup_factory("rejected_candidate_cleanup")
    add_stage("reject_cleanup", reject, "rejected", purpose="no_token_on_rejection")
    stages["consumed"] = {"kind": "terminal", "id": "consumed", "outcome": "consumed", "cleanup_complete": True}
    stages["rejected"] = {"kind": "terminal", "id": "rejected", "outcome": "rejected", "cleanup_complete": True}
    terminal_call = stages["terminal_checks"]["call_id"]
    acceptance_checks = [{"id": f"terminal_W{i}_X", "result_ids": [f"{terminal_call}/r0/terminal_W{i}_m_d{j}"
                         for j in (0, 3, 6)], "expected_parity": 0} for i in range(4)]
    result = {"schema_version": "factory-protocol/0.1.0-draft", "artifact_id": pid,
            "producer_version": "na_pipeline.qec.factory/0.3.0", "provenance": {"producer": "R0", "task_id": "T044",
            "kb_revision": "kb-0004", "fixture": False, "status": "physical_protocol_not_executed"},
            "execution_kind": "compile_plan", "quantum_state_simulated": False, "hardware_executed": False,
            "loss_enabled": False, "factory_id": factory_id, "epoch": epoch, "request_id": request_id,
            "request_gate": gate, "data_block_id": data_block_id, "qubits": qubits, "bindings": binding,
            "templates": templates, "stages": stages, "entry": "initialize", "matrix": distillation_matrix(),
            "raw_inputs": raw_inputs, "acceptance_checks": acceptance_checks,
            "injection": {"schema_version": "encoded-cnot-injection/0.1", "resource": "A_plus",
                          "control": "live_data_or_parity_pivot", "target": "magic",
                          "measurement": "magic_logical_Z", "uncorrected_branches": {"0": "T", "1": "TDG"},
                          "T_correction": {"0": "I", "1": "S"}, "TDG_correction": {"0": "SDG", "1": "I"}},
            "output_readiness_stage": "convert_output", "cleanup_stage_ids": ["reject_cleanup", "consume_cleanup"],
            "live_data_information_qubit_ids": [binding[f"D_d{i}"] for i in range(9)],
            "factory_qubit_ids": [binding[q] for q in QUBITS if not q.startswith("D_")],
            "frame_semantics": "explicit_physical_corrections_no_cached_frame_or_real_decoder",
            "output": {"block_id": f"{factory_id}:W4", "state": "A_plus",
            "qubit_ids": [binding[f"W4_{q}"] for q in FORMALS], "maximum_ready_inventory": 1},
            "lifecycle_contract": {"owner": "R5", "same_carrier_required": True, "consume_once": True,
            "new_epoch_requires_previous_cleanup": True, "ready_not_replayable": True},
            "entry_requirements": {"live_data": "existing_surface17_encoded_state_not_reset",
            "runtime_snapshot_required": True, "available_factory_carriers": 120},
            "unverified": ["fault_tolerance", "raw_injection_error_model", "encoded_cnot_injection_with_noise",
            "cross_window_atom_continuation", "runtime_token_lifecycle", "independent_R6_protocol_validation"]}
    if production_only:
        result.update(production_mode='independent_A_plus',data_block_id=None,live_data_information_qubit_ids=[])
        result['qubits']=[q for q in result['qubits'] if q['block_id']!=data_block_id]
        result['entry_requirements']['live_data']=None
        result['entry_requirements']['data_maintenance_owner']='algorithm_scheduler'
        result['entry_requirements']['available_factory_carriers']=120
        result['provenance']['status']='independent_producer_source_not_executed'
    return result


def build_factory_producer(*,factory_id,epoch,batch_id):
    """One factory line produces A_plus without selecting/locking any data patch."""
    return build_factory15to1_protocol(factory_id=factory_id,epoch=epoch,request_id=batch_id,
        data_block_id='unbound_data',production_only=True)


def factory_stage_program(protocol: dict, stage_id: str) -> dict:
    if protocol.get("schema_version") != "factory-protocol/0.1.0-draft":
        raise FactoryProtocolError("PROTOCOL_VERSION", "unknown factory protocol schema")
    stage = protocol["stages"].get(stage_id)
    if not stage or stage["kind"] != "physical":
        raise FactoryProtocolError("NOT_PHYSICAL_STAGE", "stage is absent or requires lifecycle owner", stage_id=stage_id)
    tid = stage["template_id"]
    if protocol.get('production_mode') and stage_id.startswith('consume'):
        raise FactoryProtocolError('PRODUCER_CONSUMER_UNBOUND','Bind a ready output to an actual data request before consumption',stage_id=stage_id)
    return {"schema_version": "physical-program/0.2.0-draft", "artifact_id": protocol["artifact_id"] + "." + stage_id,
            "producer_version": protocol["producer_version"], "provenance": {**protocol["provenance"],
            "protocol_id": protocol["artifact_id"], "stage_id": stage_id, "epoch": protocol["epoch"]},
            "execution_kind": "compile_plan", "quantum_state_simulated": False, "hardware_executed": False,
            "loss_enabled": False, "device_ref": None, "qubits": deepcopy(protocol["qubits"]),
            "templates": {tid: deepcopy(protocol["templates"][tid])},
            "body": [{"kind": "call", "id": stage["call_id"], "template_id": tid,
                      "bindings": {q:deepcopy(protocol['bindings'][q]) for q in protocol['templates'][tid]['qubits']}, "repeat": 1,
                      "source_ids": ["Litinski-v3-Eq1", f"T302:{stage_id}", protocol["artifact_id"]]}],
            "input_hashes": {"protocol": _hash(protocol)},
            "capability_profile": "factory_stage_requires_classical_xor_all_zero_and_continuation",
            "window_contract": {"schema_version": "physical-window-contract/0.1.0-draft",
                                "protocol_id": protocol["artifact_id"], "epoch": protocol["epoch"],
                                "stage_id": stage_id, "requires_runtime_snapshot": True,
                                "live_data_block_id": protocol["data_block_id"],
                                "clock": "absolute_us_continuation",
                                "required_capabilities": ["classical_xor_all_zero", "committed_atom_continuation"]},
            "metadata": {"purpose": stage["purpose"]}}


def factory_stage_decision(protocol, stage_id, results, *, now_us, receipt):
    """Pure controller helper. The caller supplies R5's completed-stage receipt.

    This function neither executes a stage nor grants/consumes a resource token.
    Fixture receipts remain visibly fixture in the return value.
    """
    if protocol.get("schema_version") != "factory-protocol/0.1.0-draft":
        raise FactoryProtocolError("PROTOCOL_VERSION", "unknown protocol")
    stage = protocol["stages"].get(stage_id)
    if not stage or stage["kind"] != "physical":
        raise FactoryProtocolError("NOT_PHYSICAL_STAGE", "lifecycle needs R5 ownership", stage_id=stage_id)
    if (not isinstance(receipt, dict) or receipt.get("protocol_id") != protocol["artifact_id"]
            or receipt.get("stage_id") != stage_id or receipt.get("epoch") != protocol["epoch"]
            or receipt.get("complete") is not True
            or receipt.get("evidence_kind") not in {"fixture", "fake_event_run"}
            or type(receipt.get("end_us")) not in (int, float) or not isfinite(receipt["end_us"]) or receipt["end_us"] < 0
            or type(now_us) not in (int, float) or not isfinite(now_us) or now_us < receipt["end_us"]):
        raise FactoryProtocolError("STAGE_NOT_COMMITTED", "complete matching receipt and current time required", stage_id=stage_id)
    next_id, reads = stage.get("next"), []
    if "branch" in stage:
        branch = stage["branch"]
        rid = branch["result_id"]
        record = results.get(rid)
        if not isinstance(record, dict) or type(record.get("value")) is not int or record["value"] not in (0, 1):
            raise FactoryProtocolError("MISSING_RESULT", "explicit committed bit required", stage_id=stage_id, result_id=rid)
        if record.get("origin") not in {"fake", "classical"}:
            raise FactoryProtocolError("RESULT_ORIGIN", "expected fake or derived classical result", stage_id=stage_id, result_id=rid)
        if (type(record.get("ready_us")) not in (int, float) or not isfinite(record["ready_us"])
                or record["ready_us"] < 0 or record["ready_us"] > now_us):
            raise FactoryProtocolError("RESULT_NOT_READY", "future result cannot select a branch", stage_id=stage_id, result_id=rid)
        if record.get("origin") == "classical" and record.get("measurement_origin") != "fake":
            raise FactoryProtocolError("RESULT_ORIGIN", "derived bit must retain fake measurement ancestry", stage_id=stage_id, result_id=rid)
        next_id = branch["one"] if record["value"] else branch["zero"]
        reads = [rid]
    return {"protocol_id": protocol["artifact_id"], "epoch": protocol["epoch"], "from_stage": stage_id,
            "next_stage": next_id, "reads": reads, "decision_us": now_us,
            "evidence_kind": receipt["evidence_kind"], "token_transition_performed": False}


def bind_factory_stage(protocol, stage_id, atom_program):
    """Bind this exact physical stage to R4 action/carrier identities.

    This is a mapping check only. It does not certify action completion,
    geometry, readiness, lifecycle transitions, or R5 snapshot authenticity.
    """
    physical = factory_stage_program(protocol, stage_id)
    if atom_program.get("input_hashes", {}).get("physical_program") != _hash(physical):
        raise FactoryProtocolError("PHYSICAL_STAGE_HASH", "AtomProgram is not bound to this physical stage", stage_id=stage_id)
    atoms = atom_program.get("initial_state", {}).get("atoms", [])
    qmap = {item["qubit_id"]: item["atom_id"] for item in atoms}
    if (len(qmap) != len(atoms) or len(set(qmap.values())) != len(atoms)
            or set(qmap) != {q["id"] for q in protocol["qubits"]}):
        raise FactoryProtocolError("STAGE_CARRIER_BINDING", "need one-to-one complete qubit/atom inventory", stage_id=stage_id)
    actions = atom_program.get("actions", [])
    by_id = {action["id"]: action for action in actions}
    if len(by_id) != len(actions):
        raise FactoryProtocolError("DUPLICATE_ACTION", "action IDs must be unique", stage_id=stage_id)
    source_map = atom_program.get("source_map", {})
    expected, measure_results, classical_results, used = set(), [], [], []
    for op in iter_physical_ops(physical):
        sid = op["id"]
        expected.add(sid)
        mapped = source_map.get(sid)
        if not isinstance(mapped, list) or not mapped or len(set(mapped)) != len(mapped):
            raise FactoryProtocolError("STAGE_SOURCE_COVERAGE", "source operation missing or map duplicated", stage_id=stage_id)
        for aid in mapped:
            if aid not in by_id or sid not in by_id[aid].get("source_ids", []):
                raise FactoryProtocolError("STAGE_SOURCE_BINDING", "action not bound to its source", stage_id=stage_id)
            used.append(aid)
        if op["kind"] == "measure":
            measure_results.extend(op["writes"])
        if op["kind"] == "classical":
            classical_results.extend(op["writes"])
    if set(source_map) != expected or set(used) != set(by_id):
        raise FactoryProtocolError("STAGE_SOURCE_COVERAGE", "extra or unmapped sources/actions", stage_id=stage_id)
    output_q = protocol["output"]["qubit_ids"]
    data_q = protocol["live_data_information_qubit_ids"]
    output_data_q = [q for q in output_q if "/d" in q]
    factory_atoms = {qmap[q] for q in protocol["factory_qubit_ids"]}
    category = ("conversion" if stage_id == "convert_output" else "cleanup" if stage_id in protocol["cleanup_stage_ids"]
                else "consumption" if stage_id in {"consume", "consume_correction"} else "production")
    aux_q = [protocol["bindings"][f"Y_{q}"] for q in FORMALS]
    aux_q += [q for q in output_q if q not in output_data_q] + [protocol["bindings"]["join_probe"]]
    return {"schema_version": "factory-stage-binding/0.1.0-draft", "protocol_id": protocol["artifact_id"],
            "protocol_hash": _hash(protocol), "physical_program_hash": _hash(physical),
            "atom_program_ref": atom_program["artifact_id"], "atom_program_hash": _hash(atom_program),
            "stage_id": stage_id, "category": category, "factory_id": protocol["factory_id"],
            "epoch": protocol["epoch"], "request_id": protocol["request_id"],
            "action_ids": list(dict.fromkeys(used)), "actions_by_source": deepcopy(source_map),
            "measurement_result_ids": measure_results, "classical_result_ids": classical_results,
            "output_atom_ids": [qmap[q] for q in output_q], "output_data_atom_ids": [qmap[q] for q in output_data_q],
            "live_block_atom_ids": [qmap[protocol["bindings"][f"D_{q}"]] for q in FORMALS],
            "live_data_atom_ids": [qmap[q] for q in data_q], "factory_atom_ids": sorted(factory_atoms),
            "consumption_auxiliary_atom_ids": [qmap[q] for q in aux_q],
            "factory_reset_action_ids": [a["id"] for a in actions if a["kind"] == "reset" and a["atoms"]
                                         and set(a["atoms"]) <= factory_atoms],
            "acceptance_checks": deepcopy(protocol["acceptance_checks"]) if stage_id == "terminal_checks" else [],
            "provenance": {"producer": "R3", "fixture": bool(atom_program.get("provenance", {}).get("fixture", False)),
                           "scope": "mapping_only"}, "execution_verified": False, "token_transition_performed": False}

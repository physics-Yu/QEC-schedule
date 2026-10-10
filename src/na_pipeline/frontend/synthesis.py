"""Finite-angle Clifford+T lowering with explicit classical-branch phases."""

from copy import deepcopy
from decimal import Decimal, localcontext, ROUND_CEILING
from fractions import Fraction

from .operator_certificate import certify_rotation
from .rotation_table import ROTATIONS, TABLE_VERSION


def _sum_bounds(values):
    with localcontext() as ctx:
        ctx.prec = 70
        ctx.rounding = ROUND_CEILING
        return str(sum((Decimal(str(value)) for value in values), Decimal(0)))


def synthesize_feedback(program: dict) -> dict:
    """Lower all retained small P angles using a certified, finite word table.

    The scalar phase ledger is retained. Removing it changes the phase-sensitive
    operator. It can be treated as branch-global only because conditions refer
    to measured classical bits; quantum-controlled use is explicitly rejected.
    """
    from .program import FrontendError, _hash, validate_logical, iter_logical_ops
    errors = validate_logical(program)
    if errors:
        raise FrontendError(f"INVALID_SYNTHESIS_INPUT: {errors}")
    if program.get("synthesis", {}).get("status") == "complete":
        return deepcopy(program)
    result = deepcopy(program)
    certificates = {}
    phases = []
    body = []
    for node in result["body"]:
        if node["kind"] != "op" or node["op"]["params"].get("name") != "P":
            body.append(node)
            continue
        source = node["op"]
        angle = source["params"]["angle_pi"]
        entry = ROTATIONS.get(str(angle["denominator"]))
        if angle["numerator"] != -1 or entry is None:
            raise FrontendError(f"UNSUPPORTED_SYNTHESIS_ANGLE: {source['id']}")
        if source["condition"] is None or source["qubits"] != ["ctrl"]:
            raise FrontendError(f"UNSUPPORTED_SYNTHESIS_CONTEXT: {source['id']}")
        template_id = f"feedback-minus-pi-over-{angle['denominator']}/1"
        if template_id not in certificates:
            certificate = certify_rotation(entry["chronological_gates"], angle, entry["global_phase_pi"])
            certificate.update({"table_version": TABLE_VERSION, "synthesizer": "pygridsynth/1.2.0",
                                "seed": 7, "dps": 80, "generation_epsilon": "0.00001"})
            certificates[template_id] = certificate
            template_body = []
            for index, gate in enumerate(entry["chronological_gates"]):
                template_body.append({"kind": "op", "op": {
                    "id": f"g{index:03d}", "kind": "gate", "qubits": ["q"], "params": {"name": gate},
                    "after": [] if index == 0 else [f"g{index - 1:03d}"],
                    "reads": [], "writes": [], "condition": None,
                    "source_ids": [f"synthesis:{template_id}", f"synthesis:{template_id}/g{index:03d}"]}})
            result["templates"][template_id] = {
                "template_id": template_id, "formal_qubits": ["q"], "body": template_body,
                "metadata": {"protocol": "classically-conditioned-single-qubit-phase",
                             "angle_pi": deepcopy(angle), "global_phase_pi": deepcopy(entry["global_phase_pi"]),
                             "certificate_ref": template_id, "table_version": TABLE_VERSION,
                             "coherent_quantum_control_supported": False}}
        certificate = certificates[template_id]
        if Decimal(certificate["operator_error_upper_bound"]) > Decimal(str(source["params"]["error_budget"])):
            raise FrontendError(f"SYNTHESIS_PRECISION_UNMET: {source['id']}")
        body.append({"kind": "call", "id": source["id"], "template_id": template_id,
                     "bindings": {"q": source["qubits"][0]}, "repeat": 1,
                     "after": source["after"].copy(), "source_ids": source["source_ids"] + [source["id"]],
                     "condition": deepcopy(source["condition"]), "condition_scope": "classical",
                     "logical_source_op": deepcopy(source), "synthesis_certificate_ref": template_id})
        phases.append({"source_operation_id": source["id"], "condition": deepcopy(source["condition"]),
                       "global_phase_pi": deepcopy(entry["global_phase_pi"]),
                       "semantics": "exp(i*pi*phase)*chronological_word",
                       "scope": "classical_branch_global_not_quantum_control"})
    result["body"] = body
    result["synthesis_certificates"] = certificates
    result["branch_global_phases"] = phases
    instance_bounds = [certificates[n["synthesis_certificate_ref"]]["operator_error_upper_bound"]
                       for n in body if "synthesis_certificate_ref" in n]
    bound = _sum_bounds(instance_bounds)
    if len(instance_bounds) != 15 or Decimal(bound) > Decimal(str(result["synthesis"]["path_error_budget"])):
        raise FrontendError("INCOMPLETE_OR_OVER_BUDGET_SYNTHESIS")
    result["synthesis"].update({"status": "complete", "clifford_t_ready": True,
                                "unresolved_operation_ids": [], "table_version": TABLE_VERSION,
                                "phase_policy": "retain_classical_branch_global_phase_ledger",
                                "coherent_quantum_control_supported": False,
                                "certified_path_error_upper_bound": bound,
                                "certificate_kind": "static_directed_interval_operator_bound"})
    result["artifact_id"] += "-ct-v1"
    result["provenance"].update(task_id="T202", synthesis_source="finite-table-with-recomputed-certificates")
    result["input_hashes"]["rotation_table_sha256"] = _hash(ROTATIONS)
    result["template_hashes"] = {key: _hash(value) for key, value in result["templates"].items()}
    conditional = {}
    unconditional = 0
    for op in iter_logical_ops(result):
        if op["kind"] == "gate" and op["params"]["name"] in ("T", "TDG"):
            if op["condition"] is None:
                unconditional += 1
            else:
                bit = op["condition"]["bit"]
                conditional[bit] = conditional.get(bit, 0) + 1
    result["resource_summary"].update({
        "nonexact_feedback_count": 15, "unresolved_feedback_count": 0, "synthesized_feedback_count": 15,
        "unconditional_t_like": unconditional, "conditional_t_like_by_bit_equals_one": conditional,
        "total_t_like": unconditional + sum(conditional.values()),
        "total_t_like_status": "all_conditions_true_static_upper_bound",
        "path_t_like_status": "determined_only_after_explicit_phase_bits",
    })
    return result


def audit_synthesis(program: dict) -> list[dict]:
    """Recompute each actual word certificate; do not trust ready/count flags."""
    from .program import _hash
    errors = []
    try:
        if (program.get("synthesis", {}).get("status") != "complete"
                or program["synthesis"].get("unresolved_operation_ids") != []):
            raise ValueError("synthesis metadata disagrees with lowered program")
        refs = {}
        instances = [n for n in program["body"] if "synthesis_certificate_ref" in n]
        if len(instances) != 15:
            raise ValueError("expected all 15 retained small-angle instances")
        expected_phases = []
        for node in instances:
            ref = node["synthesis_certificate_ref"]
            template = program["templates"][ref]
            source = node["logical_source_op"]
            if (source["id"] != node["id"] or source["params"]["name"] != "P"
                    or node["condition_scope"] != "classical"
                    or node["condition"] != source["condition"]
                    or node["after"] != source["after"]
                    or node["bindings"] != {"q": source["qubits"][0]}):
                raise ValueError("source, condition, target or causal boundary mismatch: " + node["id"])
            metadata = template["metadata"]
            if metadata["angle_pi"] != source["params"]["angle_pi"]:
                raise ValueError("target angle changed: " + node["id"])
            for index, item in enumerate(template["body"]):
                op = item["op"]
                if (op["kind"] != "gate" or op["qubits"] != ["q"] or op["condition"] is not None
                        or op["reads"] or op["writes"]
                        or op["id"] != f"g{index:03d}"
                        or op["after"] != ([] if index == 0 else [f"g{index - 1:03d}"])):
                    raise ValueError("nonsequential or nonunitary synthesis word")
            if ref not in refs:
                word = [n["op"]["params"]["name"] for n in template["body"]]
                certificate = certify_rotation(word, metadata["angle_pi"], metadata["global_phase_pi"])
                recorded = program["synthesis_certificates"][ref]
                if any(recorded.get(key) != value for key, value in certificate.items()):
                    raise ValueError("stale or altered certificate: " + ref)
                if program["template_hashes"][ref] != _hash(template):
                    raise ValueError("synthesis template digest mismatch")
                refs[ref] = certificate
            if Decimal(refs[ref]["operator_error_upper_bound"]) > Decimal(str(source["params"]["error_budget"])):
                raise ValueError("per-operation precision unmet: " + node["id"])
            expected_phases.append({"source_operation_id": node["id"], "condition": node["condition"],
                                    "global_phase_pi": metadata["global_phase_pi"],
                                    "semantics": "exp(i*pi*phase)*chronological_word",
                                    "scope": "classical_branch_global_not_quantum_control"})
        if program["branch_global_phases"] != expected_phases:
            raise ValueError("missing or changed branch-global phase ledger")
        bound = _sum_bounds(refs[n["synthesis_certificate_ref"]]["operator_error_upper_bound"] for n in instances)
        if (bound != program["synthesis"]["certified_path_error_upper_bound"]
                or Decimal(bound) > Decimal(str(program["synthesis"]["path_error_budget"]))):
            raise ValueError("path error bound mismatch or exceeded")
        if program["synthesis"].get("coherent_quantum_control_supported") is not False:
            raise ValueError("coherent quantum control is not qualified")
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        errors.append({"code": "INVALID_SYNTHESIS_CERTIFICATE", "operation_id": "program", "message": str(exc)})
    return errors


def t_demand_for_phase(program: dict, bits: list[int]) -> dict:
    """Static inventory for supplied fake phase bits; never a runtime receipt."""
    from .program import FrontendError, require_clifford_t, iter_logical_ops
    if not isinstance(bits, list) or len(bits) != 8 or any(type(b) is not int or b not in (0, 1) for b in bits):
        raise FrontendError("INVALID_PHASE_BITS")
    require_clifford_t(program)
    values = {f"phase[{i}]": value for i, value in enumerate(bits)}
    requests = []
    for op in iter_logical_ops(program):
        if op["kind"] != "gate" or op["params"]["name"] not in ("T", "TDG"):
            continue
        if op["condition"] and values[op["condition"]["bit"]] != op["condition"]["equals"]:
            continue
        requests.append({"operation_id": op["id"], "gate": op["params"]["name"],
                         "target_qubit_id": op["qubits"][0], "condition": deepcopy(op["condition"]),
                         "source_ids": op["source_ids"].copy()})
    return {"schema_version": "TPathDemand/0.1.0", "artifact_id": program["artifact_id"] + "-demand-" + ''.join(map(str, bits)),
            "provenance": {"owner": "R2", "task_id": "T202", "logical_artifact_id": program["artifact_id"]},
            "execution_kind": "compile_plan", "origin": "fake", "sampled": False,
            "quantum_state_simulated": False, "hardware_executed": False, "loss_enabled": False,
            "input_bits_msb_first": bits.copy(), "t_like_count": len(requests), "requests": requests,
            "scope": "static_supplied_branch_inventory_not_consumption_receipt"}

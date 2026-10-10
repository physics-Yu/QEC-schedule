"""Consume the R5 execution-context/0.1 without producing runtime evidence."""
from .enola_kernel import StrategyError, digest


def validate_execution_context(context, dags, device, world):
    if (context.get("schema_version") != "execution-context/0.1" or context.get("device_hash") != digest(device)
        or context.get("world_state_hash") != digest(world)):
        raise StrategyError("EXECUTION_CONTEXT_FRONTIER", "Context must bind this exact device and current world")
    if context["time_us"] != world.get("time_us"):
        raise StrategyError("EXECUTION_CONTEXT_TIME", "Context and world clocks disagree")
    decisions = context["graph_decisions"]
    if set(decisions) != {d["artifact_id"] for d in dags}:
        raise StrategyError("EXECUTION_CONTEXT_DAGS", "Context must bind precisely this batch")
    for dag in dags:
        decision = decisions[dag["artifact_id"]]
        if (decision["physical_dag_sha256"] != digest(dag) or decision["execution_guard"] != dag.get("execution_guard") or
            decision["external_reads"] != dag.get("external_reads", [])):
            raise StrategyError("EXECUTION_CONTEXT_DAGS", "Original DAG, guard or external read identity changed")
        guard = dag.get("execution_guard")
        reads = set(dag.get("external_reads", [])) | ({guard["bit"]} if guard else set())
        for rid in reads:
            record = context["published_results"].get(rid)
            if (not record or record.get("origin") != "fake" or type(record.get("value")) is not int or record["value"] not in (0, 1)
                or record["ready_us"] > context["time_us"] or record["available_us"] > context["time_us"]
                or record["producer_ref"]["run_id"] != context["run_id"]
                or record["producer_ref"]["action_id"] != record["action_id"]
                or decision["result_refs"].get(rid) != record["producer_ref"]):
                raise StrategyError("PUBLISHED_RESULT_REQUIRED", "External input must be a published same-session producer result", result_id=rid)
        selected = not guard or context["published_results"][guard["bit"]]["value"] == guard["equals"]
        if decision["decision"] != ("execute" if selected else "skip"):
            raise StrategyError("EXECUTION_CONTEXT_GUARD", "Guard decision disagrees with the actual published bit")
        if not selected:
            raise StrategyError("PHYSICAL_DAG_GUARD_FALSE", "R5 must record this node skipped and select an executable batch", physical_dag_id=dag["artifact_id"])

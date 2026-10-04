"""Saved evidence checks use actual scheduling inputs, without any native solve."""
from copy import deepcopy
from dataclasses import replace
import importlib.util
from math import sqrt
from pathlib import Path

import pytest

from neutral_atom_kernel import DeclaredReportSource, GateSpec, KernelExecutor, Operation
from neutral_atom_kernel.model import thaw


spec = importlib.util.spec_from_file_location("native_memory_audit", Path(__file__).resolve().parents[1] / "tools/audit_native_kernel_memory.py")
reviewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reviewer)


def test_exact_nonzero_epoch_inputs_and_two_inflight_readout_restore():
    axes = {"rows": (0, 20), "columns": (0, 20)}
    target = {"rows": (0, 20), "columns": (20, 40)}
    kernel = KernelExecutor({"readout": (100, 100), "carried": (0, 0)},
                            (GateSpec("m", "MEASURE", ("readout",)),),
                            initial_aod_axes={"AOD_0": axes}, report_source=DeclaredReportSource(bits=(1,)), recording=True)
    # A noninteger block epoch deliberately makes subtracting absolute starts lossy.
    epoch = 200 * sqrt(30 / 110)
    kernel.run(kernel.bind_block("prelude", (Operation("prelude.wait", "WAIT", duration_us=epoch),)))
    move_end = 15 + 200 * sqrt(20 / 110)
    local = (Operation("read", "MEASURE", ("readout",), 500, gate_ids=("m",), report_ids=("result",), start_us=0, end_us=500),
             Operation("load", "LOAD", ("carried",), 15, start_us=0, end_us=15,
                       metadata={"source_axes": axes, "target_axes": axes}),
             Operation("move", "MOVE", ("carried",), move_end-15, positions=(("carried", (20, 0)),),
                       start_us=15, end_us=move_end, depends_on=("load",),
                       metadata={"source_axes": axes, "target_axes": target}))
    saved_block = {"execution_mode": "scheduled", "start_us": epoch,
                   "operations": [reviewer.operation_payload(op) for op in local]}
    global_ops = tuple(replace(op, start_us=epoch+op.start_us, end_us=epoch+op.end_us) for op in local)
    recovered = reviewer.block_inputs(saved_block, global_ops, {"time_us": epoch})
    assert recovered == local
    bad = deepcopy(saved_block)
    bad["operations"][2]["start_us"] += 1e-6; bad["operations"][2]["end_us"] += 1e-6
    with pytest.raises(reviewer.ReviewFailure, match="epoch-offset"):
        reviewer.block_inputs(bad, global_ops, {"time_us": epoch})

    block = kernel.bind_block("concurrent", recovered, execution_mode="scheduled")
    kernel.run(block, until_us=epoch+50)
    cut = kernel.checkpoint(include_journal=True)
    assert reviewer.check_midcut(cut, "result", local) == 2
    assert cut["measurement_results"] == {} and cut["report_source"]["cursor"] == 0
    restored = KernelExecutor.restore(cut)
    assert restored.checkpoint(include_journal=True) == cut
    kernel.run(); restored.run()
    final = kernel.checkpoint(include_journal=True)
    assert restored.checkpoint(include_journal=True) == final
    prelude = Operation("prelude.wait", "WAIT", duration_us=epoch)
    starts, groups, reports, times, cursor = reviewer.check_journal((prelude, *global_ops), thaw(kernel.journal), final)
    assert len(starts) == 2 and groups["concurrent"] == {"read", "load", "move"}
    assert reports == {"result": 1} and cursor == 1 and times == {"result": epoch+500}
    # Completion order differs from declaration order and must remain valid.
    completions = [entry["operation_id"] for entry in thaw(kernel.journal) if entry["event"] == "OPERATION_COMPLETED"]
    assert completions == ["prelude.wait", "load", "move", "read"]
    early = deepcopy(thaw(kernel.journal))
    event = next(entry for entry in early if entry.get("operation_id") == "read" and entry["event"] == "OPERATION_STARTED")
    event["reports"] = [["result", 1]]
    with pytest.raises(reviewer.ReviewFailure, match="before measurement"):
        reviewer.check_journal((prelude, *global_ops), early, final)


def test_midcut_cannot_label_finished_or_missing_measurement_as_unfinished():
    op = Operation("read", "MEASURE", ("a",), 500, gate_ids=("m",), report_ids=("result",), start_us=0, end_us=500)
    cut = {"time_us": 500, "measurement_results": {}, "inflight": [{"operation_id": "read", "start_us": 0, "end_us": 500}]}
    with pytest.raises(reviewer.ReviewFailure, match="actual cut"):
        reviewer.check_midcut(cut, "result", (op,))
    cut["time_us"] = 250; cut["measurement_results"] = {"result": 1}
    with pytest.raises(reviewer.ReviewFailure, match="already contains"):
        reviewer.check_midcut(cut, "result", (op,))


def test_batch_reports_follow_atom_order_when_source_gate_ids_are_permuted():
    gates = (GateSpec("ma", "MEASURE", ("a",)), GateSpec("mb", "MEASURE", ("b",)))
    kernel = KernelExecutor({"a": (100, 100), "b": (110, 100)}, gates,
                            report_source=DeclaredReportSource(bits=(1, 0)), recording=True)
    op = Operation("batch", "MEASURE", ("b", "a"), 500, gate_ids=("ma", "mb"),
                   report_ids=("rb", "ra"), start_us=0, end_us=500)
    kernel.run(kernel.bind_block("batch", (op,), execution_mode="scheduled"))
    checkpoint = kernel.checkpoint(include_journal=True)
    _, _, reports, times, cursor = reviewer.check_journal((op,), thaw(kernel.journal), checkpoint, gates=gates)
    assert reports == {"rb": 1, "ra": 0} and times == {"rb": 500, "ra": 500} and cursor == 2
    assert checkpoint["report_bindings"]["rb"]["gate_id"] == "mb"

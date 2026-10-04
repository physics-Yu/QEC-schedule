import json
import hashlib

import pytest

from neutral_atom_kernel import DeclaredReportSource, GateSpec, KernelError, KernelExecutor, Operation


def test_reports_appear_only_at_measure_completion_and_failed_preview_is_atomic():
    gates = (GateSpec("m0", "MEASURE", ("Q0",)), GateSpec("m1", "MEASURE", ("Q1",)))
    kernel = KernelExecutor({"Q0": (0, 0), "Q1": (10, 0)}, gates,
                            report_source=DeclaredReportSource(bits=(1,)))
    op = Operation("read", "MEASURE", ("Q0", "Q1"), 10, gate_ids=("m0", "m1"))
    kernel.run(kernel.bind_block("read", (op,)), until_us=9)
    before = kernel.checkpoint_json(include_journal=True)
    assert kernel.observe().measurement_results == {}
    assert kernel.observe().completed_gate_ids == ()
    assert kernel.observe().report_source_cursor == 0
    with pytest.raises(KernelError, match="exhausted") as error:
        kernel.wait_until(10)
    assert error.value.code == "MISSING_REPORT"
    assert kernel.checkpoint_json(include_journal=True) == before
    assert kernel.observe().pending_events == 1

    good = KernelExecutor({"Q0": (0, 0)}, (gates[0],), report_source=DeclaredReportSource(bits=(1,)))
    good.run(good.bind_block("read", (Operation("read", "MEASURE", ("Q0",), 10, gate_ids=("m0",)),)), until_us=9)
    observation = good.wait_until(10)
    assert observation.measurement_results == {"m0": 1}
    assert observation.measurement_completion_times_us == {"m0": 10}
    assert observation.completed_gate_ids == ("m0",)
    assert observation.report_source_cursor == 1


def test_continuous_blocks_keep_locations_clock_dependency_and_report_history():
    gates = (GateSpec("h", "H", ("Q0",)), GateSpec("m", "MEASURE", ("Q0",), ("h",)))
    kernel = KernelExecutor({"Q0": (0, 0)}, gates, report_source=DeclaredReportSource(bits=(1,)))
    first = (
        Operation("load", "LOAD", ("Q0",), 2),
        Operation("move", "MOVE", ("Q0",), 3, (("Q0", (12, 4)),)),
        Operation("h", "GATE", ("Q0",), 1, gate_ids=("h",)),
    )
    observation = kernel.run(kernel.bind_block("first", first))
    assert observation.positions == {"Q0": (12, 4)}
    assert observation.holders == {"Q0": "AOD_0"}
    assert observation.time_us == 6
    second = (
        Operation("store", "STORE", ("Q0",), 2),
        Operation("read", "MEASURE", ("Q0",), 4, gate_ids=("m",)),
    )
    observation = kernel.run(kernel.bind_block("second", second))
    assert observation.positions == {"Q0": (12, 4)}
    assert observation.holders == {"Q0": "slm"}
    assert observation.time_us == 12
    kernel.activate_fragment("reuse", (GateSpec("r", "RESET", ("Q0",), ("m",)),), requires_report_ids=("m",))
    observation = kernel.run(kernel.bind_block("reset", (Operation("r", "RESET", ("Q0",), 2, gate_ids=("r",)),)))
    assert observation.measurement_results == {"m": 1}
    assert observation.measurement_completion_times_us == {"m": 12}
    assert observation.report_source_cursor == 1
    assert observation.positions == {"Q0": (12, 4)}
    assert observation.completed_gate_ids == ("h", "m", "r")
    assert observation.completed_fragment_ids == ("__initial__", "reuse")
    assert observation.completed and observation.time_us == 14
    assert kernel.observe() is observation
    with pytest.raises(TypeError):
        observation.holders["Q0"] = "AOD_0"


def test_stale_block_duplicate_effect_and_invalid_carrier_do_not_commit():
    kernel = KernelExecutor({"Q0": (0, 0)}, (GateSpec("h", "H", ("Q0",)),))
    stale = kernel.bind_block("stale", (Operation("wait", "WAIT", duration_us=1),))
    kernel.wait_until(2)
    before = kernel.checkpoint_json()
    with pytest.raises(KernelError) as error:
        kernel.run(stale)
    assert error.value.code == "STALE_BLOCK"
    assert kernel.checkpoint_json() == before
    with pytest.raises(KernelError) as error:
        kernel.run(kernel.bind_block("badmove", (Operation("move", "MOVE", ("Q0",), 1, (("Q0", (5, 0)),)),)))
    assert error.value.code == "CARRIER_STATE"
    assert kernel.checkpoint_json() == before
    kernel.run(kernel.bind_block("h", (Operation("h", "GATE", ("Q0",), 1, gate_ids=("h",)),)))
    before = kernel.checkpoint_json()
    with pytest.raises(KernelError) as error:
        kernel.run(kernel.bind_block("h2", (Operation("h2", "GATE", ("Q0",), 1, gate_ids=("h",)),)))
    assert error.value.code == "DUPLICATE_GATE_EFFECT"
    assert kernel.checkpoint_json() == before


def test_report_gates_and_fragment_activation_require_committed_dependencies():
    gates = (GateSpec("m", "MEASURE", ("Q0",)), GateSpec("h", "H", ("Q0",), ("m",)))
    kernel = KernelExecutor({"Q0": (0, 0)}, gates, report_source=DeclaredReportSource(bits=(0,)))
    before = kernel.checkpoint_json()
    with pytest.raises(KernelError) as error:
        kernel.run(kernel.bind_block("h", (Operation("h", "GATE", ("Q0",), 1, gate_ids=("h",)),)))
    assert error.value.code == "DEPENDENCY_NOT_READY"
    with pytest.raises(KernelError) as error:
        kernel.activate_fragment("late", (GateSpec("x", "X", ("Q0",)),), requires_report_ids=("m",))
    assert error.value.code == "REPORT_NOT_READY"
    assert kernel.checkpoint_json() == before
    with pytest.raises(KernelError) as error:
        kernel.run(kernel.bind_block("wrong", (Operation("wrong", "RESET", ("Q0",), 1, gate_ids=("m",)),)))
    assert error.value.code == "GATE_IDENTITY"
    assert kernel.checkpoint_json() == before


def test_checkpoint_restores_pending_report_future_bits_carriers_and_fragments():
    gates = (GateSpec("m0", "MEASURE", ("Q0",)), GateSpec("m1", "MEASURE", ("Q0",), ("m0",)))
    kernel = KernelExecutor({"Q0": (0, 0)}, gates,
                            report_source=DeclaredReportSource(source_id="model", version="v2", seed=128, probability_one=0.5))
    kernel.run(kernel.bind_block("read0", (
        Operation("load", "LOAD", ("Q0",), 2),
        Operation("move", "MOVE", ("Q0",), 3, (("Q0", (10, 5)),)),
        Operation("read0", "MEASURE", ("Q0",), 10, gate_ids=("m0",)),
    )), until_us=9)
    restored = KernelExecutor.restore(json.loads(kernel.checkpoint_json(include_journal=True)))
    assert restored.observe() == kernel.observe()
    for current in (kernel, restored):
        current.run()
        current.activate_fragment("reset", (GateSpec("r", "RESET", ("Q0",), ("m0",)),), requires_report_ids=("m0",))
        current.run(current.bind_block("read1", (
            Operation("read1", "MEASURE", ("Q0",), 7, gate_ids=("m1",)),
            Operation("reset", "RESET", ("Q0",), 1, gate_ids=("r",)),
        )))
    assert restored.observe() == kernel.observe()
    assert restored.state_hash() == kernel.state_hash()
    assert restored.checkpoint_json(include_journal=True) == kernel.checkpoint_json(include_journal=True)
    assert restored.observe().report_source_cursor == 2


def test_recording_and_failing_sink_do_not_change_committed_execution():
    def broken_sink(record):
        raise RuntimeError("observer failure")

    kernels = [KernelExecutor({"Q0": (0, 0)}, (GateSpec("m", "MEASURE", ("Q0",)),),
                              report_source=DeclaredReportSource(bits=(1,)), recording=enabled,
                              journal_sink=broken_sink if not enabled else None) for enabled in (True, False)]
    for kernel in kernels:
        kernel.run(kernel.bind_block("run", (
            Operation("load", "LOAD", ("Q0",), 2),
            Operation("move", "MOVE", ("Q0",), 3, (("Q0", (4, 5)),)),
            Operation("store", "STORE", ("Q0",), 2),
            Operation("measure", "MEASURE", ("Q0",), 4, gate_ids=("m",)),
        )))
    assert kernels[0].observe() == kernels[1].observe()
    assert kernels[0].state_hash() == kernels[1].state_hash()
    assert kernels[0].journal and not kernels[1].journal
    assert kernels[1].journal_sink_errors
    completions = [record for record in kernels[0].journal if record["event"] == "OPERATION_COMPLETED"]
    assert completions[1]["changed_atoms"] == (("Q0", ("AOD_0", 0.0, 0.0), ("AOD_0", 4.0, 5.0)),)
    assert completions[-1]["reports"] == (("m", 1),)


def test_configure_cost_axes_persistence_and_empty_carrier_guard():
    kernel = KernelExecutor({"Q0": (10, 20)}, initial_aod_axes={"AOD_0": {"rows": (0,), "columns": (0,)}})
    kernel.run(kernel.bind_block("move", (
        Operation("configure", "CONFIGURE", duration_us=5,
                  metadata={"source_axes": {"rows": (0,), "columns": (0,)}, "target_axes": {"rows": (20,), "columns": (10,)}}),
        Operation("load", "LOAD", ("Q0",), 2),
        Operation("move", "MOVE", ("Q0",), 3, (("Q0", (30, 40)),)),
    )))
    assert kernel.observe().time_us == 10
    assert kernel.observe().aod_axes["AOD_0"] == {"rows": (40,), "columns": (30,), "active_rows": (40,), "active_columns": (30,)}
    before = kernel.checkpoint_json()
    with pytest.raises(KernelError) as error:
        kernel.run(kernel.bind_block("badconfigure", (Operation("c", "CONFIGURE", duration_us=1,
                  metadata={"target_axes": {"rows": (0,), "columns": (0,)}}),)))
    assert error.value.code == "CARRIER_STATE"
    assert kernel.checkpoint_json() == before
    kernel.run(kernel.bind_block("store", (Operation("store", "STORE", ("Q0",), 2),)))
    axes = kernel.observe().aod_axes["AOD_0"]
    assert axes == {"rows": (40,), "columns": (30,), "active_rows": (), "active_columns": ()}
    assert KernelExecutor.restore(kernel.checkpoint()).observe() == kernel.observe()


def _pending_checkpoint():
    gates = (GateSpec("m0", "MEASURE", ("Q0",)), GateSpec("m1", "MEASURE", ("Q0",), ("m0",)))
    kernel = KernelExecutor({"Q0": (0, 0)}, gates, report_source=DeclaredReportSource(bits=(1, 0)))
    kernel.run(kernel.bind_block("pending", (
        Operation("load", "LOAD", ("Q0",), 2),
        Operation("move", "MOVE", ("Q0",), 3, (("Q0", (10, 5)),)),
        Operation("m0", "MEASURE", ("Q0",), 3, gate_ids=("m0",)),
        Operation("m1", "MEASURE", ("Q0",), 5, gate_ids=("m1",)),
    )), until_us=10)
    return kernel.checkpoint(include_journal=True)


@pytest.mark.parametrize("field", ("position", "report", "source_cursor", "gate", "pending"))
def test_checkpoint_integrity_rejects_tampered_location_report_cursor_gate_and_pending(field):
    payload = _pending_checkpoint()
    if field == "position":
        payload["atoms"][0]["position"][0] += 5
    elif field == "report":
        payload["measurement_results"]["m0"] = 0
    elif field == "source_cursor":
        payload["report_source"]["cursor"] += 1
    elif field == "gate":
        payload["gates"][0]["kind"] = "RESET"
    else:
        payload["running"][1] += 1
    with pytest.raises(KernelError) as error:
        KernelExecutor.restore(payload)
    assert error.value.code == "CHECKPOINT_INTEGRITY"


def _refresh_digest(payload):
    content = {key: value for key, value in payload.items() if key != "checkpoint_digest"}
    payload["checkpoint_digest"] = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def test_restore_replays_declared_reports_and_checks_completed_measurement_binding():
    payload = _pending_checkpoint()
    payload["measurement_results"]["m0"] = 0
    _refresh_digest(payload)
    with pytest.raises(KernelError) as error:
        KernelExecutor.restore(payload)
    assert error.value.code == "CHECKPOINT_REPORT"
    payload = _pending_checkpoint()
    payload["report_bindings"]["m0"]["gate_id"] = "m1"
    _refresh_digest(payload)
    with pytest.raises(KernelError) as error:
        KernelExecutor.restore(payload)
    assert error.value.code == "CHECKPOINT_REPORT"
    payload = _pending_checkpoint()
    payload["report_bindings"]["m0"]["operation_id"] = "unexecuted-operation"
    _refresh_digest(payload)
    with pytest.raises(KernelError) as error:
        KernelExecutor.restore(payload)
    assert error.value.code == "CHECKPOINT_JOURNAL"


def test_statistical_report_order_survives_sorted_json_and_partial_journal_restore():
    gates = (GateSpec("z-first", "MEASURE", ("Q0",)), GateSpec("a-second", "MEASURE", ("Q0",), ("z-first",)))
    kernel = KernelExecutor({"Q0": (0, 0)}, gates,
                            report_source=DeclaredReportSource(source_id="counter-model", seed=82, probability_one=.5))
    kernel.run(kernel.bind_block("first", (Operation("first", "MEASURE", ("Q0",), 1, gate_ids=("z-first",)),)))
    restored = KernelExecutor.restore(kernel.checkpoint_json())
    restored.run(restored.bind_block("second", (Operation("second", "MEASURE", ("Q0",), 1, gate_ids=("a-second",)),)))
    final = KernelExecutor.restore(restored.checkpoint_json(include_journal=True))
    assert final.observe() == restored.observe()
    assert final.checkpoint()["report_commit_order"] == ["z-first", "a-second"]


def test_completed_checkpoint_restores_idle_cursor_and_exact_serialized_evidence():
    kernel = KernelExecutor({"Q0": (0, 0)}, (GateSpec("m", "MEASURE", ("Q0",)),),
                            report_source=DeclaredReportSource(bits=(1,)))
    kernel.run(kernel.bind_block("done", (
        Operation("read", "MEASURE", ("Q0",), 2, gate_ids=("m",)),
        Operation("wait", "WAIT", duration_us=3),
    )))
    before = kernel.checkpoint_json(include_journal=True)
    assert kernel.checkpoint()["operation_cursor"] == 2
    restored = KernelExecutor.restore(before)
    assert restored.observe() == kernel.observe()
    assert restored.checkpoint_json(include_journal=True) == before

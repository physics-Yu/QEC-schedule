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


def _concurrent_kernel(*, recording=True, bits=(1,), motion_profile="row_column"):
    gates = (GateSpec("h0", "H", ("Q1",)), GateSpec("h1", "H", ("Q4",)), GateSpec("m", "MEASURE", ("Q3",)))
    kernel = KernelExecutor({"Q0": (0, 0), "Q2": (10, 0), "Q1": (100, 100), "Q3": (200, 100), "Q4": (300, 100)},
        gates, initial_holders={"Q0": "AOD_0", "Q2": "AOD_0"},
        initial_aod_axes={"AOD_0": {"rows": (0,), "columns": (0, 10)}},
        report_source=DeclaredReportSource(bits=bits), recording=recording)
    operations = (
        Operation("move", "MOVE", ("Q0", "Q2"), 10, (("Q0", (20, 10)), ("Q2", (30, 10))),
                  metadata={"target_axes": {"rows": (10,), "columns": (20, 30)}}, start_us=0, motion_profile=motion_profile),
        Operation("h0", "GATE", ("Q1",), 1, gate_ids=("h0",), start_us=0),
        Operation("h1", "GATE", ("Q4",), 1, gate_ids=("h1",), start_us=0),
        Operation("read", "MEASURE", ("Q3",), 5, gate_ids=("m",), start_us=0),
    )
    return kernel, operations


def test_scheduled_independent_effects_and_batched_aod_motion_share_one_clock():
    kernel, ops = _concurrent_kernel()
    kernel.run(kernel.bind_block("parallel", ops, execution_mode="scheduled"), until_us=1)
    assert kernel.observe().completed_gate_ids == ("h0", "h1")
    assert kernel.observe().measurement_results == {}
    predicted = kernel.evaluate(2.5)
    snapshot = kernel.checkpoint_json()
    assert kernel.checkpoint_json() == snapshot
    observed = kernel.wait_until(2.5)
    assert observed.positions == predicted.positions
    assert observed.aod_axes == predicted.aod_axes
    assert observed.positions["Q0"] == (3.125, 1.5625)
    assert observed.positions["Q2"] == (13.125, 1.5625)
    assert observed.committed_positions["Q0"] == (0, 0)
    assert observed.holders["Q0"] == "AOD_0"
    assert observed.aod_axes["AOD_0"]["rows"] == (1.5625,)
    assert observed.resource_owners["AOD_0"] == "move"
    observed = kernel.run()
    assert observed.time_us == 10
    assert observed.positions["Q0"] == (20, 10)
    assert observed.positions["Q2"] == (30, 10)
    assert observed.measurement_results == {"m": 1}
    assert observed.measurement_completion_times_us == {"m": 5}
    assert observed.completed and observed.pending_events == 0
    assert all(record["trajectory_profile"] == "cubic" for record in kernel.journal if record["event"] == "OPERATION_STARTED")


def test_multi_inflight_checkpoint_recovers_exact_queue_reports_journal_and_recording_equivalence():
    kernel, ops = _concurrent_kernel()
    kernel.run(kernel.bind_block("parallel", ops, execution_mode="scheduled"), until_us=.5)
    payload = kernel.checkpoint(include_journal=True)
    assert len(payload["inflight"]) == 4
    assert kernel.observe().measurement_results == {}
    encoded = kernel.checkpoint_json(include_journal=True)
    restored = KernelExecutor.restore(encoded)
    assert restored.observe() == kernel.observe()
    assert restored.checkpoint_json(include_journal=True) == encoded
    kernel.run(); restored.run()
    assert restored.observe() == kernel.observe()
    assert restored.checkpoint_json(include_journal=True) == kernel.checkpoint_json(include_journal=True)
    quiet, ops = _concurrent_kernel(recording=False)
    quiet.run(quiet.bind_block("parallel", ops, execution_mode="scheduled"), until_us=.5)
    quiet.run()
    assert quiet.observe() == kernel.observe()
    assert quiet.state_hash() == kernel.state_hash()
    assert not quiet.journal
    forged = payload
    forged["inflight"][0]["resources"].remove("AOD_0")
    _refresh_digest(forged)
    with pytest.raises(KernelError) as error:
        KernelExecutor.restore(forged)
    assert error.value.code == "CHECKPOINT_EVENT"


def test_concurrent_measurement_failure_does_not_consume_event_or_partially_commit():
    kernel, ops = _concurrent_kernel(bits=())
    kernel.run(kernel.bind_block("parallel", ops, execution_mode="scheduled"), until_us=4)
    before = kernel.checkpoint_json(include_journal=True)
    with pytest.raises(KernelError) as error:
        kernel.wait_until(5)
    assert error.value.code == "MISSING_REPORT"
    assert kernel.checkpoint_json(include_journal=True) == before
    assert kernel.observe().report_source_cursor == 0
    assert kernel.observe().completed_gate_ids == ("h0", "h1")


def test_explicit_rigid_motion_uses_linear_common_progress():
    kernel, ops = _concurrent_kernel(motion_profile="rigid")
    observed = kernel.run(kernel.bind_block("parallel", ops, execution_mode="scheduled"), until_us=2.5)
    assert observed.positions["Q0"] == (5, 2.5)
    assert observed.positions["Q2"] == (15, 2.5)
    assert observed.committed_positions["Q0"] == (0, 0)


@pytest.mark.parametrize("case", ("same_aod", "mobile_gate", "different_unitary", "extra_resource"))
def test_scheduled_required_atom_device_laser_and_declared_resources_reject_overlap_atomically(case):
    kernel, operations = _concurrent_kernel()
    if case == "same_aod":
        operations = (operations[0], Operation("secondmove", "MOVE", ("Q0", "Q2"), 2,
            (("Q0", (40, 20)), ("Q2", (50, 20))), start_us=1))
    elif case == "mobile_gate":
        kernel.activate_fragment("mobile", (GateSpec("mobile", "H", ("Q0",)),))
        operations = (operations[0], Operation("mobile", "GATE", ("Q0",), 1, gate_ids=("mobile",), start_us=0))
    elif case == "different_unitary":
        kernel.activate_fragment("x", (GateSpec("x", "X", ("Q3",)),))
        operations = (operations[1], Operation("x", "GATE", ("Q3",), 1, gate_ids=("x",), start_us=0))
    else:
        operations = (Operation("a", "WAIT", duration_us=2, resources=("CONTROL_BUS",), start_us=0),
                      Operation("b", "WAIT", duration_us=1, resources=("CONTROL_BUS",), start_us=0))
    before = kernel.checkpoint_json()
    with pytest.raises(KernelError) as error:
        kernel.run(kernel.bind_block("invalid", operations, execution_mode="scheduled"))
    assert error.value.code == ("LASER_KIND_CONFLICT" if case == "different_unitary" else "RESOURCE_CONFLICT")
    assert kernel.checkpoint_json() == before


def test_scheduled_same_time_completion_releases_dependency_and_zero_duration_operations():
    kernel = KernelExecutor({"Q0": (0, 0)}, initial_aod_axes={"AOD_0": {"rows": (0,), "columns": (0,)}})
    ops = (Operation("configure", "CONFIGURE", metadata={"target_axes": {"rows": (0,), "columns": (0,)}}, start_us=0),
           Operation("load", "LOAD", ("Q0",), 2, start_us=0, depends_on=("configure",)),
           Operation("move", "MOVE", ("Q0",), 3, (("Q0", (10, 0)),), start_us=2, depends_on=("load",)))
    observed = kernel.run(kernel.bind_block("chain", ops, execution_mode="scheduled"))
    assert observed.time_us == 5 and observed.positions["Q0"] == (10, 0)
    events = [(record["event"], record.get("operation_id"), record["time_us"]) for record in kernel.journal if record["event"].startswith("OPERATION")]
    assert events[:3] == [("OPERATION_STARTED", "configure", 0), ("OPERATION_COMPLETED", "configure", 0), ("OPERATION_STARTED", "load", 0)]
    assert events[3:5] == [("OPERATION_COMPLETED", "load", 2), ("OPERATION_STARTED", "move", 2)]


def test_legacy_integrity_checkpoint_restores_serial_running_state():
    payload = _pending_checkpoint()
    payload["version"] = 1
    for field in ("block_start_us", "block_completed_operation_ids", "serial_context", "inflight", "scheduled_events", "scheduled_resources"):
        payload.pop(field)
    payload["active_block"].pop("execution_mode")
    for operation in payload["active_block"]["operations"]:
        for field in ("start_us", "depends_on", "resources", "motion_profile"):
            operation.pop(field)
    _refresh_digest(payload)
    restored = KernelExecutor.restore(payload)
    assert restored.observe().measurement_results == {"m0": 1}
    assert restored.observe().time_us == 10
    restored.run()
    assert restored.observe().measurement_results == {"m0": 1, "m1": 0}


@pytest.mark.parametrize("explicit_end", (False, True))
def test_scheduled_canonical_block_boundaries_and_flat_global_boundaries_do_not_depend_on_addition_order(explicit_end):
    epoch = 123456.7
    offsets = (0., .3, .5, .86)
    durations = (.3, .2, .36, 1.)
    ends = (.3, .5, .86, 1.86)
    relative = tuple(Operation(f"w{index}", "WAIT", duration_us=duration, start_us=start,
                              end_us=end if explicit_end else None,
                              depends_on=(f"w{index-1}",) if index else ())
                     for index, (start, end, duration) in enumerate(zip(offsets, ends, durations)))
    kernel = KernelExecutor({"Q0": (0, 0)})
    kernel.wait_until(epoch)
    kernel.run(kernel.bind_block("relative", relative, execution_mode="scheduled"), until_us=epoch+.4)
    saved = kernel.checkpoint_json(include_journal=True)
    restored = KernelExecutor.restore(saved)
    assert restored.checkpoint_json(include_journal=True) == saved
    kernel.run(); restored.run()
    assert kernel.observe().time_us == epoch+1.86
    assert restored.observe() == kernel.observe()
    if explicit_end:
        flat = tuple(Operation(op.id, op.kind, duration_us=op.duration_us,
                               start_us=epoch+op.start_us, end_us=epoch+op.end_us, depends_on=op.depends_on) for op in relative)
        replay = KernelExecutor({"Q0": (0, 0)})
        replay.run(replay.bind_block("flat", flat, execution_mode="scheduled"))
        assert replay.observe().time_us == kernel.observe().time_us
        assert replay.observe().completed_operation_ids == kernel.observe().completed_operation_ids


def test_explicit_end_accepts_only_representation_error_and_rejects_hidden_timing_changes():
    Operation("rounded", "WAIT", duration_us=.36, start_us=123456.7, end_us=123456.7+.36)
    with pytest.raises(ValueError, match="floating-point"):
        Operation("changed", "WAIT", duration_us=.36, start_us=123456.7, end_us=123456.7+.360001)
    with pytest.raises(ValueError, match="floating-point"):
        Operation("zero", "WAIT", duration_us=0, start_us=1., end_us=1.0000000000000002)


def test_independent_readout_restores_historical_start_axes_after_other_device_load_and_move():
    kernel = KernelExecutor({"Q0": (0, 0), "Q1": (100, 100)}, (GateSpec("m", "MEASURE", ("Q1",)),),
        initial_aod_axes={"AOD_0": {"rows": (0,), "columns": (0,)}}, report_source=DeclaredReportSource(bits=(1,)))
    epoch = 100.1
    kernel.wait_until(epoch)
    ops = (Operation("read", "MEASURE", ("Q1",), 500, gate_ids=("m",), start_us=0, end_us=500),
           Operation("load", "LOAD", ("Q0",), 15, start_us=0, end_us=15),
           Operation("move", "MOVE", ("Q0",), 100, (("Q0", (10, 10)),), start_us=15, end_us=115, depends_on=("load",)))
    kernel.run(kernel.bind_block("parallel", ops, execution_mode="scheduled"), until_us=epoch+50)
    assert kernel.observe().inflight_operations == ("read", "move")
    assert "AOD_0" not in kernel.checkpoint()["inflight"][0]["resources"]
    saved = kernel.checkpoint_json(include_journal=True)
    restored = KernelExecutor.restore(saved)
    assert restored.observe() == kernel.observe()
    assert restored.checkpoint_json(include_journal=True) == saved
    kernel.run(); restored.run()
    assert restored.checkpoint_json(include_journal=True) == kernel.checkpoint_json(include_journal=True)
    assert restored.observe().measurement_results == {"m": 1}
    assert restored.observe().time_us == epoch+500

"""Public orchestration only; module gaps fail explicitly, never become fixture success."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import sys
import time

from . import __version__


class PipelineError(ValueError):
    pass


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_bytes().decode("utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)
    return {"path": path.name, "bytes": len(data), "byte_sha256": hashlib.sha256(data).hexdigest(), "canonical_sha256": canonical_hash(value)}


def public_api(requirements):
    found, missing = {}, []
    for module, names in requirements.items():
        try:
            obj = importlib.import_module(f"na_pipeline.{module}")
        except ModuleNotFoundError as exc:
            if exc.name != f"na_pipeline.{module}":
                raise PipelineError(f"DEPENDENCY_IMPORT_FAILED {module}: {exc}") from exc
            missing.append(f"na_pipeline.{module}")
            continue
        for name in names:
            fn = getattr(obj, name, None)
            if not callable(fn):
                missing.append(f"na_pipeline.{module}.{name}")
            else:
                found[name] = fn
    if missing:
        raise PipelineError("UPSTREAM_NOT_READY: " + ", ".join(missing))
    return found


def code_identity():
    root = Path(__file__).parent
    hashes = {str(p.relative_to(root)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*.py"))}
    import viewer
    for p in sorted(Path(viewer.__file__).parent.iterdir()):
        if p.suffix == '.py' or p.name in {'viewer.html','viewer.js','viewer.css','hierarchy.html','hierarchy.js'}:
            hashes["viewer/" + p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return hashes


@contextmanager
def stage(manifest, out, name):
    manifest["current_stage"] = name
    manifest["status"] = "running"
    write_json(out / "manifest.json", manifest)
    started = time.perf_counter()
    try:
        yield
    finally:
        manifest["stage_wall_seconds"][name] = time.perf_counter() - started
        write_json(out / "manifest.json", manifest)


def evidence_check(value, kind):
    for key in ("quantum_state_simulated", "hardware_executed", "loss_enabled"):
        if value.get(key) is not False:
            raise PipelineError(f"EVIDENCE_LABEL_INVALID {key}: expected false")
    if value.get("execution_kind") != kind:
        raise PipelineError(f"EXECUTION_KIND_INVALID: expected {kind}")
    if kind == "fake_event_run" and (value.get("measurement_origin") != "fake" or value.get("sampled") is not False):
        raise PipelineError("FAKE_TRACE_LABEL_INVALID: measurement_origin=fake and sampled=false required")


def make_explicit_scenario(atom, value):
    results = {}
    for action in atom["actions"]:
        if action["kind"] == "measure":
            rid = action["payload"]["result_id"]
            if rid in results:
                raise PipelineError(f"DUPLICATE_RESULT_ID: {rid}")
            results[rid] = {"value": value, "origin": "fake"}
    return {"schema_version": "ScenarioInput/0.2.0-draft", "artifact_id": atom["artifact_id"] + f"/explicit-fake-{value}", "provenance": {"producer": "R7 CLI explicit scenario enumeration", "fixture": bool(atom.get("provenance", {}).get("fixture", False)), "policy": f"user_cli_selected_constant_{value}", "sampling": "none"}, "execution_kind": "scenario", "quantum_state_simulated": False, "hardware_executed": False, "loss_enabled": False, "results": results}


def slice_command(args):
    api = public_api({"device": ["default_device", "validate_device"], "qec": ["build_two_block_slice"], "backend": ["compile_physical"], "runtime": ["run"], "validation": ["validate"]})
    if args.rounds < 1:
        raise PipelineError("rounds must be >= 1")
    if args.out.exists() and any(args.out.iterdir()) and not args.resume:
        raise PipelineError("OUTPUT_NOT_EMPTY: choose a fresh directory or --resume")
    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out / "manifest.json"
    previous = read_json(manifest_path) if args.resume and manifest_path.exists() else None
    if previous:
        history = args.out / "attempts" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        history.mkdir(parents=True)
        # Preserve prior execution evidence before starting an independent run.
        for name in ("manifest.json", "device.json", "physical.json", "atom.json", "scenario.json", "trace.json", "validation.json", "viewer.html"):
            path = args.out / name
            if path.is_file():
                (history / name).write_bytes(path.read_bytes())
    manifest = {"schema_version": "na-run-manifest/0.1.0", "created_at_utc": datetime.now(timezone.utc).isoformat(), "producer_version": __version__, "kb_revision": "kb-0004", "interface_version": "IF-MVP-001/0.2.1-draft", "execution_kind": "fake_event_run", "quantum_state_simulated": False, "hardware_executed": False, "loss_enabled": False, "integration": "real_producer_modules", "fixture": False, "python": sys.version, "host": platform.node(), "source_byte_sha256": code_identity(), "stage_wall_seconds": {}, "files": {}, "engineering_acceptance": "pending", "user_visual_acceptance": "pending"}
    def save(name, value):
        manifest["files"][name] = write_json(args.out / f"{name}.json", value)
    try:
        with stage(manifest, args.out, "build_structured_inputs"):
            device = api["default_device"]()
            errors = api["validate_device"](device)
            if errors:
                raise PipelineError(f"DEVICE_INVALID: {errors}")
            physical = api["build_two_block_slice"](rounds=args.rounds)
            identity = {"code": manifest["source_byte_sha256"], "device": canonical_hash(device), "physical": canonical_hash(physical), "rounds": args.rounds, "max_ops": args.max_ops}
            manifest["compile_identity"] = identity
            reusable = previous and previous.get("compile_identity") == identity and "atom" in previous.get("files", {})
            atom_path = args.out / "atom.json"
            if reusable:
                reusable = atom_path.exists() and hashlib.sha256(atom_path.read_bytes()).hexdigest() == previous["files"]["atom"]["byte_sha256"]
            if args.resume and previous and not reusable:
                raise PipelineError("RESUME_IDENTITY_MISMATCH_OR_NO_COMPILE_CHECKPOINT: use a fresh output directory; old outputs retained")
            save("device", device)
            save("physical", physical)
        with stage(manifest, args.out, "compile_layout_route_schedule"):
            atom = read_json(atom_path) if reusable else api["compile_physical"](physical, device, max_ops=args.max_ops)
            if atom.get("complete") is not True:
                raise PipelineError("INCOMPLETE_COMPILE: no runtime or viewer acceptance")
            evidence_check(atom, "compile_plan")
            manifest["fixture"] = bool(atom.get("provenance", {}).get("fixture", False))
            if manifest["fixture"]:
                manifest["integration"] = "fixture_producers_not_real_chain"
            manifest["compile_checkpoint_reused"] = bool(reusable)
            save("atom", atom)
        with stage(manifest, args.out, "scenario"):
            scenario = read_json(args.scenario) if args.scenario else make_explicit_scenario(atom, args.fake_value)
            save("scenario", scenario)
        with stage(manifest, args.out, "runtime"):
            trace = api["run"](atom, scenario, device)
            evidence_check(trace, "fake_event_run")
            save("trace", trace)
        with stage(manifest, args.out, "independent_validation"):
            report = api["validate"](atom, device, trace=trace, physical_program=physical)
            save("validation", report)
        with stage(manifest, args.out, "viewer_output"):
            from viewer import export_view
            viewer_path = args.out / "viewer.html"
            export_view(args.out / "atom.json", viewer_path, trace_path=args.out / "trace.json", device_path=args.out / "device.json", report_path=args.out / "validation.json")
            manifest["files"]["viewer"] = {"path": "viewer.html", "byte_sha256": hashlib.sha256(viewer_path.read_bytes()).hexdigest()}
        manifest["status"] = "completed" if report.get("passed") is True else "validation_failed_or_unverified"
        manifest["engineering_acceptance"] = "independent_report_passed" if report.get("passed") is True else "failed_or_unverified"
        manifest["source_snapshot_stable"] = code_identity() == manifest["source_byte_sha256"]
        if not manifest["source_snapshot_stable"]:
            manifest["status"] = "source_changed_during_run_incomplete"
            manifest["engineering_acceptance"] = "unverified_source_identity"
        manifest["current_stage"] = "done"
        write_json(manifest_path, manifest)
        print(json.dumps({"status": manifest["status"], "manifest": str(manifest_path.resolve()), "viewer": str(viewer_path.resolve()), "user_visual_acceptance": "pending"}, ensure_ascii=False))
        return 0 if manifest["status"] == "completed" else 1
    except Exception as exc:
        manifest.update(status="incomplete", error={"type": type(exc).__name__, "message": str(exc)})
        partial = getattr(exc, "partial_program", None)
        if partial is not None:
            save("partial_atom", partial)
        write_json(manifest_path, manifest)
        raise


def validate_command(args):
    api = public_api({"validation": ["validate"]})
    report = api["validate"](read_json(args.atom), read_json(args.device), trace=read_json(args.trace) if args.trace else None, physical_program=read_json(args.physical) if args.physical else None)
    files = {k: getattr(args, k) for k in ("atom", "device", "trace", "physical") if getattr(args, k)}
    receipt = {"schema_version": "na-validation-byte-receipt/0.1.0", "file_byte_sha256": {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in files.items()}, "validator_report": write_json(args.out, report)}
    write_json(args.out.with_suffix(".receipt.json"), receipt)
    print(json.dumps({"passed": report.get("passed"), "scoped_pass": report.get("scoped_pass"), "report": str(args.out.resolve())}, ensure_ascii=False))
    return 0 if report.get("passed") is True else 1


def view_command(args):
    from viewer import export_view
    result = export_view(args.atom, args.out, trace_path=args.trace, device_path=args.device, report_path=args.report, run_path=args.strategy_run, strategies_path=args.strategies)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def strategy_compile_command(args):
    api = public_api({"device": ["grouped_device", "validate_device"], "qec": ["build_logical_primitive"], "backend": ["StrategyLibrary"], "validation": ["validate_strategy"], "validation.strategy_observer": ["EnolaCallObserver"]})
    if args.out.exists() and any(args.out.iterdir()):
        raise PipelineError("OUTPUT_NOT_EMPTY: strategy artifacts require a fresh directory")
    args.out.mkdir(parents=True, exist_ok=True)
    device = read_json(args.device) if args.device else api["grouped_device"]()
    if errors := api["validate_device"](device):
        raise PipelineError(f"DEVICE_INVALID: {errors}")
    params = {"state": args.state} if args.operation == "prepare" else {}
    physical = api["build_logical_primitive"](args.operation, params=params)
    root = args.enola_root.resolve()
    if (root / "upstream").is_dir():
        root = root / "upstream"
    library = api["StrategyLibrary"](device, enola_root=root)
    manifest = {"schema_version": "na-strategy-cli/0.1.0", "kb_revision": "kb-0005", "plan_revision": "plan-0007", "interface_version": "IF-STRATEGY-001/0.1.0", "status": "running", "operation": args.operation, "params": params, "enola_root": str(root), "source_byte_sha256": code_identity(), "files": {}, "user_visual_acceptance": "pending"}
    for name, value in (("device", device), ("physical", physical)):
        manifest["files"][name] = write_json(args.out / f"{name}.json", value)
    write_json(args.out / "manifest.json", manifest)
    started = time.perf_counter()
    try:
        observer = api["EnolaCallObserver"](root / "enola/router/router_mis.py")
        with observer:
            strategy = library.get_or_compile(physical)
        manifest["compile_wall_seconds"] = time.perf_counter() - started
        manifest["files"]["strategy"] = write_json(args.out / "strategy.json", strategy)
        evidence = {"pin": read_json(root.parent / "pin.json"), "observation": observer.evidence()}
        manifest["files"]["enola_evidence"] = write_json(args.out / "enola_evidence.json", evidence)
        report = api["validate_strategy"](strategy, device, enola_evidence=evidence)
        manifest["files"]["validation"] = write_json(args.out / "validation.json", report)
        manifest["library_stats"] = library.stats
        manifest["backend_used"] = strategy["body"]["backend_used"]
        manifest["source_snapshot_stable"] = code_identity() == manifest["source_byte_sha256"]
        manifest["status"] = "compiled_and_scoped_validated" if report.get("passed") and manifest["source_snapshot_stable"] else "qualification_failed_or_unverified"
        manifest["t000_qualified"] = False
        write_json(args.out / "manifest.json", manifest)
        print(json.dumps({"status": manifest["status"], "strategy_id": strategy["strategy_id"], "strategy_hash": strategy["strategy_hash"], "backend_used": manifest["backend_used"], "manifest": str((args.out / "manifest.json").resolve()), "t000_qualified": False}, ensure_ascii=False))
        return 0 if manifest["status"] == "compiled_and_scoped_validated" else 1
    except Exception as exc:
        manifest.update(status="incomplete", error=exc.to_dict() if hasattr(exc, "to_dict") else {"type": type(exc).__name__, "message": str(exc)})
        write_json(args.out / "manifest.json", manifest)
        raise


def strategy_validate_command(args):
    function = "validate_strategy_run" if args.run else "validate_strategy"
    api = public_api({"validation": [function]})
    source = args.run or args.strategy
    kwargs = {}
    if args.enola_evidence:
        kwargs["enola_evidence"] = read_json(args.enola_evidence)
    if args.run and args.strategies:
        kwargs["strategies"] = read_json(args.strategies)
    before = code_identity()
    report = api[function](read_json(source), read_json(args.device), **kwargs)
    after = code_identity()
    write_json(args.out, report)
    write_json(args.out.with_suffix(".receipt.json"), {"source_byte_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "device_byte_sha256": hashlib.sha256(args.device.read_bytes()).hexdigest(), "report_byte_sha256": hashlib.sha256(args.out.read_bytes()).hexdigest(), "validation_code_byte_sha256": before, "source_snapshot_stable": before == after})
    print(json.dumps({"passed": report.get("passed"), "scoped_pass": report.get("scoped_pass"), "source_snapshot_stable": before == after, "report": str(args.out.resolve())}, ensure_ascii=False))
    return 0 if report.get("passed") and before == after else 1


class _RecordingStrategyLibrary:
    """Observe public returns; never inspect a backend's private cache."""
    def __init__(self, library, observer_type, source_file, checkpoint_dir=None):
        self.library = library
        self.strategies = {}
        self.observer_type = observer_type
        self.source_file = source_file
        self.observations = {}
        self.lookup_records = []
        self.binding_observations = {}
        self.checkpoint_dir = checkpoint_dir

    @property
    def stats(self):
        return self.library.stats

    def get_or_compile(self, program):
        observer = self.observer_type(self.source_file)
        before = json.loads(json.dumps(self.library.stats))
        with observer:
            value = self.library.get_or_compile(program)
        self.strategies[value["strategy_id"]] = json.loads(json.dumps(value))
        observation = observer.evidence()
        if value["strategy_hash"] not in self.observations or observation["record_count"]:
            self.observations[value["strategy_hash"]] = observation
        if self.checkpoint_dir is not None:
            key = value["strategy_hash"]
            if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
                raise PipelineError("STRATEGY_HASH_FORMAT")
            destination = self.checkpoint_dir / (key + ".json")
            if not destination.exists():
                write_json(destination, value)
                write_json(self.checkpoint_dir / (key + ".observation.json"), observation)
        self.lookup_records.append({"strategy_hash": value["strategy_hash"], "observed_function_returns": observation["record_count"], "library_stats_before": before, "library_stats_after": json.loads(json.dumps(self.library.stats))})
        return value

    def bind(self, strategy, binding):
        observer = self.observer_type(self.source_file)
        try:
            with observer:
                return self.library.bind(strategy, binding)
        finally:
            evidence = observer.evidence()
            previous = self.binding_observations.get(binding["call_id"])
            if previous:
                evidence["record_count"] += previous["record_count"]
                evidence["records"] = previous["records"] + evidence["records"]
                evidence["source_unchanged"] = previous["source_unchanged"] and evidence["source_unchanged"]
                if "project_search_counts" in previous and "project_search_counts" in evidence:
                    for key, value in previous["project_search_counts"].items():
                        evidence["project_search_counts"][key] = evidence["project_search_counts"].get(key, 0) + value
                    evidence["project_sources_unchanged"] = evidence["project_sources_unchanged"] and previous["project_sources_unchanged"] and evidence["project_source_hashes"] == previous["project_source_hashes"]
                else:
                    evidence.pop("project_search_counts", None)
            evidence["binding_attempt_count"] = (previous or {}).get("binding_attempt_count", 0) + 1
            self.binding_observations[binding["call_id"]] = evidence
            if self.checkpoint_dir is not None:
                write_json(self.checkpoint_dir / "bind-progress.json", {"call_id": binding["call_id"], "start_time_us": binding["start_time_us"], "binding_attempt_count": evidence["binding_attempt_count"], "observed_enola_calls": evidence["record_count"], "project_search_counts": evidence.get("project_search_counts"), "execution_status": "binding_only_not_committed"})


def strategy_run_command(args):
    api = public_api({"backend": ["StrategyLibrary"], "runtime": ["LogicalBlockController"], "validation": ["validate_strategy_run"], "validation.strategy_observer": ["EnolaCallObserver"], "device": ["validate_device"]})
    request = read_json(args.request)
    if request.get("schema_version") != "r7-logical-run-request/0.1.0":
        raise PipelineError("STRATEGY_REQUEST_SCHEMA_UNSUPPORTED")
    if args.out.exists() and any(args.out.iterdir()):
        raise PipelineError("OUTPUT_NOT_EMPTY: choose a fresh strategy run directory")
    args.out.mkdir(parents=True, exist_ok=True)
    device = request["device"]
    if errors := api["validate_device"](device):
        raise PipelineError(f"DEVICE_INVALID: {errors}")
    root = args.enola_root.resolve()
    if (root / "upstream").is_dir():
        root = root / "upstream"
    library = _RecordingStrategyLibrary(api["StrategyLibrary"](device, enola_root=root), api["EnolaCallObserver"], root / "enola/router/router_mis.py", args.out / "strategy-checkpoints")
    if args.binding_retry_budget < 1:
        raise PipelineError("BINDING_BUDGET_INVALID")
    fixture = bool(request.get("provenance", {}).get("fixture", False))
    controller = api["LogicalBlockController"](device, request["initial_state"], run_id=request["run_id"], strategy_library=library, binding_retry_budget=args.binding_retry_budget, fixture=fixture)
    manifest = {"schema_version": "na-strategy-run-cli/0.1.0", "kb_revision": "kb-0005", "plan_revision": "plan-0007", "request_byte_sha256": hashlib.sha256(args.request.read_bytes()).hexdigest(), "source_byte_sha256": code_identity(), "status": "running", "files": {}, "stage_wall_seconds": {}, "t000_qualified": False, "user_visual_acceptance": "pending"}
    def save(name, value):
        manifest["files"][name] = write_json(args.out / f"{name}.json", value)
    save("request", request)
    save("device", device)
    manifest["binding_retry_budget"] = args.binding_retry_budget
    manifest["fixture"] = fixture
    queued = []
    execution_committed = False
    try:
        with stage(manifest, args.out, "logical_queue_compile_bind"):
            for block in request["blocks"]:
                controller.register_block(**block)
            if request.get("controller_input") == "encoded_program":
                if "calls" in request:
                    raise PipelineError("AMBIGUOUS_LOGICAL_INPUT: encoded_program mode cannot also specify calls")
                controller.queue_encoded_program(request["encoded_program"])
                save("controller_snapshot", controller.snapshot())
                queued = [{"call_id": cid, "status": "queued_not_committed", "source": "controller.snapshot"} for cid in controller.snapshot()["pending_call_ids"]]
                save("queued_prefix", {"complete": False, "execution_status": "not_committed", "pending_call_ids": controller.snapshot()["pending_call_ids"], "input_mode": "encoded_program"})
            else:
                for call in request["calls"]:
                    manifest["current_call_id"] = call["call_id"]
                    write_json(args.out / "manifest.json", manifest)
                    queued.append(controller.queue_call(**call))
                    save("queued_prefix", {"complete": False, "execution_status": "not_committed", "calls": queued})
                    save("controller_snapshot", controller.snapshot())
            save("queued", queued)
            atom = controller.pending_program()
            save("atom", atom)
            save("strategies", library.strategies)
            evidence = {"pin": read_json(root.parent / "pin.json"), "observations": library.observations, "lookup_records": library.lookup_records, "binding_observations": library.binding_observations}
            save("enola_evidence", evidence)
        with stage(manifest, args.out, "fake_execution"):
            scenario = read_json(args.scenario) if args.scenario else make_explicit_scenario(atom, args.fake_value)
            save("scenario", scenario)
            run = controller.execute_pending(scenario)
            execution_committed = True
            evidence_check(run["event_trace"], "fake_event_run")
            save("run", run)
            save("trace", run["event_trace"])
            save("queued_prefix", {"complete": True, "execution_status": "committed", "calls": run["instances"]})
            save("controller_snapshot", controller.snapshot())
            manifest["library_stats"] = library.stats
        with stage(manifest, args.out, "independent_strategy_run_validation"):
            report = api["validate_strategy_run"](run, device, strategies=library.strategies, enola_evidence=evidence)
            save("validation", report)
        with stage(manifest, args.out, "viewer_output"):
            from viewer import export_view
            view = export_view(args.out / "atom.json", args.out / "viewer.html", trace_path=args.out / "trace.json", device_path=args.out / "device.json", report_path=args.out / "validation.json", run_path=args.out / "run.json", strategies_path=args.out / "strategies.json")
            manifest["files"]["viewer"] = {"path": "viewer.html", "byte_sha256": view["byte_sha256"]}
        manifest["source_snapshot_stable"] = code_identity() == manifest["source_byte_sha256"]
        manifest["status"] = "run_and_scoped_validation_passed" if report.get("passed") and manifest["source_snapshot_stable"] else "qualification_failed_or_unverified"
        manifest["current_stage"] = "done"
        write_json(args.out / "manifest.json", manifest)
        print(json.dumps({"status": manifest["status"], "passed": report.get("passed"), "manifest": str((args.out / "manifest.json").resolve()), "viewer": str((args.out / "viewer.html").resolve()), "t000_qualified": False}, ensure_ascii=False))
        return 0 if manifest["status"] == "run_and_scoped_validation_passed" else 1
    except Exception as exc:
        # Public diagnostics are pending plans, never committed execution.
        save("queued_prefix", {"complete": False, "execution_status": "committed_see_run_and_snapshot" if execution_committed else "not_committed", "calls": queued})
        save("controller_snapshot", controller.snapshot())
        save("strategies", library.strategies)
        save("enola_evidence", {"pin": read_json(root.parent / "pin.json"), "observations": library.observations, "lookup_records": library.lookup_records, "binding_observations": library.binding_observations})
        manifest.update(status="incomplete", error=exc.to_dict() if hasattr(exc, "to_dict") else {"type": type(exc).__name__, "message": str(exc)})
        if hasattr(exc, "details"):
            manifest["error"]["details"] = exc.details
        write_json(args.out / "manifest.json", manifest)
        raise


def dag_inspect_command(args):
    from viewer.bundle import load_bundle
    _, _, receipt = load_bundle(args.bundle)
    write_json(args.out, receipt)
    print(json.dumps({'receipt':str(args.out.resolve()),'status':receipt['status'],'missing_core_roles':receipt['missing_core_roles'],'full_program_passed':False}, ensure_ascii=False))
    return 0


def dag_view_command(args):
    from viewer.hierarchy import export_hierarchy
    result=export_hierarchy(args.bundle,args.out)
    print(json.dumps({'viewer':result['path'],'sha256':result['sha256'],'user_visual_acceptance':'pending'},ensure_ascii=False))
    return 0


def session_view_command(args):
    from viewer.session import export_session_view
    result=export_session_view(args.window,args.trace,args.device,args.out,logical_path=args.logical_dag,schedule_path=args.logical_schedule,report_path=args.report,report_receipt_path=args.report_receipt,archive_root=args.history_root)
    print(json.dumps({k:result[k] for k in ('path','sha256','window_count','action_count','atom_count','full_shor_complete')},ensure_ascii=False))
    return 0


def dag_lower_command(args):
    """Preserve the complete R3 shared library/instance map; no fake execution."""
    from viewer.bundle import load_bundle
    original,values,_=load_bundle(args.bundle)
    api=public_api({'qec':['build_physical_dag_bundle']})
    if args.out.exists() and any(args.out.iterdir()):raise PipelineError('OUTPUT_NOT_EMPTY')
    args.out.mkdir(parents=True,exist_ok=True)
    manifest={'schema_version':'r7-dag-lowering/0.1','kb_revision':'kb-0006','status':'starting','source_byte_sha256':code_identity(),'stage_wall_seconds':{},'files':{},'full_program_passed':False,'runtime_executed':False}
    try:
        with stage(manifest,args.out,'shared_physical_library_and_complete_instance_binding'):
            physical=api['build_physical_dag_bundle'](values['logical_dag'])
            if physical.get('schema_version')!='PhysicalDAGBundle/0.1.0':raise PipelineError('PHYSICAL_BUNDLE_SCHEMA_UNSUPPORTED')
            for role,value in [('physical_dag_bundle',physical),('resource_requirements',physical['resource_requirements'])]:
                manifest['files'][role]=write_json(args.out/(role+'.json'),value)
        copied=[]
        root=Path(args.bundle).resolve().parent
        for item in original['files']:
            target=args.out/'inputs'/Path(item['path']).name;target.parent.mkdir(exist_ok=True)
            if target.exists():raise PipelineError('BUNDLE_COPY_NAME_COLLISION')
            raw=(root/item['path']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=item['byte_sha256']:raise PipelineError('BUNDLE_INPUT_CHANGED_DURING_RUN')
            target.write_bytes(raw);copied.append({**item,'path':target.relative_to(args.out).as_posix()})
        copied += [{'role':role,'path':r['path'],'byte_sha256':r['byte_sha256']} for role,r in manifest['files'].items()]
        write_json(args.out/'bundle.json',{**original,'bundle_id':physical['artifact_id'],'files':copied})
        manifest.update(status='physical_library_bound_execution_pending',current_stage='await_complete_resource_world_and_runtime',source_snapshot_stable=code_identity()==manifest['source_byte_sha256'],coverage=physical['coverage'],resource_counts=physical['resource_requirements']['counts'])
        if not manifest['source_snapshot_stable']:raise PipelineError('SOURCE_CHANGED_DURING_RUN')
        write_json(args.out/'manifest.json',manifest)
        print(json.dumps({'status':manifest['status'],'out':str(args.out),'coverage':{k:v for k,v in manifest['coverage'].items() if k!='static_source_coverage'},'resource_counts':manifest['resource_counts'],'full_program_passed':False},ensure_ascii=False))
        return 0
    except Exception as exc:
        manifest.update(status='incomplete',error=exc.to_dict() if hasattr(exc,'to_dict') else {'type':type(exc).__name__,'message':str(exc)})
        write_json(args.out/'manifest.json',manifest)
        raise


def dag_world_command(args):
    """Bind the complete R3 finite inventory through R4 placement and R5 pool."""
    from viewer.bundle import load_bundle
    original,values,_=load_bundle(args.bundle)
    api=public_api({'backend':['place_resource_requirements'],'runtime':['FiniteResourcePool'],'device':['validate_preinitialized_state']})
    if 'resource_requirements' not in values:raise PipelineError('COMPLETE_RESOURCE_REQUIREMENTS_MISSING')
    if args.out.exists() and any(args.out.iterdir()):raise PipelineError('OUTPUT_NOT_EMPTY')
    args.out.mkdir(parents=True,exist_ok=True)
    manifest={'schema_version':'r7-complete-world/0.1','kb_revision':'kb-0006','status':'starting','source_byte_sha256':code_identity(),'stage_wall_seconds':{},'files':{},'full_program_passed':False,'runtime_executed':False}
    try:
        with stage(manifest,args.out,'complete_resource_world_placement'):
            placement=api['place_resource_requirements'](values['logical_dag'],values['resource_requirements'],values['device'],seed=args.seed,budget=read_json(args.placement_budget),enola_root=args.enola_root)
            state=placement['initial_state'];errors=api['validate_preinitialized_state'](state,values['device'])
            if errors:raise PipelineError('COMPLETE_WORLD_INVALID: '+str(errors))
            pool=api['FiniteResourcePool'](values['resource_requirements'],state).snapshot()
            for role,value in [('patch_placement',placement),('initial_state',state),('resource_pool',pool)]:
                manifest['files'][role]=write_json(args.out/(role+'.json'),value)
        copied=[];root=Path(args.bundle).resolve().parent
        for item in original['files']:
            if item['role'] in manifest['files']:continue
            target=args.out/'inputs'/Path(item['path']).name;target.parent.mkdir(exist_ok=True)
            if target.exists():raise PipelineError('BUNDLE_COPY_NAME_COLLISION')
            raw=(root/item['path']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=item['byte_sha256']:raise PipelineError('BUNDLE_INPUT_CHANGED_DURING_RUN')
            target.write_bytes(raw);copied.append({**item,'path':target.relative_to(args.out).as_posix()})
        copied += [{'role':role,'path':r['path'],'byte_sha256':r['byte_sha256']} for role,r in manifest['files'].items()]
        write_json(args.out/'bundle.json',{**original,'bundle_id':placement['artifact_id']+'-complete-world','files':copied})
        manifest.update(status='complete_inventory_positioned_execution_pending',current_stage='await_qualified_session_factory_execution',source_snapshot_stable=code_identity()==manifest['source_byte_sha256'],resource_counts=state['resource_counts'])
        if not manifest['source_snapshot_stable']:raise PipelineError('SOURCE_CHANGED_DURING_RUN')
        write_json(args.out/'manifest.json',manifest)
        print(json.dumps({'status':manifest['status'],'out':str(args.out),'atoms':len(state['atoms']),'patches':len(placement['placements']),'full_program_passed':False},ensure_ascii=False))
        return 0
    except Exception as exc:
        manifest.update(status='incomplete',error=exc.to_dict() if hasattr(exc,'to_dict') else {'type':type(exc).__name__,'message':str(exc)})
        write_json(args.out/'manifest.json',manifest)
        raise


def dag_prepare_command(args):
    """R2 full graph and real R4 initial placement; no runtime qualification."""
    api = public_api({'frontend':['build_logical_dag','build_patch_dag_example','validate_logical_dag','logical_dag_requirements'],
                      'device':['preinitialized_device','validate_preinitialized_state'],
                      'backend':['place_logical_dag']})
    if args.out.exists() and any(args.out.iterdir()):
        raise PipelineError('OUTPUT_NOT_EMPTY: use a new directory; prior evidence preserved')
    args.out.mkdir(parents=True,exist_ok=True)
    manifest={'schema_version':'r7-dag-preparation/0.1','kb_revision':'kb-0006','entry_mode':'preinitialized','program_scope':args.program,
              'status':'starting','source_byte_sha256':code_identity(),'stage_wall_seconds':{},'files':{},'full_program_passed':False,'runtime_executed':False,'user_visual_acceptance':'pending'}
    def save(name,value):manifest['files'][name]=write_json(args.out/(name+'.json'),value)
    try:
        with stage(manifest,args.out,'logical_frontend'):
            dag=api['build_logical_dag']() if args.program=='shor15' else api['build_patch_dag_example']()
            errors=api['validate_logical_dag'](dag)
            save('logical_dag',dag)
            save('logical_validation',{'errors':errors,'producer_self_check':True,'full_program_passed':False})
            if errors:raise PipelineError('LOGICAL_DAG_INVALID: '+str(errors[:5]))
            save('requirements',api['logical_dag_requirements'](dag))
            if dag.get('source_program') is not None:save('source_program',dag['source_program'])
        with stage(manifest,args.out,'patch_placement'):
            device=api['preinitialized_device']();save('device',device)
            budget=read_json(args.placement_budget)
            save('placement_request',{'schema_version':'r7-r2-r4-placement-adapter/0.2','logical_dag_sha256':canonical_hash(dag),'entry':'na_pipeline.backend.place_logical_dag','seed':args.seed,'budget':budget})
            placement=api['place_logical_dag'](dag,device,seed=args.seed,budget=budget,enola_root=args.enola_root)
            save('patch_placement',placement);save('initial_state',placement['initial_state'])
            errors=api['validate_preinitialized_state'](placement['initial_state'],device)
            if errors:raise PipelineError('INITIAL_STATE_INVALID: '+str(errors))
        roles=['logical_dag','device','patch_placement','initial_state']+(['source_program'] if 'source_program' in manifest['files'] else [])
        bundle={'schema_version':'r7-hierarchical-bundle/0.1','bundle_id':dag['artifact_id']+'-placed','kb_revision':'kb-0006','entry_mode':'preinitialized','fixture':bool(dag.get('provenance',{}).get('fixture',False)),
                'files':[{'role':name,'path':manifest['files'][name]['path'],'byte_sha256':manifest['files'][name]['byte_sha256']} for name in roles]}
        save('bundle',bundle)
        manifest.update(status='frontend_and_placement_complete_runtime_pending',current_stage='await_physical_compiler_and_runtime',source_snapshot_stable=code_identity()==manifest['source_byte_sha256'])
        if not manifest['source_snapshot_stable']:raise PipelineError('SOURCE_CHANGED_DURING_RUN')
        write_json(args.out/'manifest.json',manifest)
        print(json.dumps({'status':manifest['status'],'out':str(args.out),'logical_nodes':len(dag['nodes']),'source_scope':args.program,'patches':len(placement['placements']),'full_program_passed':False},ensure_ascii=False))
        return 0
    except Exception as exc:
        manifest.update(status='incomplete',error=exc.to_dict() if hasattr(exc,'to_dict') else {'type':type(exc).__name__,'message':str(exc)})
        write_json(args.out/'manifest.json',manifest)
        raise


def dag_validate_command(args):
    from viewer.bundle import load_bundle, r6_input
    manifest, values, receipt = load_bundle(args.bundle)
    api = public_api({'validation':['validate_hierarchical_run']})
    products = r6_input(values)
    products['fixture'] = manifest['fixture']
    report = api['validate_hierarchical_run'](products)
    write_json(args.out, report)
    receipt['validation_report'] = {'path':str(args.out.resolve()),'byte_sha256':hashlib.sha256(args.out.read_bytes()).hexdigest()}
    receipt['domain_validation_performed'] = True
    write_json(args.out.with_suffix('.receipt.json'), receipt)
    print(json.dumps({'report':str(args.out.resolve()),'passed':report.get('passed'),'full_program_passed':report.get('full_program_passed',False)}, ensure_ascii=False))
    return 0 if report.get('passed') is True else 1


def main(argv=None):
    if sys.version_info < (3, 12):
        print("Python >=3.12 required; use scripts/na.ps1", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(prog="na-pipeline", description="编译与 fake 场景调度；不模拟量子态")
    parser.add_argument("--version", action="version", version=__version__)
    subs = parser.add_subparsers(dest="command", required=True)
    p=subs.add_parser('session-view',help='R5连续窗口原样显示投影，不生成执行计划')
    p.add_argument('--history-root',type=Path,help='显式重定位全部不可变历史块；逐字节及链校验')
    p.add_argument('--window',type=Path,action='append',required=True)
    p.add_argument('--trace',type=Path,required=True)
    p.add_argument('--device',type=Path,required=True)
    p.add_argument('--logical-dag',type=Path)
    p.add_argument('--logical-schedule',type=Path)
    p.add_argument('--report',type=Path)
    p.add_argument('--report-receipt',type=Path)
    p.add_argument('--out',type=Path,required=True)
    p.set_defaults(func=session_view_command)
    p = subs.add_parser('dag', help='双层DAG同源工件；旧T000资格不继承')
    dag_sub = p.add_subparsers(dest='dag_command', required=True)
    for name, function in [('inspect',dag_inspect_command),('validate',dag_validate_command),('view',dag_view_command),('lower',dag_lower_command)]:
        d = dag_sub.add_parser(name)
        d.add_argument('--bundle',type=Path,required=True)
        d.add_argument('--out',type=Path,required=True)
        d.set_defaults(func=function)
    d=dag_sub.add_parser('prepare',help='完整R2源图与真实R4初始布局；运行/独立资格另计')
    d.add_argument('--program',choices=('shor15','patch-example'),default='shor15')
    d.add_argument('--placement-budget',type=Path,required=True)
    d.add_argument('--seed',type=int,default=0)
    d.add_argument('--enola-root',type=Path,default=Path('third_party/enola/upstream'))
    d.add_argument('--out',type=Path,required=True)
    d.set_defaults(func=dag_prepare_command)
    d=dag_sub.add_parser('world',help='真实R4全资源布局与R5有限池；不产生运行结果')
    d.add_argument('--bundle',type=Path,required=True)
    d.add_argument('--placement-budget',type=Path,required=True)
    d.add_argument('--seed',type=int,default=0)
    d.add_argument('--enola-root',type=Path,default=Path('third_party/enola/upstream'))
    d.add_argument('--out',type=Path,required=True)
    d.set_defaults(func=dag_world_command)
    p = subs.add_parser("slice", help="真实模块两 Surface-17 集成；依赖缺失时报错")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--max-ops", type=int)
    p.add_argument("--resume", action="store_true", help="仅复用字节和代码绑定的编译检查点；重新运行和验证")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--scenario", type=Path)
    group.add_argument("--fake-value", type=int, choices=(0, 1))
    p.set_defaults(func=slice_command)
    p = subs.add_parser("validate", help="调用 R6 独立验证并绑定文件字节哈希")
    p.add_argument("--atom", type=Path, required=True)
    p.add_argument("--device", type=Path, required=True)
    p.add_argument("--trace", type=Path)
    p.add_argument("--physical", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=validate_command)
    p = subs.add_parser("view", help="从同一计划和事件工件输出离线单文件查看器")
    p.add_argument("--atom", type=Path, required=True)
    p.add_argument("--trace", type=Path)
    p.add_argument("--device", type=Path)
    p.add_argument("--report", type=Path)
    p.add_argument("--strategy-run", type=Path)
    p.add_argument("--strategies", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=view_command)
    p = subs.add_parser("strategy", help="Enola 完整逻辑策略：独立编译和资格检查，不冒充 T000 整链")
    strategy_sub = p.add_subparsers(dest="strategy_command", required=True)
    p = strategy_sub.add_parser("compile")
    p.add_argument("--operation", choices=("prepare", "syndrome_round", "logical_cx"), required=True)
    p.add_argument("--state", choices=("0", "+"), default="0")
    p.add_argument("--device", type=Path)
    p.add_argument("--enola-root", type=Path, default=Path("third_party/enola/upstream"))
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=strategy_compile_command)
    p = strategy_sub.add_parser("validate")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--strategy", type=Path)
    group.add_argument("--run", type=Path)
    p.add_argument("--strategies", type=Path)
    p.add_argument("--device", type=Path, required=True)
    p.add_argument("--enola-evidence", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=strategy_validate_command)
    p = strategy_sub.add_parser("run", help="执行显式逻辑请求；真实策略/控制器未就绪则失败")
    p.add_argument("--binding-retry-budget", type=int, default=1024, help="组合尝试上限；依据256次用尽的代表性运行扩大，不改变电路")
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--enola-root", type=Path, default=Path("third_party/enola/upstream"))
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--scenario", type=Path)
    group.add_argument("--fake-value", type=int, choices=(0, 1))
    p.set_defaults(func=strategy_run_command)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OSError, KeyError, TypeError, ImportError) as exc:
        detail = exc.to_dict() if hasattr(exc, "to_dict") else {"code": type(exc).__name__, "message": str(exc)}
        print(json.dumps({"status": "incomplete", "error": detail}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

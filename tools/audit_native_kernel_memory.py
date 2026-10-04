"""Verify saved canonical native-kernel evidence without invoking QMAP.

Usage: python tools/audit_native_kernel_memory.py DIRECTORY --output REVIEW.json
The review output should be outside DIRECTORY so the original manifest remains
an exact inventory. Hashes provide reproducible provenance, not authenticity.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from neutral_atom_kernel import DeclaredReportSource, GateSpec, KernelExecutor, Operation
from neutral_atom_kernel.audit import audit_operations
from neutral_atom_kernel.model import thaw
from neutral_atom_experiments.qec_pbc.canonical import canonical_memory_program
from neutral_atom_strategies.native_kernel.axes import finalize_operations
from neutral_atom_strategies.native_kernel.lowering import lower_native


BASE_ARTIFACTS = {
    "initial.json", "operations.json", "blocks.json", "journal.json",
    "checkpoint.json", "inflight-checkpoint.json", "offline-audit.json",
    "summary.json", "recording.json", "replay.html",
}
CORE_SOURCES = {
    "examples/run_native_kernel_memory.py",
    "src/neutral_atom_experiments/qec_pbc/native_kernel_memory.py",
    "src/neutral_atom_experiments/qec_pbc/canonical.py",
    "src/neutral_atom_experiments/qec_pbc/ir.py",
    "src/neutral_atom_experiments/qec_pbc/surface.py",
    "src/neutral_atom_app/native_kernel_view.py",
    "src/neutral_atom_env/visualization/viewer.py",
    "src/neutral_atom_env/visualization/viewer.js",
    "src/neutral_atom_env/visualization/viewer-shell.html",
    "src/neutral_atom_env/visualization/summary.py",
    "src/neutral_atom_env/visualization/theme.py",
}


class ReviewFailure(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def require(condition, code, message):
    if not condition:
        raise ReviewFailure(code, message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def operation_payload(op):
    return {"id": op.id, "kind": op.kind, "atoms": list(op.atoms), "duration_us": op.duration_us,
            "positions": [[q, list(point)] for q, point in op.positions], "gate_ids": list(op.gate_ids),
            "report_ids": list(op.report_ids), "aod_id": op.aod_id, "metadata": thaw(op.metadata)}


def source_protocol(rounds):
    """Build the normative role/wire/dependency mapping independently of runner."""
    require(type(rounds) is int and rounds >= 1, "SOURCE_PROTOCOL", "Round count must be a positive integer")
    protocol = canonical_memory_program(basis="Z", rounds=rounds)
    bindings = {role.id: f"Q{index:03d}" for index, role in enumerate(protocol.program.roles)}
    previous, gates = {}, []
    for task in protocol.program.operations:
        atoms = tuple(bindings[role] for role in task.targets)
        dependencies = tuple(dict.fromkeys((*(f"{parent}__g000" for parent in task.depends_on),
                                             *(previous[q] for q in atoms if q in previous))))
        gates.append(GateSpec(f"{task.id}__g000", task.gate_type, atoms, dependencies))
        previous.update({q: gates[-1].id for q in atoms})
    segments, pending = [], []
    for gate in gates:
        if gate.kind in {"H", "X", "Y", "Z", "T", "CZ"}:
            pending.append(gate)
        elif pending:
            segments.append(tuple(pending)); pending = []
    if pending:
        segments.append(tuple(pending))
    return protocol, bindings, tuple(gates), tuple(segments)


def _safe_file(base, relative):
    require(isinstance(relative, str) and relative and "\\" not in relative,
            "MANIFEST_PATH", "Manifest keys must use nonempty repository-relative POSIX paths")
    path = (base / relative).resolve()
    require(path.is_relative_to(base.resolve()) and path.is_file(), "MANIFEST_PATH", f"Missing or escaping manifest file: {relative}")
    return path


def _check_manifest(directory, manifest, root):
    require(manifest.get("schema") == "native-kernel-evidence-manifest/1", "MANIFEST_SCHEMA", "Missing/unsupported evidence manifest")
    sources, artifacts = manifest.get("source_sha256"), manifest.get("artifact_sha256")
    require(isinstance(sources, dict) and sources and isinstance(artifacts, dict) and artifacts,
            "MANIFEST_NONEMPTY", "Both source_sha256 and artifact_sha256 must be nonempty mappings")
    required_sources = set(CORE_SOURCES)
    for package in ("neutral_atom_kernel", "neutral_atom_strategies/native_kernel"):
        required_sources.update(path.relative_to(root).as_posix() for path in (root / "src" / package).glob("*.py"))
    require(required_sources <= sources.keys(), "MANIFEST_SOURCE_COVERAGE", f"Required source hashes are missing: {sorted(required_sources - sources.keys())}")
    require(BASE_ARTIFACTS <= artifacts.keys(), "MANIFEST_ARTIFACT_COVERAGE", f"Required artifacts are missing: {sorted(BASE_ARTIFACTS - artifacts.keys())}")
    actual = {path.name for path in directory.iterdir() if path.is_file() and path.name != "manifest.json"}
    require(set(artifacts) == actual, "MANIFEST_ARTIFACT_COVERAGE", "Artifact manifest must cover every saved evidence file, with no omitted or nonexistent entry")
    for base, values in ((root, sources), (directory, artifacts)):
        for name, digest in values.items():
            require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
                    "MANIFEST_HASH", f"Invalid SHA256 for {name}")
            require(sha256(_safe_file(base, name).read_bytes()).hexdigest() == digest,
                    "MANIFEST_HASH", f"SHA256 mismatch for {name}")
    return {"sources": len(sources), "artifacts": len(artifacts)}


def audit_directory(directory, *, root=ROOT):
    """Read, reconstruct, and replay the saved evidence; never call a compiler."""
    directory, root = Path(directory).resolve(), Path(root).resolve()
    report = {"schema": "native-kernel-memory-independent-review/1", "directory": str(directory),
              "status": "FAIL", "checks": {}, "failures": [],
              "native_compilation_calls": 0, "legacy_environment_execution_calls": 0,
              "scope": "Canonical scheduling source, native provenance, independent geometry and exact kernel replay; no quantum quality or factory qualification"}
    checks = report["checks"]
    load = lambda name: json.loads((directory / name).read_text(encoding="utf-8"))
    try:
        manifest = load("manifest.json")
        checks["manifest"] = _check_manifest(directory, manifest, root)
        initial, summary = load("initial.json"), load("summary.json")
        protocol, bindings, gates, segments = source_protocol(summary["rounds"])
        expected_gates = [{"id": g.id, "kind": g.kind, "atoms": list(g.atoms), "depends_on": list(g.depends_on)} for g in gates]
        require(initial["gates"] == expected_gates, "SOURCE_GATE_CONTRACT", "Saved GateSpecs differ from independent canonical role/wire/dependency mapping")
        expected_initial = {q: [10 * index, 0] for index, q in enumerate(bindings.values())}
        require(initial["positions"] == expected_initial, "SOURCE_INITIAL_PLACEMENT", "Initial positions differ from the declared t=0 canonical SZ10 profile")
        required_native = {f"unitary-{i}{suffix}" for i in range(1, len(segments) + 1) for suffix in (".native.json", ".naviz")}
        require(required_native <= manifest["artifact_sha256"].keys(), "MANIFEST_NATIVE_COVERAGE", "Native evidence is missing a complete canonical unitary segment")
        observed_native = {p.name for p in directory.glob("unitary-*.native.json")}
        require(observed_native == {f"unitary-{i}.native.json" for i in range(1, len(segments) + 1)},
                "NATIVE_SEGMENT_COVERAGE", "Saved native outputs do not exactly cover canonical unitary segments")
        checks["canonical_source"] = {"gates": len(gates), "atoms": len(bindings), "unitary_segments": len(segments), "rounds": summary["rounds"]}

        operations = tuple(Operation(**value) for value in load("operations.json"))
        by_op = {op.id: op for op in operations}
        require(len(by_op) == len(operations), "OPERATION_IDENTITY", "Saved operations contain duplicate IDs")
        effects = Counter(g for op in operations for g in op.gate_ids)
        require(set(effects) == {g.id for g in gates} and all(n == 1 for n in effects.values()),
                "SOURCE_EFFECT_COVERAGE", "Each canonical source gate must execute exactly once, without extra effects")
        geometry = audit_operations(initial["positions"], operations, initial["profile"], gates=gates,
                                    initial_axes=initial["profile"]["initial_axes"])
        require(geometry["passed"], "PHYSICAL_REVIEW", f"Independent geometry review failed: {geometry['failures']}")
        saved_geometry = load("offline-audit.json")
        require(saved_geometry == geometry, "PHYSICAL_REVIEW_BINDING", "Saved physical review differs from independent replay of the saved operation stream")
        checks["physical_review"] = {"status": geometry["status"], "operations": len(operations), "geometry_contract": geometry["geometry_contract"]["name"]}

        journal, blocks = load("journal.json"), load("blocks.json")
        final_saved, cut_saved = load("checkpoint.json"), load("inflight-checkpoint.json")
        require(isinstance(journal, list) and journal and isinstance(blocks, list) and blocks,
                "JOURNAL_NONEMPTY", "Saved blocks and committed journal must be nonempty")
        KernelExecutor.restore(final_saved)
        KernelExecutor.restore(cut_saved)
        starts, groups, completed, reports, report_times, report_bindings = {}, defaultdict(list), [], {}, {}, {}
        cursor, previous_time = 0, 0.0
        for index, entry in enumerate(journal):
            require(entry["version"] == index + 1 and entry["time_us"] >= previous_time, "JOURNAL_ORDER", "Journal versions/time are not a complete monotonic prefix")
            previous_time = entry["time_us"]
            event = entry["event"]
            if event == "BLOCK_STARTED":
                require(entry["block_id"] not in starts, "BLOCK_IDENTITY", "A block starts more than once")
                starts[entry["block_id"]] = entry
            elif event == "OPERATION_STARTED":
                oid = entry["operation_id"]
                require(oid in by_op, "JOURNAL_OPERATION", "Journal names an unknown operation")
                groups[entry["block_id"]].append(by_op[oid])
            elif event == "OPERATION_COMPLETED":
                oid = entry["operation_id"]
                require(oid in by_op and oid not in completed, "JOURNAL_OPERATION", "Operation completion is unknown or duplicated")
                completed.append(oid)
                values = dict(entry.get("reports", ()))
                if by_op[oid].kind == "MEASURE":
                    op = by_op[oid]
                    ids = op.report_ids or op.gate_ids
                    require(set(values) == set(ids) and not reports.keys() & values.keys(), "REPORT_COMPLETION", "Measurement reports are missing, extra or duplicated")
                    require(entry["report_source_cursor_before"] == cursor and entry["report_source_cursor_after"] == cursor + len(ids),
                            "REPORT_CURSOR", "Report source cursor does not advance exactly at each readout completion")
                    for rid, gid, atom in zip(ids, op.gate_ids, op.atoms):
                        reports[rid], report_times[rid] = values[rid], entry["time_us"]
                        report_bindings[rid] = {"gate_id": gid, "atom": atom, "operation_id": oid}
                    cursor += len(ids)
                else:
                    require(not values, "REPORT_COMPLETION", "A report commits outside measurement completion")
            else:
                require(not entry.get("reports"), "REPORT_COMPLETION", "A report is visible before measurement completion")
        require(completed == [o.id for o in operations], "JOURNAL_OPERATION", "Journal completion sequence differs from the saved operation stream")
        expected_reports = sum(g.kind == "MEASURE" for g in gates)
        require(len(reports) == expected_reports and reports == final_saved["measurement_results"]
                and report_times == final_saved["measurement_completion_times_us"]
                and report_bindings == final_saved["report_bindings"] and cursor == final_saved["report_source"]["cursor"],
                "REPORT_FINAL_STATE", "Reports, completion times, bindings or source cursor differ from final checkpoint")
        require([b["id"] for b in blocks] == list(starts), "BLOCK_IDENTITY", "Saved block order differs from journal block starts")
        checks["reports"] = {"count": len(reports), "cursor": cursor, "completion_only": True}

        source = DeclaredReportSource.restore(initial["report_source"])
        executor = KernelExecutor(initial["positions"], gates, initial_aod_axes=initial["profile"]["initial_axes"], report_source=source, recording=True)
        native_count, cut_match = 0, False
        alignment_operations, alignment_time = 0, 0.0
        for saved_block in blocks:
            bid = saved_block["id"]
            block_operations = tuple(groups[bid])
            require(bool(block_operations), "BLOCK_OPERATIONS", f"Saved block {bid} has no operation trace")
            before = executor.observe()
            if re.fullmatch(r"unitary-\d+", bid):
                number = int(bid.split("-")[1]); authoritative = segments[number - 1]
                native = load(bid + ".native.json")
                require(native["architecture"] == initial["profile"]["architecture"], "NATIVE_ARCHITECTURE", "Native architecture differs from declared physical profile")
                require(native["code"] == (directory / (bid + ".naviz")).read_text(encoding="utf-8"), "NATIVE_CODE", "Native JSON and source NAViz differ")
                require(native["compiler_source_sha256"] == manifest["source_sha256"]["src/neutral_atom_strategies/native_kernel/compiler.py"],
                        "NATIVE_SOURCE_SHA", "Native source SHA differs from evidence source manifest")
                require(native["completed_dependencies"] == list(before.completed_gate_ids), "NATIVE_LIVE_DEPENDENCIES", "Native request dependency prefix differs from real committed state")
                boundaries = {phase.native_gate_ids[0] for phase in protocol.phases if phase.native_gate_ids and phase.native_gate_ids[0] in {g.id for g in authoritative}}
                boundaries.discard(authoritative[0].id)
                require(native["barrier_before"] == sorted(boundaries), "NATIVE_PROTOCOL_FRONTIERS", "Native request barriers differ from canonical protected boundaries")
                lowered = lower_native(native, authoritative, initial_positions=before.positions,
                                       completed_dependencies=before.completed_gate_ids)
                require(thaw(lowered.provenance) == saved_block["native_provenance"], "NATIVE_PROVENANCE", "Saved native block provenance differs from validated original source")
                expected_ops = finalize_operations(lowered.operations, before.positions, initial_axes=before.aod_axes,
                                                   initial_holders=before.holders, bounds=initial["profile"]["bounds_um"], minimum_axis_spacing_um=2)
                require([operation_payload(o) for o in expected_ops] == [operation_payload(o) for o in block_operations],
                        "NATIVE_LOWERING_BINDING", "Saved native physical operations differ from deterministic source lowering/full-axis finalization")
                native_count += 1
            elif bid.endswith(".align"):
                alignment_operations += len(block_operations)
                alignment_time += sum(o.duration_us for o in block_operations)
            block = executor.bind_block(bid, block_operations, native_provenance=saved_block["native_provenance"])
            require(block.expected_version == saved_block["expected_version"] and block.starting_state_hash == saved_block["starting_state_hash"],
                    "LIVE_STATE_BINDING", f"Block {bid} does not bind the independently replayed live state")
            require(starts[bid]["native_provenance"] == saved_block["native_provenance"], "BLOCK_PROVENANCE", "Journal block provenance differs from saved block")
            # Runtime operation hashes deliberately use ASCII JSON, unlike native request hashing.
            operation_hash = sha256(json.dumps([operation_payload(o) for o in block_operations], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
            require(operation_hash == starts[bid]["operations_hash"], "BLOCK_OPERATIONS_HASH", "Saved operation hash differs from actual saved block operations")
            if bid == cut_saved["active_block"]["id"]:
                executor.run(block, until_us=cut_saved["time_us"])
                require(executor.checkpoint(include_journal=True) == cut_saved, "MIDCUT_REPLAY", "Saved in-flight checkpoint is not reproduced exactly")
                probe = summary["inflight_recovery"]
                require(probe["passed"] and probe["report_not_ready"] and probe["cut_us"] == cut_saved["time_us"]
                        and probe["measurement_id"] not in cut_saved["measurement_results"]
                        and cut_saved["running"][0] < cut_saved["time_us"] < cut_saved["running"][1],
                        "MIDCUT_REPORT", "Recovery probe is not genuinely inside an unfinished readout")
                executor = KernelExecutor.restore(executor.checkpoint(include_journal=True)); executor.run(); cut_match = True
            else:
                executor.run(block)
        require(native_count == len(segments) and cut_match, "REPLAY_COVERAGE", "Native segments or measurement recovery cut were not independently replayed")
        require(executor.checkpoint(include_journal=True) == final_saved, "FINAL_REPLAY", "Final saved checkpoint is not reproduced exactly")
        require(thaw(executor.journal) == journal and final_saved["journal"] == journal, "JOURNAL_REPLAY", "Saved committed journal is not reproduced exactly")
        require(executor.observe().completed and not executor.observe().pending_events, "FINAL_COMPLETION", "Final runtime is incomplete or still has events")
        require(summary["runtime_status"] == "completed" and summary["offline_physical_status"] == "PASS"
                and summary["gates"] == len(gates) and summary["operations"] == len(operations)
                and summary["reports"] == len(reports) and summary["journal_events"] == len(journal)
                and summary["physical_time_us"] == executor.observe().time_us
                and summary["inflight_recovery"]["report_completion_us"] == report_times[summary["inflight_recovery"]["measurement_id"]],
                "SUMMARY_BINDING", "Summary counters/time/recovery receipt differ from independently replayed evidence")
        checks["exact_replay"] = {"blocks": len(blocks), "native_segments": native_count,
                                  "midcut_checkpoint": True, "final_checkpoint": True, "journal": len(journal),
                                  "physical_time_us": executor.observe().time_us,
                                  "alignment_operations": alignment_operations, "alignment_time_us": alignment_time}
        report["status"] = "PASS"
    except ReviewFailure as error:
        report["failures"].append({"code": error.code, "reason": str(error)})
    except (OSError, KeyError, TypeError, ValueError, IndexError, AttributeError) as error:
        report["failures"].append({"code": "INVALID_EVIDENCE", "reason": f"{type(error).__name__}: {error}"})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.resolve().is_relative_to(args.directory.resolve()), "REVIEW_OUTPUT_PATH", "Write the independent review outside the original evidence directory")
    result = audit_directory(args.directory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

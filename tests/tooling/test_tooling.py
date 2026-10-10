from __future__ import annotations
from copy import deepcopy
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from na_pipeline import cli
from scripts.make_viewer_fixture import fixture
from viewer import check_model, export_view


class ToolingTests(unittest.TestCase):
    def test_json_byte_and_content_hashes_are_distinct_and_exact(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "x.json"
            obj = {"中文": [1, 2], "a": "line\nline"}
            receipt = cli.write_json(path, obj)
            self.assertEqual(receipt["byte_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertNotIn(b"\r\n", path.read_bytes())
            self.assertEqual(cli.read_json(path), obj)
            self.assertNotEqual(receipt["byte_sha256"], receipt["canonical_sha256"])

    def test_missing_upstream_is_explicit_not_substituted(self):
        missing = ModuleNotFoundError("absent", name="na_pipeline.qec")
        with patch.object(cli.importlib, "import_module", side_effect=missing):
            with self.assertRaisesRegex(cli.PipelineError, "UPSTREAM_NOT_READY"):
                cli.public_api({"qec": ["build_two_block_slice"]})

    def test_internal_import_gap_is_distinguished(self):
        missing = ModuleNotFoundError("dependency missing", name="na_pipeline.runtime.state")
        with patch.object(cli.importlib, "import_module", side_effect=missing):
            with self.assertRaisesRegex(cli.PipelineError, "DEPENDENCY_IMPORT_FAILED"):
                cli.public_api({"runtime": ["run"]})

    def test_fixture_render_and_script_escape(self):
        atom, trace = fixture()
        atom["artifact_id"] = '</script><script>alert("unsafe")</script>'
        trace["atom_program_ref"] = atom["artifact_id"]
        trace["input_hashes"]["atom_program"] = cli.canonical_hash(atom)
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            cli.write_json(folder / "atom.json", atom)
            cli.write_json(folder / "trace.json", trace)
            result = export_view(folder / "atom.json", folder / "view.html", trace_path=folder / "trace.json")
            self.assertTrue(result["fixture"])
            html = (folder / "view.html").read_text(encoding="utf-8")
            self.assertNotIn('</script><script>alert', html)
            self.assertIn('\\u003c/script\\u003e', html)
            self.assertEqual(result["inputs"]["atom_program"]["byte_sha256"], hashlib.sha256((folder / "atom.json").read_bytes()).hexdigest())

    def test_unknown_interpolation_is_rejected(self):
        atom, _ = fixture()
        atom["actions"][1]["payload"]["interpolation"] = "magic_teleport"
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_INTERPOLATION"):
            check_model(atom)

    def test_missing_shared_motion_and_zero_time_rejected(self):
        for variant in ("coverage", "duration"):
            atom, _ = fixture()
            move = atom["actions"][1]
            if variant == "coverage":
                move["atoms"].append("a1")
            else:
                move["t_end_us"] = move["t_start_us"]
            with self.assertRaisesRegex(ValueError, "TRAJECTORY_COVERAGE|ZERO_TIME_MOVE"):
                check_model(atom)

    def test_wrong_trace_timing_and_hardware_claim_rejected(self):
        atom, trace = fixture()
        trace["events"][0]["t_end_us"] += 1
        with self.assertRaisesRegex(ValueError, "EVENT_PLAN_MISMATCH"):
            check_model(atom, trace)
        atom, trace = fixture()
        trace["hardware_executed"] = True
        with self.assertRaisesRegex(ValueError, "EVIDENCE_LABEL"):
            check_model(atom, trace)

    def test_hash_mismatch_does_not_produce_view(self):
        atom, trace = fixture()
        trace["input_hashes"]["atom_program"] = "0" * 64
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            cli.write_json(folder / "a.json", atom)
            cli.write_json(folder / "t.json", trace)
            with self.assertRaisesRegex(ValueError, "INPUT_HASH_MISMATCH"):
                export_view(folder / "a.json", folder / "view.html", trace_path=folder / "t.json")
            self.assertFalse((folder / "view.html").exists())

    def test_resume_reuses_compile_only_not_runtime_or_validation(self):
        atom, trace = fixture()
        counts = {"compile": 0, "runtime": 0, "validate": 0}
        def compile_fn(*args, **kwargs):
            counts["compile"] += 1
            return deepcopy(atom)
        def run(*args):
            counts["runtime"] += 1
            return deepcopy(trace)
        def validate(*args, **kwargs):
            counts["validate"] += 1
            return {"passed": True, "checks": [], "failures": [], "unverified": [], "provenance": {"fixture": True}}
        api = {"default_device": lambda: {"artifact_id": "fixture-device"}, "validate_device": lambda _: [], "build_two_block_slice": lambda **_: {"body": []}, "compile_physical": compile_fn, "run": run, "validate": validate}
        with tempfile.TemporaryDirectory() as temp, patch.object(cli, "public_api", return_value=api), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["slice", "--out", temp, "--fake-value", "0"]), 0)
            self.assertEqual(cli.main(["slice", "--out", temp, "--fake-value", "1", "--resume"]), 0)
            self.assertEqual(counts, {"compile": 1, "runtime": 2, "validate": 2})
            manifest = cli.read_json(Path(temp) / "manifest.json")
            self.assertTrue(manifest["compile_checkpoint_reused"])
            self.assertEqual(manifest["user_visual_acceptance"], "pending")
            archived = list((Path(temp) / "attempts").glob("*/trace.json"))
            self.assertEqual(len(archived), 1)
            self.assertEqual(cli.read_json(archived[0]), trace)

    def test_background_job_logs_and_budget_exhaustion(self):
        with tempfile.TemporaryDirectory() as temp:
            for mode in ("complete", "budget", "memory"):
                job = Path(temp) / mode
                code = "print('durable-log', flush=True)" if mode == "complete" else "import time; print('started', flush=True); time.sleep(30)"
                if mode == "memory":
                    code = "import time; data=bytearray(128*1024*1024); print('allocated',flush=True); time.sleep(30)"
                args = [sys.executable, str(ROOT / "scripts/jobs.py"), "launch", "--job-dir", str(job), "--wall-seconds", "0.7" if mode == "budget" else "5", "--memory-gib", "0.08" if mode == "memory" else "1", "--parallelism", "1", "--search-expansions", "10", "--", sys.executable, "-c", code]
                result = subprocess.run(args, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    state = cli.read_json(job / "status.json")
                    if state["status"] in {"completed", "budget_exhausted_incomplete", "supervisor_failed_incomplete"}:
                        break
                    time.sleep(0.1)
                self.assertEqual(state["status"], "completed" if mode == "complete" else "budget_exhausted_incomplete", state)
                self.assertTrue((job / "stdout.log").read_bytes())
                self.assertGreaterEqual(state["elapsed_seconds"], 0)
                if mode == "memory":
                    self.assertEqual(state["budget_reason"], "tree_rss_bytes")
                    self.assertGreater(state["peak_tree_rss_bytes"], 80 * 1024**2)


if __name__ == "__main__":
    unittest.main()

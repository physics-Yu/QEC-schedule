from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import io
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from scripts import enola_environment as env
from scripts.make_viewer_fixture import fixture
from viewer import check_model, group_projection, transfer_bindings
from scripts.make_strategy_request import request_for, encoded_request_for
from na_pipeline.cli import _RecordingStrategyLibrary, main, write_json, read_json


class StrategyToolingTests(unittest.TestCase):
    def test_source_pin_actual_dependencies_and_import_path(self):
        report = env.verify()
        self.assertTrue(report["source_and_import_verified"])
        self.assertFalse(report["integration_qualified"])
        self.assertEqual(report["commit"], env.COMMIT)
        self.assertEqual(report["dependencies"], env.DEPS)

    def test_encoded_call_bijection_preserves_original_source_and_dependencies(self):
        request = request_for("coupled")
        from na_pipeline.frontend import iter_encoded_calls
        originals = list(iter_encoded_calls(request["encoded_program"]))
        mapping = request["encoded_call_bindings"]
        self.assertEqual(len(mapping), len(set(mapping.values())))
        for original, adapted in zip(originals, request["calls"], strict=True):
            self.assertEqual(adapted["call_id"], mapping[original["id"]])
            self.assertEqual(adapted["after"], [mapping[x] for x in original["after"]])
            self.assertIn(original["id"], adapted["source_ids"])
            self.assertEqual(adapted["operands"], original["operands"])
        self.assertEqual(len(request["initial_state"]["atoms"]), 34)
        self.assertEqual(request["blocks"][1]["offset_um"], [100.0, 0.0])
        self.assertEqual(next(a["position_um"] for a in request["initial_state"]["atoms"] if a["qubit_id"] == "L1/d0"), [100.0, -100.0])

    def test_native_encoded_mode_rejects_competing_explicit_calls(self):
        request = encoded_request_for("single")
        self.assertNotIn("calls", request)
        request["provenance"]["fixture"] = True
        request["calls"] = []
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            write_json(folder / "request.json", request)
            stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                code = main(["strategy", "run", "--request", str(folder / "request.json"), "--out", str(folder / "run"), "--fake-value", "0"])
            self.assertEqual(code, 2)
            self.assertIn("AMBIGUOUS_LOGICAL_INPUT", stderr.getvalue())
            manifest = read_json(folder / "run/manifest.json")
            self.assertEqual(manifest["status"], "incomplete")
            self.assertTrue(manifest["fixture"])
            self.assertFalse((folder / "run/trace.json").exists())

    def test_tampered_vendor_bytes_rejected_without_touching_live_vendor(self):
        entries = env.source_files()
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for name in entries:
                dest = folder / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(env.SOURCE / name, dest)
            path = folder / "enola/router/router_mis.py"
            path.write_bytes(path.read_bytes() + b"\n# tamper\n")
            with patch.object(env, "SOURCE", folder), patch.object(env, "git", side_effect=AssertionError('export must not invoke git')):
                with self.assertRaisesRegex(ValueError, "ENOLA_SOURCE_CHANGED"):
                    env.source_files()

    def test_frozen_export_checks_original_pin_without_git(self):
        expected=env.source_files()
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            for name in expected:
                dest=folder/name;dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(env.SOURCE/name,dest)
            with patch.object(env,'SOURCE',folder),patch.object(env,'git',side_effect=AssertionError('no git')):
                self.assertEqual(env.source_files(),expected)
                (folder/'enola/extra.py').write_bytes(b'# unexpected')
                with self.assertRaisesRegex(ValueError,'ENOLA_EXTRA_SOURCE'):env.source_files()

    def test_atomic_group_transfer_bindings_cover_all_atoms(self):
        atom, _ = fixture()
        a = atom["actions"][0]
        a["atoms"] = ["a0", "a1"]
        old = deepcopy(a["payload"])
        a["payload"] = {"aod_group": "data", "group_id": "g0", "purpose": "patch_initialization_transport", "bindings": [{"atom_id": "a0", **old}, {"atom_id": "a1", **old, "from_trap_id": "s/a1", "to_trap_id": "aod/data/1", "column_id": "c1", "position_um": [10, 0]}]}
        self.assertEqual(len(transfer_bindings(a)), 2)
        check_model(atom)
        a["payload"]["bindings"][1]["atom_id"] = "a0"
        with self.assertRaisesRegex(ValueError, "TRANSFER_BINDING_COVERAGE"):
            check_model(atom)

    def test_group_metrics_preserve_declared_timing_and_missing_reasons(self):
        atom, _ = fixture()
        m1 = atom["actions"][4]
        m1["payload"].update(group_id="readout", purpose="maintenance_readout")
        m2 = deepcopy(m1)
        m2.update(id="second-measure", atoms=["a1"], t_start_us=m1["t_start_us"] + 2, t_end_us=m1["t_end_us"] + 3)
        m2["payload"].update(result_id="m1", result_ready_us=54)
        atom["actions"].append(m2)
        g = group_projection(atom)[0]
        self.assertEqual(g["readout_start_span_us"], 2)
        self.assertEqual(g["readout_end_span_us"], 3)
        self.assertEqual(g["result_ready_span_us"], 5)
        self.assertEqual(g["split_reasons"], [])
        self.assertEqual(g["measurements"][0]["t_start_us"], m1["t_start_us"])

    def test_shared_cz_preserves_pair_sources_and_direction(self):
        atom, _ = fixture()
        atom["initial_state"]["atoms"].append({"atom_id": "a3", "qubit_id": "q/a3", "position_um": [30, 20], "carrier": "SLM", "trap_id": "s/a3", "aod_group": "magic", "row_id": None, "column_id": None})
        action = atom["actions"][2]
        action["atoms"] = ["a0", "a1", "a2", "a3"]
        pairs = [["a0", "a1"], ["a2", "a3"]]
        action["source_ids"] += ["physical0", "physical1"]
        action["payload"].update(pairs=pairs, physical_op_ids=["physical0", "physical1"], source_op_records={f"physical{i}": {"qubits": ["q/"+x for x in pair], "params": {"name": "CX"}, "reads": [], "writes": [], "condition": None} for i, pair in enumerate(pairs)}, pair_sources=[{"physical_op_id": f"physical{i}", "qubits": ["q/"+x for x in pair], "atoms": pair} for i, pair in enumerate(pairs)])
        check_model(atom)
        action["payload"]["pair_sources"][0]["qubits"].reverse()
        with self.assertRaisesRegex(ValueError, "PAIR_SOURCE_IDENTITY"):
            check_model(atom)

    def test_failed_binding_search_observation_cannot_be_erased_by_retry(self):
        class Observer:
            count = 0
            def __init__(self, *args):
                self.index = Observer.count
                Observer.count += 1
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def evidence(self):
                return {"record_count": 1 if self.index == 0 else 0, "records": [], "source_unchanged": True, "project_search_counts": {"compile": 1 if self.index == 0 else 0}, "project_source_hashes": {"file": "hash"}, "project_sources_unchanged": True}
        class Library:
            count = 0
            def bind(self, *args):
                self.count += 1
                if self.count == 1: raise ValueError("conflict")
                return {"fixture": True}
        wrapped = _RecordingStrategyLibrary(Library(), Observer, Path("fixture"))
        with self.assertRaisesRegex(ValueError, "conflict"):
            wrapped.bind({}, {"call_id": "call0"})
        wrapped.bind({}, {"call_id": "call0"})
        evidence = wrapped.binding_observations["call0"]
        self.assertEqual(evidence["record_count"], 1)
        self.assertEqual(evidence["project_search_counts"]["compile"], 1)
        self.assertEqual(evidence["binding_attempt_count"], 2)


if __name__ == "__main__":
    unittest.main()

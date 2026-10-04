import ast
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from neutral_atom_app.native_kernel_view import build_native_kernel_payload, export_native_kernel_view
from neutral_atom_kernel import DeclaredReportSource, GateSpec, KernelExecutor, Operation
from neutral_atom_kernel.model import thaw


def evidence():
    initial = {"Q0": (0, 0), "Q1": (10, 0)}
    axes = {"rows": (-10,), "columns": (-10, 0)}
    profile = {"id": "viewer-contract", "bounds_um": (-20, -30, 50, 160), "slm_grid_um": 5,
               "initial_axes": {"AOD_0": axes}, "measurement_zone_um": (0, 130, 50, 160),
               "cz_zone_um": (-10, 50, 40, 80)}
    gates = (GateSpec("h", "H", ("Q1",)), GateSpec("m", "MEASURE", ("Q0",), ("h",)),
             GateSpec("reset", "RESET", ("Q0",), ("m",)))
    source = DeclaredReportSource(source_id="viewer-trajectory", version="v1", bits=(1,))
    ops = (
        Operation("configure", "CONFIGURE", duration_us=5, metadata={"source_axes": axes, "target_axes": {"rows": (0,), "columns": (0, 10)}}),
        Operation("h", "GATE", ("Q1",), 1, gate_ids=("h",)),
        Operation("load", "LOAD", ("Q0",), 2),
        Operation("move", "MOVE", ("Q0",), 3, (("Q0", (0, 130)),), metadata={"target_axes": {"rows": (130,), "columns": (0, 10)}}),
        Operation("store", "STORE", ("Q0",), 2),
        Operation("read", "MEASURE", ("Q0",), 4, gate_ids=("m",), report_ids=("r.m",)),
        Operation("reset", "RESET", ("Q0",), 2, gate_ids=("reset",)),
        Operation("wait", "WAIT", duration_us=1),
    )
    kernel = KernelExecutor(initial, gates, initial_aod_axes={"AOD_0": axes}, report_source=source)
    observation = kernel.run(kernel.bind_block("viewer", ops))
    final = {key: thaw(getattr(observation, key)) for key in ("time_us", "positions", "holders", "completed_gate_ids",
             "measurement_results", "measurement_completion_times_us", "aod_axes")}
    return {"initial": initial, "profile": profile, "gates": gates, "operations": ops,
            "journal": thaw(kernel.journal), "role_to_atom": {"A.D0": "Q0", "A.X0": "Q1"},
            "report_source": source.checkpoint(), "final": final}


def test_export_replays_deltas_reports_effects_axes_and_shared_presentation(tmp_path):
    saved = evidence()
    before = json.dumps(thaw(saved["journal"]), sort_keys=True)
    result = export_native_kernel_view(saved, tmp_path)
    payload = json.loads(Path(result["recording"]).read_text(encoding="utf-8"))
    atoms, reports = {}, {}
    assert len(payload["frames"][0]["atom_updates"]) == 2
    assert sum(len(frame["atom_updates"]) for frame in payload["frames"]) < 2*len(payload["frames"])
    for frame in payload["frames"]:
        atoms.update({atom["id"]: atom for atom in frame["atom_updates"]})
        if frame["measurement_updates"]:
            assert frame["time"] == 17
        reports.update(frame["measurement_updates"])
    assert {atom: [value["position"]["x_um"], value["position"]["y_um"]] for atom, value in atoms.items()} == saved["final"]["positions"]
    assert reports == {"r.m": 1}
    assert payload["measurement_completion_times_us"] == {"r.m": 17}
    assert {id for op in payload["operations"] for id in op["gate_ids"]} == set(saved["final"]["completed_gate_ids"])
    assert {id for frame in payload["frames"] for id in frame["completed_gate_ids_delta"]} == {"h", "m", "reset"}
    assert payload["frames"][-1]["aods"]["AOD_0"]["enabled_rows"] == [False]
    assert payload["frames"][-1]["axes_by_aod"]["AOD_0"] == {"x_um": [0, 10], "y_um": [130]}
    assert payload["scheduling_report_source"]["source_id"] == "viewer-trajectory"
    assert payload["scheduling_report_source"]["quantum_projection"] is False
    assert payload["scheduling_report_source"]["fidelity"] is None
    assert all(not frame["quantum_tracking"] for frame in payload["frames"])
    assert payload["scene"]["atom_roles"]["Q1"]["stabilizer_basis"] == "X"
    assert payload["scene"]["spacing_um"] == 5
    assert payload["summary"]["wall_time_us"] == 20
    assert sum(row["duration_us"] for row in payload["summary"]["categories"]) == pytest.approx(20)
    assert payload["summary"]["metrics"]["total_atom_distance_um"] == 130
    assert payload["atom_statistics"] is None and payload["atom_statistics_unavailable"]
    assert before == json.dumps(thaw(saved["journal"]), sort_keys=True)
    html = Path(result["replay"]).read_text(encoding="utf-8")
    assert "NeutralAtomViewer.mount" in html and "__SHELL_JSON__" not in html
    assert "MARKER_ATOM_UM=2.3" in html and "resource-details" in html


def test_export_rejects_mismatched_delta_end_state_and_premature_reports():
    saved = evidence()
    saved["final"]["positions"]["Q0"] = [99, 130]
    with pytest.raises(ValueError, match="locations disagree"):
        build_native_kernel_payload(saved)
    saved = evidence()
    saved["final"]["measurement_completion_times_us"]["r.m"] = 16
    with pytest.raises(ValueError, match="timing disagrees"):
        build_native_kernel_payload(saved)


@pytest.mark.parametrize('basis', ('x', 'z'))
def test_factory_lowercase_roles_keep_identity_and_uppercase_stabilizer_marker(basis):
    saved = evidence()
    saved['role_to_atom'] = {'W4.d0': 'Q0', 'W4.'+basis+'0': 'Q1'}
    roles = build_native_kernel_payload(saved)['scene']['atom_roles']
    assert roles['Q0']['kind'] == 'data' and roles['Q0']['role'] == 'W4.d0'
    assert roles['Q1']['stabilizer_basis'] == basis.upper()
    assert roles['Q1']['role'] == 'W4.'+basis+'0'


def test_exporter_imports_only_allowed_legacy_presentation_modules():
    source = Path(__file__).parents[1]/"src/neutral_atom_app/native_kernel_view.py"
    imports = []
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            imports.append(node.module)
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
    legacy = {name for name in imports if name.startswith("neutral_atom_env")}
    assert legacy == {"neutral_atom_env.visualization.viewer", "neutral_atom_env.visualization.summary", "neutral_atom_env.visualization.theme"}


def test_canvas_javascript_loads_payload_and_interpolates_recorded_axes(tmp_path):
    node = shutil.which("node")
    if node is None:
        candidate = Path.home()/".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
        node = str(candidate) if candidate.exists() else None
    if node is None:
        pytest.skip("Node is unavailable for the shared Canvas component contract")
    result = export_native_kernel_view(evidence(), tmp_path)
    harness = Path(__file__).with_name("viewer_harness.cjs")
    script = "const fs=require('node:fs'),assert=require('node:assert/strict');"+\
        f"const harness=require({json.dumps(str(harness))});const v=harness(fs.readFileSync({json.dumps(result['replay'])},'utf8'));"+\
        "v.get('seek(9.5)');const p=JSON.parse(v.get('JSON.stringify(current.atoms.find(a=>a.id===\"Q0\").position)'));"+\
        "assert.equal(p.x_um,0);assert.equal(p.y_um,65);"+\
        "v.get('seek(data.duration)');assert.equal(v.get('current.atoms.find(a=>a.id===\"Q0\").position.y_um'),130);"+\
        "assert.equal(v.get('data.frames.some(f=>f.quantum_tracking)'),false);assert.equal(v.get('stabilizerBasis(\"Q1\")'),'X');"+\
        "assert.match(v.el('measurement-readout').textContent,/r.m=1/);"+\
        "v.get('seek(16.999)');assert(!v.el('measurement-readout').textContent.includes('r.m=1'));"+\
        "v.get('seek(0)');assert.equal(v.get('current.atoms.find(a=>a.id===\"Q0\").position.y_um'),0);console.log('PASS shared Canvas delta replay');"
    done = subprocess.run([node, "-e", script], text=True, capture_output=True, check=False)
    assert done.returncode == 0, done.stdout+done.stderr

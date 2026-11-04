"""Build the L2-only portable simulator using the current simplified plans."""

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

from experiments.small_circuit.run_shor_l2 import SHOR

from ..shot_sampling.animation import build_animation_html, replay_frame
from ..shot_sampling.plan import load_plan
from ..simplified_circuit.compile_inputs import BUILD

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "shot_sampling"
OUT = ROOT / "build"
ENGINE = SHOR / "browser_engine.js"


def encoded(value: object) -> str:
    """Embed JSON as inert text even when it contains HTML-like strings."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace(
        "<", "\\u003c"
    )


def build() -> Path:
    """Bundle plans, L2 worker, standard replay, and pulse schedule without assets."""
    OUT.mkdir(parents=True, exist_ok=True)
    plans = {str(n): load_plan(n) for n in (15, 21)}
    engine = ENGINE.read_text(encoding="utf-8")
    prepare = r"""
const fs=require('fs'),E=require(process.argv[1]);
const plans=JSON.parse(fs.readFileSync(0,'utf8'));
const schedules=Object.fromEntries(Object.entries(plans).map(([n,plan])=>[n,
  {...E.prepare(plan,{}).level2.schedule,selected_bitstring:null,
   selection_label:'默认参数的固定调度，尚未采样；条件门是否执行待定'}]));
process.stdout.write(JSON.stringify({defaults:E.DEFAULTS,schedules}));
"""
    prepared = json.loads(
        subprocess.run(
            ["node", "-e", prepare, str(ENGINE)],
            input=json.dumps(plans),
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
        ).stdout
    )
    provenance = {
        "model": "L2 static detuning plus OU noise with instantaneous XY4 rotations",
        "embedded_engine_sha256": hashlib.sha256(engine.encode("utf-8")).hexdigest(),
        "engine_file_sha256": hashlib.sha256(ENGINE.read_bytes()).hexdigest(),
        "reference_html_sha256": "2f3d1aa27252bd8009404e0b53a4d6f6044c4d6df855e1a127917c15ac9e3a66",
        "changes": [
            "L2 only; no legacy exponential dephasing selector",
            "All algorithm gate slots block global DD; no deferred Phase gates",
            "Z measurement at exposure completion; immediate reported feedback",
            "Stable short-interval OU moments; pre-readout DD coverage only",
            "Schedule and quantum events produced by the same preparation",
            "Storage-zone XY4 continues during remote measurement exposure with explicit pulse targets",
        ],
        "scope": "Instantaneous rotations; not finite-duration driven Hamiltonian simulation or device calibration.",
    }
    worker = (
        engine
        + "\nconst modelProvenance="
        + encoded(provenance)
        + ";\n"
        + """
self.onmessage = function(event) {
  try {
    const {plan,request}=event.data;
    const result=ShorBrowserEngine.sample(plan,request.parameters,request.shots,request.seed);
    result.model_provenance=modelProvenance;
    self.postMessage({result});
  } catch(error) { self.postMessage({error:error.message}); }
};
"""
    )
    frame = replay_frame(build_animation_html(plans, ENGINE))
    document = (ROOT / "index.html").read_text(encoding="utf-8")
    document = document.replace(
        "<!-- L2_FORMULAS -->", (ROOT / "formulas.html").read_text(encoding="utf-8")
    )
    document = document.replace(
        "<!-- PULSE_SCHEDULE -->",
        (ROOT / "pulse_schedule_fragment.html").read_text(encoding="utf-8"),
    )
    document = document.replace("<!-- INDEPENDENT_ANIMATION -->", frame)
    document = document.replace(
        "</head>",
        "<style>"
        + (ROOT / "pulse_schedule.css").read_text(encoding="utf-8")
        + "</style></head>",
    )
    document = document.replace(
        "“停止接收”仅取消浏览器等待；已提交的后台计算仍会完成。参数修改后需点击“开始采样”，结果不会与旧参数混合。",
        "在浏览器内独立采样，无需 Python 或服务器。“停止采样”会终止计算。改参数后点击“开始采样”，下方结果与脉冲调度图同步更新。",
    )
    payload = "".join(
        f'<script type="application/json" id="{name}">{encoded(value)}</script>'
        for name, value in (
            ("offline-plans", plans),
            ("offline-defaults", prepared["defaults"]),
            ("offline-worker", worker),
            ("initial-schedules", prepared["schedules"]),
        )
    )
    payload += (
        "<script>"
        + (BASE / "offline_runner.js").read_text(encoding="utf-8")
        + "\nShorOffline.schedules=JSON.parse(document.getElementById('initial-schedules').textContent);</script>"
    )
    payload += (
        "<script>"
        + (ROOT / "pulse_schedule.js").read_text(encoding="utf-8")
        + "</script>"
    )
    payload += "<script>" + (ROOT / "app.js").read_text(encoding="utf-8") + "</script>"
    document = document.replace("<!-- APPLICATION -->", payload)
    target = OUT / "SmallShor-Semiclassical-L2-Pulses.html"
    target.write_text(document, encoding="utf-8")
    (OUT / "model-provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )
    with zipfile.ZipFile(
        OUT / "SmallShor-Semiclassical-L2-Pulses.zip", "w", zipfile.ZIP_DEFLATED
    ) as archive:
        archive.write(target, target.name)
        archive.write(OUT / "model-provenance.json", "model-provenance.json")
        for n, plan in plans.items():
            archive.writestr(f"plans/n{n}.json", json.dumps(plan, indent=2))
            archive.write(
                BUILD / "semiclassical" / f"n{n}.qasm3", f"circuits/n{n}.qasm3"
            )
    return target


if __name__ == "__main__":
    result = build()
    print(f"{result}: {result.stat().st_size:,} bytes")

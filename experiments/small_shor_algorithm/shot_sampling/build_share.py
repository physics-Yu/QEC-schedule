"""Build portable browser sampling and local accelerated pages with one viewer."""

from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

from experiments.small_circuit.run_shor_l2 import SHOR

from ..simplified_circuit.compile_inputs import BUILD
from .animation import build_animation_html, replay_frame
from .plan import load_plan

ROOT = Path(__file__).resolve().parent
OUT = BUILD / "share"


def inline_json(value: object) -> str:
    """Keep JSON data inert inside HTML script elements."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace(
        "<", "\\u003c"
    )


def build() -> tuple[Path, Path]:
    """Embed all computation, plans and standard animation assets into HTML."""
    OUT.mkdir(parents=True, exist_ok=True)
    # Re-export the current compilations first so sampling and replay cannot
    # silently embed a bundled plan from an earlier circuit revision.
    plans = {str(n): load_plan(n) for n in (15, 21)}
    template = (ROOT / "index.html").read_text(encoding="utf-8")
    frame = replay_frame(build_animation_html(plans, ROOT / "browser_engine.js"))
    if template.count("<!-- INDEPENDENT_ANIMATION -->") != 1:
        raise ValueError("Missing unique animation insertion point.")
    template = template.replace("<!-- INDEPENDENT_ANIMATION -->", frame)
    local = OUT / "SmallShor-Local.html"
    local.write_text(template, encoding="utf-8")
    worker = (
        (ROOT / "browser_engine.js").read_text(encoding="utf-8")
        + """
self.onmessage = function(event) {
  try {
    const {plan,request}=event.data;
    const result=ShorBrowserEngine.sample(plan,request.parameters,request.shots,request.seed);
    self.postMessage({result});
  } catch(error) { self.postMessage({error:error.message}); }
};
"""
    )
    defaults = json.loads(
        subprocess.check_output(
            [
                "node",
                "-e",
                "process.stdout.write(JSON.stringify(require(process.argv[1]).DEFAULTS))",
                str(ROOT / "browser_engine.js"),
            ]
        )
    )
    payload = "".join(
        '<script type="application/json" id="'
        + name
        + '">'
        + inline_json(value)
        + "</script>"
        for name, value in (
            ("offline-plans", plans),
            ("offline-defaults", defaults),
            ("offline-worker", worker),
        )
    )
    payload += (
        "<script>"
        + (ROOT / "offline_runner.js").read_text(encoding="utf-8")
        + "</script>"
    )
    marker = "<script>\n'use strict';"
    if template.count(marker) != 1:
        raise ValueError("Missing unique app-script insertion point.")
    portable = template.replace(marker, payload + marker)
    portable = portable.replace(
        "“停止接收”仅取消浏览器等待；已提交的后台计算仍会完成。参数修改后需点击“开始采样”，结果不会与旧参数混合。",
        "本页在浏览器内完成采样，无需安装 Python 或连接服务器。“停止采样”会终止本次计算；参数修改后点击“开始采样”更新。",
    ).replace(
        "。请先启动本地 server.py。",
        "。请使用支持 Web Worker 的现代浏览器打开此 HTML。",
    )
    target = OUT / "SmallShor-Complete.html"
    target.write_text(portable, encoding="utf-8")
    with zipfile.ZipFile(
        OUT / "SmallShor-Semiclassical.zip", "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        archive.write(target, "SmallShor-Semiclassical.html")
        archive.write(BUILD / "manifest.json", "manifest.json")
        for n, plan in plans.items():
            archive.writestr(f"plans/n{n}.json", json.dumps(plan))
            for folder, source in (
                ("inputs", SHOR / "inputs"),
                ("semiclassical", BUILD / "semiclassical"),
            ):
                archive.write(source / f"n{n}.qasm3", f"{folder}/n{n}.qasm3")
    return target, local


if __name__ == "__main__":
    for path in build():
        print(f"{path}: {path.stat().st_size:,} bytes")

"""Build offline loss/time sensitivity viewers from existing validated traces."""

import json
import re
import zipfile
from html import escape
from pathlib import Path

from nadit_physical_compiler.visualization.result import build_result_trace

ROOT = Path(__file__).resolve().parent
WEB = (
    ROOT.parents[1]
    / "modules/physical_compiler/src/nadit_physical_compiler/visualization/web"
)
OUT = ROOT / "native_cphase/loss_time"
BUNDLE = OUT / "SmallShor-Loss-Time-Offline"


def read(path: Path) -> str:
    """Read UTF-8 source without altering the compiler's viewer assets."""
    return path.read_text(encoding="utf-8")


def replace_once(source: str, old: str, new: str) -> str:
    """Require a unique injection point rather than silently exporting broken UI."""
    if source.count(old) != 1:
        raise ValueError(f"Expected one injection point: {old[:70]}")
    return source.replace(old, new)


def assets() -> tuple[str, str, str, str]:
    """Adapt copies of the current player; leave production files unchanged."""
    template = replace_once(
        read(WEB / "viewer.html"),
        '<main class="workspace">',
        read(ROOT / "loss_time_panel.html") + '\n<main class="workspace">',
    )
    template = template.replace(
        "Final fidelity proxy", "P(no atom lost), independent model"
    )
    template = template.replace("CZ physical atom loss", "CZ atom loss")
    template = replace_once(
        template,
        '<option value="lanes">Lanes</option><option value="direct">Direct</option>',
        '<option value="direct">Recorded segments</option>',
    )
    template = template.replace("Noise in this step", "Loss in this step")
    template = template.replace("Noise parameters", "Current loss parameters")
    template = template.replace(
        "Channels and upstream records", "Conditional loss events"
    )
    template = re.sub(r'<tr id="loss-residence-row">.*?</tr>', "", template)
    template = template.replace(
        "Residence is physical loss, not T2 or computational leakage.",
        "Background lifetime loss is not included in this NAL preset.",
    )
    template = template.replace(
        "Independent estimates, booked when each event completes. No loss is sampled.",
        "Conditional on this saved ideal/forced branch. Events book on completion; no atom dropout is sampled.",
    )
    extra = ""
    for key, label in [
        ("cp", "CPhase atom loss (proxy)"),
        ("imaging", "Imaging"),
        ("single", "Single-qubit gate"),
        ("reset", "Reset"),
    ]:
        extra += f'<tr id="loss-{key}-row"><th>{label}</th><td id="loss-{key}-expected"></td>'
        for suffix in ("average", "maximum"):
            extra += f'<td><span id="loss-{key}-{suffix}"></span><div class="loss-bar"><i id="loss-{key}-{suffix}-bar"></i></div></td>'
        extra += "</tr>"
    template = replace_once(
        template, '<tr id="loss-other-row"', extra + '<tr id="loss-other-row"'
    )
    per_atom = (
        '<section class="analysis atom-loss-table"><h3>Final loss by atom and first-loss source</h3>'
        "<table><thead><tr><th>Atom</th><th>Total</th><th>Load</th><th>Store</th><th>Move</th>"
        "<th>CZ</th><th>CP</th><th>Imaging</th><th>1Q</th><th>Reset</th></tr></thead>"
        '<tbody id="atom-loss-rows"></tbody></table></section>'
    )
    template = (
        replace_once(template, "  <footer>", per_atom + "\n  <footer>")
        if "  <footer>" in template
        else replace_once(
            template,
            '  <script id="atom-replay-data"',
            per_atom + '\n  <script id="atom-replay-data"',
        )
    )
    names = [
        "paths.js",
        "model.js",
        "loss.js",
        "analysis.js",
        "loss-panel.js",
        "dashboard.js",
        "qec.js",
    ]
    modules = []
    old_sources = "['load','store','move','residence','cz','other']"
    new_sources = "['load','store','move','cz','cp','imaging','single','reset','other']"
    for name in names:
        content = read(WEB / name)
        if name in ("loss.js", "loss-panel.js"):
            content = replace_once(content, old_sources, new_sources)
        if name == "loss.js":
            content = re.sub(
                r"  const sourceOf = event => .*?;",
                "  const sourceOf = event => SOURCES.includes(event.cause) ? event.cause : 'other';",
                content,
                count=1,
            )
        if name == "dashboard.js":
            start = content.index("        const gates =")
            end = content.index("\n      }", start)
            content = (
                content[:start]
                + """        const events = (noise?.loss?.events || []).filter(e => e.step_index === step);
        $('leakage-summary').textContent = events.length ?
          events.length + ' conditional atom-loss events; first-loss attribution is shown below.' :
          'No modeled loss event in this step. No Pauli or logical-error simulation.';
        $('noise-count').textContent = events.length + ' loss events';
        $('noise-step').textContent = JSON.stringify({events}, null, 2);"""
                + content[end:]
            )
        modules.append(content)
    modules += [read(ROOT / "loss_time_model.js"), read(ROOT / "loss_time_controls.js")]
    viewer = replace_once(
        read(WEB / "viewer.js"),
        "trace = data.traces[index];",
        "trace = ShorLossTime.retime(data.traces[index], ShorControls.values());",
    )
    viewer = viewer.replace(
        "Direct preview, recorded timing", "Recorded segments, recalculated timing"
    )
    viewer = replace_once(
        viewer,
        "analysis = new AtomReplayAnalysis.Analysis(trace); dashboard.load(trace, analysis);",
        "analysis = new AtomReplayAnalysis.Analysis(trace); trace.noise_report.metrics.fidelity = analysis.finalRisk.allSurvive; dashboard.load(trace, analysis); ShorControls.report(trace, analysis);",
    )
    viewer = replace_once(
        viewer,
        "  loadTrace(0);",
        """  ShorControls.mount(() => {
    const origin = trace.steps[cursor.step]?.original_index, fraction = cursor.fraction;
    const atEnd = cursor.step >= trace.steps.length;
    loadTrace(Number($('trace-select').value));
    const mapped = atEnd ? trace.steps.length : trace.steps.findIndex(s => s.original_index === origin);
    seek(mapped < 0 ? 0 : mapped, fraction);
  });
  loadTrace(0);""",
    )
    style = read(WEB / "viewer.css") + "\n" + read(ROOT / "loss_time_panel.css")
    return template, style, "\n".join(modules), viewer


def main() -> None:
    """Export 14 standalone scenarios, one combined viewer and a sharing ZIP."""
    BUNDLE.mkdir(parents=True, exist_ok=True)
    traces = []
    for path in sorted((ROOT / "native_cphase/results").glob("*.json")):
        document = json.loads(read(path))
        description = "Rigid AOD · one entanglement row · " + (
            "forced branch; not a physical measurement sample"
            if "forced-" in path.stem
            else "ideal-state sampled measurement branch"
        )
        trace = build_result_trace(document, title=path.stem, description=description)
        trace["compilation"] = {
            "metrics": document["metrics"],
            "validation": document["validation"],
        }
        trace["loss_time"] = {
            "nodes": document["dag"]["nodes"],
            "edges": document["dag"]["edges"],
            "latency": document["device"]["readout"]["latency_us"],
        }
        traces.append(trace)
    if len(traces) != 14:
        raise ValueError(f"Expected the 14 saved cases; found {len(traces)}")
    template, style, modules, viewer = assets()

    def export(selected: list[dict], path: Path) -> None:
        values = {
            "TITLE": "Small Shor: Time and Atom Loss",
            "STYLE": style,
            "MODEL": modules,
            "SCRIPT": viewer,
            "DATA": json.dumps(
                {"schema_version": 1, "traces": selected},
                ensure_ascii=True,
                separators=(",", ":"),
            ).replace("<", "\\u003c"),
        }
        html = re.sub(
            r"\{\{(TITLE|STYLE|MODEL|SCRIPT|DATA)\}\}", lambda m: values[m[1]], template
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")

    export(traces, BUNDLE / "all-animations.html")
    links = []
    for trace in traces:
        name = trace["title"]
        export([trace], BUNDLE / "viewers" / (name + ".html"))
        links.append(
            f'<li><a href="viewers/{escape(name)}.html">{escape(name)}</a></li>'
        )
    (BUNDLE / "START_HERE.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>Shor time and loss explorer</title>'
        "<style>body{font:16px system-ui;max-width:1000px;margin:40px auto;color:#243748}li{margin:12px}a{color:#147b7b}</style>"
        "<h1>Small Shor: Time &amp; Atom-Loss Explorer</h1>"
        "<p>Open locally in a current browser. No server, installation or internet connection is required.</p>"
        '<p><a href="all-animations.html">Open all 14 animations with parameter sliders</a></p>'
        "<p>Time and loss use the actual saved action paths. NAL event losses are sourced; transport trap settings and CPhase loss are clearly labeled examples / assumptions. This is not a logical-error or fidelity estimator.</p>"
        "<ul>" + "".join(links) + "</ul>",
        encoding="utf-8",
    )
    (BUNDLE / "README.txt").write_text(
        "SMALL SHOR: OFFLINE TIME AND ATOM-LOSS SENSITIVITY\n\n"
        "Extract this ZIP and open START_HERE.html. all-animations.html is also self-contained and can be shared alone.\n"
        "All 14 saved cases are included. Sliders change fixed-order action times, feedback availability and physical loss together.\n"
        "Timing uses the recorded straight MOVE segments. No synthetic 200 um readout term or unverified lane detour is added.\n"
        "Main timing defaults: speed 1 um/us; each transfer 15 us; each exposure 100 us. Restore saved timing reproduces the original results.\n\n"
        "NAL source: https://arxiv.org/html/2609.10079v1#S6.SS2\n"
        "Transfer loss 0.2%, CZ and imaging loss 0.1%, 1Q/reset loss zero. CPhase defaults to the CZ rate as an uncalibrated proxy.\n"
        "Transport follows NAL Eqs. (2)-(3). Trap settings are illustrative, using the cited transport study's 87Rb, 90 kHz, 27 uK and 0.73 um harmonic width.\n"
        "Trap source: https://arxiv.org/html/2410.22627v1\n"
        "The NAL paper does not specify all numerical trap parameters. Depth spread defaults to zero; positive spread uses a positive-truncated Gaussian.\n\n"
        "The loss panel estimates independent physical atom survival on the chosen ideal/forced branch. It does not simulate dropout, subsequent gate cancellations, loss correction, Pauli noise or logical error.\n"
        "No background trap lifetime or reloading model is added. Reset does not restore a physically lost atom.\n"
        "Loss is booked at completion; source totals use first-loss attribution to avoid counting a lost atom repeatedly.\n"
        "Scenario JSON export records parameter values and derived statistics. References require internet only when clicked.\n",
        encoding="utf-8",
    )
    archive = OUT / "SmallShor-Loss-Time-Offline.zip"
    with zipfile.ZipFile(
        archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as zipped:
        names = ["START_HERE.html", "all-animations.html", "README.txt"]
        names.extend(f"viewers/{trace['title']}.html" for trace in traces)
        for name in names:
            zipped.write(BUNDLE / name, Path(BUNDLE.name) / name)
    print(
        json.dumps(
            {
                "html": str(BUNDLE / "all-animations.html"),
                "zip": str(archive),
                "zip_bytes": archive.stat().st_size,
                "cases": len(traces),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

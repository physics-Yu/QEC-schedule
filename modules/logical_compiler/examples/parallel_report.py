"""Read back two static factory cases and render their startup comparison.

No compilation, event sampling, noise evaluation or physical validation runs
here. Reported validation is source evidence. A fixed-seed pair is not a
statistical performance estimate, and proxy outcomes are not logical success.
"""

# Embedded SVG/HTML tags stay together for inspection of the exported markup.

from __future__ import annotations

import hashlib
import html
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from modules.logical_compiler.src.protocols.experiment_ledger import build_ledger_record

_BATCH = re.compile(r"^factory/batch\[(\d+)\]/")
_ATTEMPT = re.compile(r"/attempt\[(\d+)\]/")


def _json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _copy(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"INVALID_REPORT_INPUT: {name} must be a string-keyed mapping")
    copied: dict[str, Any] = json.loads(_json(dict(value)))
    return copied


def _time(value: Any) -> float:
    if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
        raise ValueError("INVALID_REPORT_TIME: expected finite nonnegative time")
    return float(value)


def _mode(case: dict[str, Any]) -> str:
    schedule = case.get("component_schedule")
    if schedule is None:
        return "serial"
    mode = schedule.get("policy", {}).get("mode")
    if mode not in ("serial", "parallel"):
        raise ValueError("INVALID_REPORT_MODE: missing component schedule policy")
    return str(mode)


def _validate(case: dict[str, Any], mode: str) -> None:
    if case.get("schema") != "nadit.factory_case/1" or _mode(case) != mode:
        raise ValueError(f"INVALID_REPORT_INPUT: expected a {mode} FactoryCase")
    if type(case.get("seed")) is not int:
        raise ValueError("INVALID_REPORT_SEED")
    for key in ("case_id", "code", "status"):
        if not isinstance(case.get(key), str) or not case[key].strip():
            raise ValueError(f"INVALID_REPORT_INPUT: missing {key}")
    if case["status"] in ("running", "pending"):
        raise ValueError("UNFINISHED_REPORT_CASE")
    duration = _time(case["duration_us"])
    seen = set()
    for call in case.get("calls", []):
        identity = call["invocation_id"]
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError("INVALID_REPORT_CALL_ID")
        seen.add(identity)
        if not _time(call["start_us"]) <= _time(call["end_us"]) <= duration:
            raise ValueError("INVALID_REPORT_CALL_INTERVAL")
        if not call.get("participant_roles") or any(
            not isinstance(role, str) for role in call["participant_roles"]
        ):
            raise ValueError("INVALID_REPORT_PARTICIPANTS")
    for event in case.get("events", []):
        if (
            not _time(event["available_at_us"])
            <= _time(event["released_at_us"])
            <= duration
        ):
            raise ValueError("INVALID_REPORT_EVENT_TIME")
    for mark in case.get("milestones", []):
        if _time(mark["at_us"]) > duration:
            raise ValueError("INVALID_REPORT_MILESTONE_TIME")


def _peak(calls: list[dict[str, Any]]) -> int:
    changes: list[tuple[float, int]] = []
    for call in calls:
        if call["end_us"] > call["start_us"]:
            changes.extend(((call["start_us"], 1), (call["end_us"], -1)))
    active = peak = 0
    for _, delta in sorted(changes):
        active += delta
        peak = max(peak, active)
    return peak


def _startups(case: dict[str, Any]) -> list[dict[str, Any]]:
    preparations = case["recipe"].get("initial_preparations", [])
    if not preparations or len({item["key"] for item in preparations}) != len(
        preparations
    ):
        raise ValueError(
            "INVALID_REPORT_RECIPE: distinct initial preparations required"
        )
    starts = {
        mark["batch"]: mark["at_us"]
        for mark in case["milestones"]
        if mark["kind"] == "batch_started"
    }
    result = []
    for batch, start in sorted(starts.items()):
        scope = f"factory/batch[{batch}]"
        identities = {f"{scope}/{item['key']}": item["role"] for item in preparations}
        initial_calls = [
            call
            for call in case["calls"]
            if any(
                call["invocation_id"].startswith(identity + "/")
                for identity in identities
            )
        ]
        marks = [
            mark
            for mark in case["milestones"]
            if mark["kind"] == "preparation_canonicalized"
            and mark.get("preparation") in identities
        ]
        canonicalized = {mark["preparation"]: mark["at_us"] for mark in marks}
        ready = (
            max(canonicalized.values())
            if canonicalized.keys() == identities.keys()
            else None
        )
        events = [
            event
            for event in case["events"]
            if event["occurrence"]["invocation_id"] in identities
        ]
        end = (
            ready
            if ready is not None
            else max(
                (
                    start,
                    *(call["end_us"] for call in initial_calls),
                    *(event["released_at_us"] for event in events),
                )
            )
        )
        calls = [
            call
            for call in case["calls"]
            if call in initial_calls or start <= call["start_us"] < end
        ]
        holds = []
        for identity, at in canonicalized.items():
            role = identities[identity]
            next_use = min(
                (
                    call["start_us"]
                    for call in case["calls"]
                    if role in call["participant_roles"]
                    and call["start_us"] >= at
                    and call not in initial_calls
                ),
                default=end,
            )
            until = min(end, next_use)
            if until > at:
                holds.append(
                    {
                        "role": role,
                        "start_us": at,
                        "end_us": until,
                        "evidence": "canonicalized_initial_preparation_waiting_for_supply",
                    }
                )
        raw = [
            call
            for call in initial_calls
            if call["component_id"] == "raw_t_postselection"
        ]
        raw_identities = {
            call["invocation_id"].split("/attempt[", 1)[0] for call in raw
        }
        result.append(
            {
                "batch": batch,
                "start_us": start,
                "window_end_us": end,
                "ready_at_us": ready,
                "duration_us": None if ready is None else ready - start,
                "ready_evidence": "last_initial_preparation_canonicalized_mark"
                if ready is not None
                else "incomplete_initial_preparations",
                "roles": list(dict.fromkeys(item["role"] for item in preparations)),
                "initial_identities": identities,
                "calls": calls,
                "events": events,
                "canonicalized_marks": marks,
                "holds": holds,
                "raw_attempts": len(raw),
                "raw_rejections": sum(
                    event["occurrence"]["invocation_id"] in raw_identities
                    and event.get("values", {}).get("accepted") is False
                    for event in events
                ),
                "peak_raw_concurrency": _peak(raw),
            }
        )
    return result


def _summary(case: dict[str, Any], evaluation: dict[str, Any] | None) -> dict[str, Any]:
    ledger = build_ledger_record(case)
    startups = _startups(case)
    aods = (case.get("physical") or {}).get("device", {}).get("aods")
    aod_ids = None if aods is None else [aod["id"] for aod in aods]
    raw_ids = {
        call["invocation_id"].split("/attempt[", 1)[0]
        for call in case["calls"]
        if call["component_id"] == "raw_t_postselection"
    }
    return {
        "mode": _mode(case),
        "case_status": case["status"],
        "aod_ids": aod_ids,
        "aod_count": None if aod_ids is None else len(aod_ids),
        "duration_us": case["duration_us"],
        "startup_ready_us": startups[0]["ready_at_us"] if startups else None,
        "startup_duration_us": startups[0]["duration_us"] if startups else None,
        "startup_definition": "first batch; last canonicalized initial preparation mark",
        "raw_attempts": ledger["counts"]["raw_preparation_attempts"],
        "raw_rejections": sum(
            event["occurrence"]["invocation_id"] in raw_ids
            and event.get("values", {}).get("accepted") is False
            for event in case["events"]
        ),
        "factory_s_calls": ledger["counts"]["factory_s_calls"],
        "algorithm_s_calls": ledger["counts"]["algorithm_s_calls"],
        "batch_decisions": ledger["batches"],
        "terminal_evaluation": evaluation,
        "factory_output_ready": ledger["factory_output_ready"],
        "algorithm_complete": ledger["algorithm_complete"],
        "physical_validation_ok": ledger["physical_validation_ok"],
        "validation_reexecuted": False,
        "logical_success": None,
        "probability_model_hashes": sorted(case.get("probability_models", {})),
        "startups": startups,
    }


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _number(value: Any) -> str:
    return "Not available" if value is None else f"{value:,.3f}"


def _label(call: dict[str, Any]) -> tuple[str, str]:
    component = call["component_id"]
    attempt = _ATTEMPT.search(call["invocation_id"])
    if component == "raw_t_postselection":
        retry = int(attempt.group(1)) if attempt else 0
        return (f"raw retry {retry}" if retry else "raw", "retry" if retry else "raw")
    if component.endswith("/canonicalize"):
        return "canon", "canonical"
    return {"initialize_0": "init 0", "initialize_plus": "init +"}.get(
        component, component
    ), "other"


def _svg(startup: dict[str, Any], mode: str, horizon: float) -> str:
    left, width, row_height = 90, 1020, 45
    plot = width - left - 25
    roles, origin = startup["roles"], float(startup["start_us"])
    height = 65 + row_height * len(roles)
    scale = plot / horizon if horizon > 0 else 1

    def x(time: float) -> float:
        return left + (time - origin) * scale

    pieces = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{mode} startup batch {startup["batch"]}" xmlns="http://www.w3.org/2000/svg">',
        f"<title>{mode.title()} startup batch {startup['batch']}; time in microseconds since batch start</title>",
    ]
    for index in range(6):
        value = horizon * index / 5
        at = left + value * scale
        pieces.append(
            f'<line class="grid" x1="{at:.3f}" y1="22" x2="{at:.3f}" y2="{height - 22}"/><text class="tick" x="{at:.3f}" y="15" text-anchor="middle">{value:,.0f}</text>'
        )
    for index, role in enumerate(roles):
        y = 35 + index * row_height
        pieces.append(
            f'<text class="patch" x="{left - 12}" y="{y + 16}" text-anchor="end">{_escape(role)}</text>'
        )
        for hold in startup["holds"]:
            if hold["role"] == role:
                pieces.append(
                    f'<rect class="hold" x="{x(hold["start_us"]):.3f}" y="{y + 3}" width="{(hold["end_us"] - hold["start_us"]) * scale:.3f}" height="29"><title>Canonicalized {_escape(role)} retained; {_number(hold["start_us"])} to {_number(hold["end_us"])} us. No quality or active storage-maintenance claim.</title></rect>'
                )
        for call in startup["calls"]:
            if role not in call["participant_roles"]:
                continue
            label, kind = _label(call)
            start, end = call["start_us"], call["end_us"]
            tooltip = _escape(
                f"{call['invocation_id']}\n{call['component_id']}\n{start:.6f}–{end:.6f} us; duration {end - start:.6f} us"
            )
            pieces.append(
                f'<g class="call {kind}" data-call-id="{_escape(call["invocation_id"])}"><title>{tooltip}</title>'
            )
            if end == start:
                pieces.append(
                    f'<line x1="{x(start):.3f}" x2="{x(start):.3f}" y1="{y + 6}" y2="{y + 29}" stroke-width="3"/>'
                )
            else:
                bar_width = (end - start) * scale
                pieces.append(
                    f'<rect x="{x(start):.3f}" y="{y + 7}" width="{bar_width:.3f}" height="20" rx="3"/>'
                )
                if bar_width > max(35, len(label) * 6.5):
                    pieces.append(
                        f'<text class="bar-label" x="{x(start) + bar_width / 2:.3f}" y="{y + 21}" text-anchor="middle">{_escape(label)}</text>'
                    )
            pieces.append("</g>")
        for event in startup["events"]:
            identity = event["occurrence"]["invocation_id"]
            if startup["initial_identities"][identity] != role:
                continue
            ready, release = event["available_at_us"], event["released_at_us"]
            accepted = event.get("values", {}).get("accepted")
            state = (
                "accepted"
                if accepted is True
                else "rejected"
                if accepted is False
                else "unknown"
            )
            pieces.append(
                f'<g class="event {state}"><title>{_escape(identity)} attempt {event["occurrence"]["attempt"]}: {state}; results ready {_number(ready)} us, event released {_number(release)} us. Coarse event, not physical measurement bits.</title><line class="ready" x1="{x(ready):.3f}" x2="{x(ready):.3f}" y1="{y + 2}" y2="{y + 32}"/><circle cx="{x(release):.3f}" cy="{y + 34}" r="4"/></g>'
            )
    if startup["ready_at_us"] is not None:
        at = x(startup["ready_at_us"])
        pieces.append(
            f'<line class="startup-ready" x1="{at:.3f}" x2="{at:.3f}" y1="22" y2="{height - 22}"><title>All initial preparations canonicalized at {_number(startup["ready_at_us"])} us</title></line>'
        )
    pieces.append(
        f'<text class="axis" x="{left}" y="{height - 3}">Time since batch start (µs); absolute origin {_number(origin)} µs</text></svg>'
    )
    return "".join(pieces)


def _report(comparison: dict[str, Any]) -> str:
    modes = comparison["modes"]
    rows = [
        ("Case status", "case_status"),
        ("AOD inventory", "aod_count"),
        ("Total duration (µs)", "duration_us"),
        ("First startup ready (µs)", "startup_ready_us"),
        ("Raw attempts", "raw_attempts"),
        ("Raw rejections", "raw_rejections"),
        ("Factory S calls", "factory_s_calls"),
        ("Algorithm S calls", "algorithm_s_calls"),
    ]
    lines = [
        "# Serial / parallel component comparison",
        "",
        f"Case `{comparison['case_id']}` · seed `{comparison['seed']}` · code `{comparison['code']}`",
        "",
        "| Metric | Serial | Parallel |",
        "| --- | ---: | ---: |",
    ]
    for label, key in rows:
        values = [modes[mode][key] for mode in ("serial", "parallel")]
        lines.append(f"| {label} | {values[0]} | {values[1]} |")
    lines.extend(
        (
            "",
            "Timing and events are read from the supplied static cases. No compilation, sampling, noise evaluation or physical revalidation was performed.",
            "",
            "Startup readiness is the last canonicalized initial-preparation mark of the first batch, only when every declared initial role completed. All batch startups remain in comparison.json and the HTML report.",
            "",
            "Factory decisions and optional terminal proxy evaluations remain separate from logical success, which is unknown. A fixed seed does not force the same outcome when a scoped model changes; duration differences may include different selected branches. This pair is not a statistical speedup estimate.",
            "",
            "[Component timeline](index.html) · [Serial atom replay](serial/index.html) · [Parallel atom replay](parallel/index.html)",
            "",
            "Input hashes use canonical JSON content, not source-file bytes.",
            "",
            f"- Serial case SHA-256: `{comparison['inputs']['serial_case_sha256']}`",
            f"- Parallel case SHA-256: `{comparison['inputs']['parallel_case_sha256']}`",
            "",
        )
    )
    return "\n".join(lines)


def _page(comparison: dict[str, Any]) -> str:
    modes = comparison["modes"]
    cards = []
    for mode, item in modes.items():
        cards.append(
            f'<section class="metric"><h2>{mode.title()}</h2><p>AOD inventory: {_escape(item["aod_count"] if item["aod_count"] is not None else "unknown")}</p><div class="value">{_number(item["duration_us"])} <small>µs</small></div><p>Startup ready: {_number(item["startup_ready_us"])} µs</p><p>{item["raw_attempts"]} raw attempts · {item["raw_rejections"]} rejected · S {item["factory_s_calls"]} factory / {item["algorithm_s_calls"]} algorithm</p><p class="status">{_escape(item["case_status"])}</p></section>'
        )
    charts = []
    batch_ids = sorted(
        {row["batch"] for item in modes.values() for row in item["startups"]}
    )
    for batch in batch_ids:
        pair = {
            mode: next((row for row in item["startups"] if row["batch"] == batch), None)
            for mode, item in modes.items()
        }
        horizon = max(
            (
                row["window_end_us"] - row["start_us"]
                for row in pair.values()
                if row is not None
            ),
            default=0,
        )
        charts.append(
            f'<section class="timeline"><h2>Batch {batch} · initial supply</h2>'
        )
        for mode, row in pair.items():
            charts.append(f"<h3>{mode.title()}</h3>")
            if row is None:
                charts.append("<p>This batch is absent from this selected case.</p>")
            else:
                charts.append(
                    f'<p class="subtle">Peak simultaneous raw bodies: {row["peak_raw_concurrency"]} · raw attempts {row["raw_attempts"]} · rejected {row["raw_rejections"]}</p>'
                )
                charts.append(_svg(row, mode, horizon))
        charts.append("</section>")
    decisions = []
    for mode, item in modes.items():
        lines = []
        for batch in item["batch_decisions"]:
            probability = batch["acceptance_probability"]
            event = batch["final_event"]
            outcome = "Not evaluated" if event is None else event["outcome_key"]
            lines.append(
                f"<li>Batch {batch['batch']}: {_escape(outcome)}; acceptance probability {'not available' if probability is None else f'{probability:.9g}'}</li>"
            )
        terminal = item["terminal_evaluation"]
        terminal_text = (
            "Not supplied"
            if terminal is None
            else _escape(
                f"{terminal.get('status', 'unspecified')}; proxy_success={terminal.get('proxy_success')}"
            )
        )
        decisions.append(
            f"<section><h3>{mode.title()}</h3><ul>{''.join(lines)}</ul><p>Terminal proxy: {terminal_text}</p><p>Logical success: unknown</p></section>"
        )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Serial / parallel component comparison</title><style>
body{{margin:0;background:#f5f7fb;color:#182334;font:15px system-ui,sans-serif}}main{{max-width:1120px;margin:auto;padding:36px 24px}}h1{{font-size:30px;margin:6px 0 12px}}h2{{font-size:20px}}h3{{font-size:16px;margin-bottom:4px}}p{{line-height:1.55}}a{{color:#185caa}}.eyebrow,.subtle{{color:#5c6b7d}}.cards,.decisions{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.metric,.timeline,.evidence{{background:white;border:1px solid #dce3ec;border-radius:12px;padding:20px;margin:20px 0}}.metric{{margin:0}}.value{{font-size:27px;font-weight:650}}small{{font-size:14px;font-weight:400}}.status{{font-family:monospace}}nav{{display:flex;flex-wrap:wrap;gap:20px;margin:20px 0}}svg{{width:100%;height:auto;display:block}}.grid{{stroke:#e3e9f1}}.tick,.axis{{font-size:11px;fill:#657388}}.patch{{font-size:13px;fill:#23344e}}.call.raw{{fill:#087f8c;stroke:#087f8c}}.call.retry{{fill:#d97813;stroke:#d97813}}.call.canonical{{fill:#7455b5;stroke:#7455b5}}.call.other{{fill:#4275b8;stroke:#4275b8}}.bar-label{{font-size:11px;fill:white;stroke:none}}.hold{{fill:#e6f3e9;stroke:#82b98a;stroke-dasharray:3 3}}.ready{{stroke:#63758a;stroke-dasharray:2 2}}.event.accepted circle{{fill:#237c46}}.event.rejected circle{{fill:#bd3e3e}}.event.unknown circle{{fill:#63758a}}.startup-ready{{stroke:#203c64;stroke-width:1.5;stroke-dasharray:5 4}}.legend{{display:flex;flex-wrap:wrap;gap:14px;font-size:13px}}.legend span::before{{content:"";display:inline-block;width:12px;height:12px;margin-right:5px;background:var(--color);vertical-align:-1px}}code{{overflow-wrap:anywhere;font-size:12px}}@media(max-width:700px){{main{{padding:20px 10px}}.cards,.decisions{{grid-template-columns:1fr}}.timeline{{padding:10px}}}}
</style></head><body><main><div class="eyebrow">STATIC CASE READBACK · NO NEW COMPILATION OR SAMPLING</div><h1>Serial / parallel component comparison</h1><p>Case <code>{_escape(comparison["case_id"])}</code> · seed <strong>{comparison["seed"]}</strong> · {_escape(comparison["code"])}</p><nav><a href="serial/index.html">Serial atom replay ↗</a><a href="parallel/index.html">Parallel atom replay ↗</a><a href="comparison.json">Comparison JSON</a><a href="report.md">Evidence notes</a></nav><div class="cards">{"".join(cards)}</div><p class="subtle">One fixed-seed pair. Selected branches can differ when scoped probabilities change; these durations are not a statistical speedup estimate.</p><div class="legend"><span style="--color:#087f8c">Raw body</span><span style="--color:#d97813">This patch's retry</span><span style="--color:#7455b5">Canonicalization</span><span style="--color:#4275b8">Other component</span><span style="--color:#e6f3e9">Canonicalized state retained</span></div><p class="subtle">Dashed markers: physical results ready. Dots: coarse event release (green accepted, red rejected). Dark dashed line: startup ready. Hover for source identities and exact times. Zero-duration calls use a thin marker. Holding does not imply a quality or storage-maintenance guarantee.</p>{"".join(charts)}<section class="evidence"><h2>Factory decisions and terminal proxy</h2><div class="decisions">{"".join(decisions)}</div><p>Physical validation is reported from the input artifacts and was not rerun. Logical success remains unknown.</p></section><section class="evidence"><h2>Input identity and hashes</h2><p>Both cases use the same case ID, seed, code and complete recipe. Reference parameters equal: {_escape(comparison["controls"]["reference_parameters_equal"])}; limits equal: {_escape(comparison["controls"]["limits_equal"])}.</p><p>Serial canonical JSON SHA-256<br><code>{comparison["inputs"]["serial_case_sha256"]}</code></p><p>Parallel canonical JSON SHA-256<br><code>{comparison["inputs"]["parallel_case_sha256"]}</code></p></section></main></body></html>"""


def write_parallel_comparison(
    serial_case: dict[str, Any],
    parallel_case: dict[str, Any],
    output: Path,
    *,
    serial_evaluation: Mapping[str, Any] | None = None,
    parallel_evaluation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write comparison.json, report.md and a component-level SVG/HTML report.

    Inputs must be completed FactoryCase snapshots with matching case ID, seed,
    code and full recipe and distinct serial/parallel schedule modes. Optional
    terminal evaluations retain their own explicit evidence; absence stays null.
    Output may contain serial/ and parallel/ atom viewers. Existing report files
    are never overwritten. Input objects remain unchanged. Raises ValueError for
    inconsistent inputs and FileExistsError for an existing report file.
    """
    cases = {
        "serial": _copy(serial_case, "serial_case"),
        "parallel": _copy(parallel_case, "parallel_case"),
    }
    for mode, case in cases.items():
        _validate(case, mode)
    for key in ("case_id", "seed", "code", "recipe"):
        if cases["serial"].get(key) != cases["parallel"].get(key):
            raise ValueError(f"REPORT_IDENTITY_MISMATCH: {key}")
    evaluations = {}
    for mode, value in (
        ("serial", serial_evaluation),
        ("parallel", parallel_evaluation),
    ):
        evaluation = None if value is None else _copy(value, mode + "_evaluation")
        if evaluation is not None and any(
            evaluation.get(key) != cases[mode][key] for key in ("case_id", "seed")
        ):
            raise ValueError(f"REPORT_EVALUATION_IDENTITY_MISMATCH: {mode}")
        evaluations[mode] = evaluation
    comparison = {
        "schema": "nadit.parallel_comparison/1",
        "case_id": cases["serial"]["case_id"],
        "seed": cases["serial"]["seed"],
        "code": cases["serial"]["code"],
        "recipe_sha256": _hash(cases["serial"]["recipe"]),
        "inputs": {
            "serial_case_sha256": _hash(cases["serial"]),
            "parallel_case_sha256": _hash(cases["parallel"]),
            "serial_evaluation_sha256": None
            if evaluations["serial"] is None
            else _hash(evaluations["serial"]),
            "parallel_evaluation_sha256": None
            if evaluations["parallel"] is None
            else _hash(evaluations["parallel"]),
            "hash_encoding": "UTF-8 JSON; sorted keys; compact separators; ensure_ascii=False; no trailing newline",
        },
        "controls": {
            "same_case_id_seed_code_recipe": True,
            "reference_parameters_equal": cases["serial"].get("reference_parameters")
            == cases["parallel"].get("reference_parameters"),
            "limits_equal": cases["serial"].get("limits")
            == cases["parallel"].get("limits"),
        },
        "modes": {
            mode: _summary(case, evaluations[mode]) for mode, case in cases.items()
        },
        "readback_only": True,
        "logical_success": None,
        "statistical_speedup_claimed": False,
        "atom_replays": {
            "serial": "serial/index.html",
            "parallel": "parallel/index.html",
        },
    }
    payloads = {
        "comparison.json": _json(comparison) + "\n",
        "report.md": _report(comparison),
        "index.html": _page(comparison),
    }
    destination = Path(output).expanduser().resolve()
    if any((destination / name).exists() for name in payloads):
        raise FileExistsError(f"Comparison report already exists: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        with (destination / name).open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
    return comparison

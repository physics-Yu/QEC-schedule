"""Shared viewer presentation for the actual modular transport journal."""
import html
import json
from pathlib import Path


def export_report(result, evidence, directory):
    """Use the unchanged shared journal exporter and shared embeddable viewer."""
    from neutral_atom_app.native_kernel_view import build_native_kernel_payload
    from neutral_atom_env.visualization.viewer import write_bundle, write_html
    directory = Path(directory)
    payload = build_native_kernel_payload(evidence)
    if payload["completed_gate_ids"] or payload["measurement_completion_times_us"]:
        raise ValueError("The modular transport report cannot relabel gate or report effects")
    payload["scheduling_report_source"] = None
    payload["evidence_scope"] = (
        "two independent AOD pure transport modules; actual kernel journal and offline geometry review; "
        "no gate or report effects")
    payload["scene"]["aod_labels"] = {
        device: device + " · 独立 row / column" for device in payload["scene"]["aod_labels"]}
    recording = directory / "recording.json"
    recording.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                                    allow_nan=False), encoding="utf-8")
    replay = write_html(payload, directory / "replay.html")
    exported = {"recording": str(recording.resolve()), "replay": str(replay.resolve()),
                "frames": len(payload["frames"]), "operations": len(payload["operations"]),
                "reports": len(payload["measurement_completion_times_us"])}
    write_bundle(directory)
    summary_json = json.dumps(result, ensure_ascii=False).replace("<", r"\u003c")
    status = html.escape(result["offline_physical_status"])
    page = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>双 AOD 独立运输</title>
<style>body{margin:0;background:#f4f6fa;color:#20304c;font:15px system-ui,sans-serif}header{max-width:1180px;margin:auto;padding:20px}h1{font-size:26px}p{line-height:1.6}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}.metric{background:white;border:1px solid #dfe5ef;border-radius:10px;padding:14px;min-width:0}.metric strong{display:block;font-size:22px;overflow-wrap:anywhere}button{padding:9px;border:1px solid #b8c7dc;background:white;border-radius:8px;color:#20304c;cursor:pointer}.bookmarks{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}details{margin:14px 0}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere}#error{color:#b42318}@media(max-width:500px){header{padding:14px}h1{font-size:22px}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}</style></head><body>
<header><h1>双 AOD · 独立运输与归还</h1><p>左侧 data 17 原子，右侧 resource 17 原子。两台真实 5×5 AOD 使用独立模块时间线；资源先回家时，数据仍在返程。所有轨迹与 holder 来自轻量 Executor journal。</p>
<div class="metrics"><div class="metric">原子 / 设备<strong>34 / 2</strong></div><div class="metric">并发终态 μs<strong id="duration"></strong></div><div class="metric">同 profile 串行 μs<strong id="serial-duration"></strong></div><div class="metric">完成时间减少<strong id="reduction"></strong></div><div class="metric">独立物理审核<strong>__STATUS__</strong></div><div class="metric">量子门 / 报告<strong>0 / 0</strong></div></div>
<p id="device-completion"></p>
<div class="bookmarks" id="bookmarks"></div><details><summary>能力与起态范围</summary><p>仅运输和声明停留，不执行 syndrome、RESET、MEASURE 或 magic factory。左侧 X/Z 是冻结数据模板的布局标记；右侧 r00–r16 是运输载体，未编码、未执行工厂或制备 magic。staging 是本例运输停放标签，不是测量区合同。t=0 接受预先声明的 SLM homes，外部初始制备成本未知。活动行列由载荷推导，所有 Cartesian 空交点参与审核；不支持额外空活动 RF 轴。</p></details><p id="error"></p></header>
<main id="physical-viewer"></main><script src="atom-viewer.js"></script><script>
const summary=__SUMMARY__;
document.getElementById('duration').textContent=summary.physical_time_us.toFixed(3);
document.getElementById('serial-duration').textContent=summary.same_profile_serial_control.physical_time_us.toFixed(3);
document.getElementById('reduction').textContent=summary.same_profile_serial_control.time_reduction_percent.toFixed(2)+'%';
document.getElementById('device-completion').textContent='资源 AOD_MAGIC 在 '+summary.device_completion_us.AOD_MAGIC.toFixed(3)+' μs 完成归还；数据 AOD_0 在 '+summary.device_completion_us.AOD_0.toFixed(3)+' μs 完成。资源提前 '+summary.resource_early_return_us.toFixed(3)+' μs 回家。收益仅限此例相同端点、时长和初终态的串行对照。';
fetch('recording.json').then(response=>{if(!response.ok)throw new Error('录制读取失败');return response.json()}).then(data=>{
const viewer=window.NeutralAtomViewer.mount(document.getElementById('physical-viewer'),data);window.modularAodViewer=viewer;
for(const row of summary.bookmarks){const button=document.createElement('button');button.textContent=row.label;button.onclick=()=>{viewer.setTime(row.time);document.getElementById('physical-viewer').scrollIntoView({block:'start',behavior:'smooth'})};document.getElementById('bookmarks').append(button)}
}).catch(error=>{document.getElementById('error').textContent=String(error)});
</script></body></html>'''.replace("__STATUS__", status).replace("__SUMMARY__", summary_json)
    (directory / "index.html").write_text(page, encoding="utf-8")
    return exported

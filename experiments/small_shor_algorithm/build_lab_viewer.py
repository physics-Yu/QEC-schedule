"""Package two semiclassical sampled cases for the Chinese experimental viewer."""

import json
import re
import zipfile
from pathlib import Path

from nadit_physical_compiler.visualization.result import build_result_trace

ROOT = Path(__file__).resolve().parent
WEB = (
    ROOT.parents[1]
    / "modules/physical_compiler/src/nadit_physical_compiler/visualization/web"
)
OUT = ROOT / "native_cphase/lab_cn"
BUNDLE = OUT / "SmallShor-Lab-CN"


def main() -> None:
    """Preserve saved cases and export a portable two-case HTML and ZIP."""
    BUNDLE.mkdir(parents=True, exist_ok=True)
    traces = []
    for n in (15, 21):
        path = (
            ROOT
            / f"native_cphase/results/n{n}-semiclassical-native-cz-ideal-sample.json"
        )
        document = json.loads(path.read_text(encoding="utf-8"))
        assert not any(node["name"] == "cp" for node in document["dag"]["nodes"])
        trace = build_result_trace(document, title=f"N={n}")
        outcomes = {
            m["result"]["measurement_id"]: m["value"] for m in document["measurements"]
        }
        decisions = {op["operation_id"]: op["status"] for op in document["operations"]}
        conditioned = [node for node in document["dag"]["nodes"] if node["condition"]]
        trace["lab"] = {
            "n": n,
            "seed": 17,
            "conditioned": len(conditioned),
            "executedConditional": sum(
                decisions[node["id"]] == "emitted" for node in conditioned
            ),
            "measurements": sorted(
                [
                    {
                        "measurement_id": node["source_id"],
                        "bit": node["clbits"][0],
                        "value": outcomes[node["source_id"]],
                    }
                    for node in document["dag"]["nodes"]
                    if node["name"] == "measure"
                ],
                key=lambda record: record["bit"],
            ),
        }
        trace["loss_time"] = {
            "nodes": document["dag"]["nodes"],
            "edges": document["dag"]["edges"],
            "latency": document["device"]["readout"]["latency_us"],
        }
        trace.pop("compilation", None)
        traces.append(trace)
    engine = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            WEB / "paths.js",
            WEB / "model.js",
            ROOT / "loss_time_model.js",
            ROOT / "lab_model.js",
        ]
    )
    values = {
        "CSS": (ROOT / "lab_viewer.css").read_text(encoding="utf-8"),
        "UI": (ROOT / "lab_viewer.js").read_text(encoding="utf-8"),
        "ENGINE": engine,
        "DATA": json.dumps(
            {"traces": traces}, ensure_ascii=True, separators=(",", ":")
        ).replace("<", "\\u003c"),
    }
    html = re.sub(
        r"\{\{(CSS|UI|ENGINE|DATA)\}\}",
        lambda m: values[m[1]],
        (ROOT / "lab_viewer.html").read_text(encoding="utf-8"),
    )
    (BUNDLE / "all-animations.html").write_text(html, encoding="utf-8")
    (BUNDLE / "阅读说明.txt").write_text(
        "NADiT 半经典 Shor 中文实验展示\n\n"
        "解压后双击 all-animations.html，无需安装或启动服务器。也可单独分享此 HTML。\n"
        "仅包含 N=15、N=21 两条已有的理想态测量采样分支；不包含 CPhase 动画或强制分支。\n"
        "动画只保留时间、当前操作、原子位置和经典结果；下方有动态 loss 表及可点击的 schedule。\n"
        "参数说明、逐原子结果、计算公式和来源均在页面内。所有滑轨下限为 0，默认值仍为展示场景。\n\n"
        "物理原子丢失与 T2 相干衰减分别列出。模拟平均 loss = mean(1-S_i*C_i)，仅为模拟粗估，不是电路失败率。\n"
        "T2 默认 1000 ms 为示例，需要实验标定。只累计有效相干区间内的空闲和搬运，不累计量子门或读出本身。\n"
        "速度为 0 时电路无法完成；T2 为 0 且暴露为正时完全退相干；质量/频率/阱宽为 0 时暂停模型计算。\n"
        "物理 loss 基于 NAL Table II 与式 (2)-(4)，陷阱参数为已标注的示例。没有 QEC 解码或实际态错误传播。\n"
        "参考：https://arxiv.org/html/2609.10079v1#S6.SS2\n"
        "陷阱示例：https://arxiv.org/html/2410.22627v1\n",
        encoding="utf-8",
    )
    archive = OUT / "SmallShor-Lab-CN.zip"
    with zipfile.ZipFile(
        archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as zipped:
        for name in ("all-animations.html", "阅读说明.txt"):
            zipped.write(BUNDLE / name, Path(BUNDLE.name) / name)
    print(
        json.dumps(
            {
                "html": str(BUNDLE / "all-animations.html"),
                "zip": str(archive),
                "zip_bytes": archive.stat().st_size,
                "circuits": [t["lab"]["n"] for t in traces],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

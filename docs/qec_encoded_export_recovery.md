# 已完成 checkpoint 的独立核验与导出恢复

`encoded_export_recovery.py` 针对 forward 已完成、进程在末尾核验/导出期间中断的 encoded ZZ/XX retained instrument。它不调用调度器，不执行剩余门，不重新 RESET 或准备数据；不完整 DAG 或非空 pending queue 直接拒绝。原 archive 保持原样，结果写入独立新目录。这里的“completed”只属于重新核验后的 recovery 结果。

恢复必须核对 seed、protocol、compiled circuit、有限 platform、placement、destinations、原 initial 的完整内容，以及冻结 crash manifest 中 11 个原文件的字节长度和 SHA256。原 launch sidecar 与初始化源码记录必须一致。来源检查覆盖原已记录的 environment/strategy 文件及十个 QEC frontend 文件；只允许明确复核的 shared runner 旧→新 SHA 配对。原记录未包含 `surface_ghz.py`、`surface_qec.py`、`qec_layout.py`，因此其原源码指纹保存为 null，完整原源码一致性为 false；当前 recovery 指纹另列。新 producer 模块、CLI、Python 与 shared audit 源码单独记录，旧 `run_metadata.json` 只作原运行记录保存。

此前 strict resume 的 parent checkpoint/metadata/initial 指纹、所有 accepted plan 的完整内容与所有 committed trace 的原字符串前缀必须匹配。Parent 必须每个 accepted plan 已有真实 plan_started；尚未开始的尾计划在此窄恢复路径拒绝。Parent 的失败状态和旧 replay=false 原样保留，不能解释为旧运行通过。当前 trace 与 checkpoint 逐记录匹配；每个 plan_started 的完整 plan body 与 plans 文件核对，不能只比 ID。

完整状态重新通过 shared quantum reference、真实投影/报告、exactly-once native effects、依赖时序、operation/resource intervals、终态、保留数据、signed sectors、parity/coherence 和 detectors 审计。随后在新环境从原 initial 逐计划真实 submit/run，并用固定 canonical chunk 序列比较全部 snapshot 字节与 EOF。完整 VisualRecorder 来自这次真实重放，覆盖原前缀与末尾。Checkpoint 与 plans 逐条写出，需等于原文件 SHA；流式 serializer 的 Unicode、转义、嵌套对象、float、sets 和截断边界均与完整 public canonical serializer 的独立 byte oracle 对照。

原 scheduler decisions 缺失时不补空日志；保存 unavailable 说明，candidate rejections 为 null。`no_layout_staging` 的证据范围明确为全部 accepted-plan intents 与实际存在的 parent decisions。原 crashed 总 wall time 未知，保存 null；新 wall time 仅计此次恢复输入核验、审计、重放和导出。Windows `0xc0000005` 是原现场记录的访问冲突，机制未知，不定性为 OOM。新诊断文件和输出经路径解析后均禁止位于任一原 archive 内。新输出建立后的重放/导出普通异常保存 `recovery_failure.json`，不能生成 completed evidence；输入、source、parent 与初步完成审计的早期拒绝不建立新输出。CLI faulthandler 诊断保留解释器异常。

入口：

```powershell
python -m neutral_atom_experiments.qec_pbc.encoded_export_recovery --basis X --rounds 3 --seed 7 --crashed CRASHED --parent PARENT --output NEW_OUTPUT --crash-manifest FROZEN_MANIFEST --reviewed-runner-old-sha OLD_SHA --reviewed-runner-new-sha NEW_SHA --fault-log FRESH_OUTSIDE_ARCHIVES
```

测试中的短真实物理 fixture 是有限 51 原子平台上三个 native RESET/H/MEASURE 门，包含真实搬运、投影、时序、末尾 cleanup、strict parent 续跑和完整 replay；仅该 fixture 的 encoded output 审计明确替换，不作为 d3 仪器验收。完整 1860 门 XX 的输出与全历史重放必须另行实际执行。这是理想物理执行及工程恢复能力，不是 noisy fault tolerance、magic factory 或完整 encoded Shor。

# 2026-10-04 · 初始化及 syndrome 全体 MZ 汇集重编译

- 状态：COMPLETED，范围为当前 rigid ENV 首T前物理前缀兼容实现。
- 用户目标：初始化全部需要 RESET 的原子汇集 MZ 后统一复位；本轮所有 ancilla 汇集后统一测量，重新编译并固化，而非只更新标准。
- 实施范围：相同 full12 首 T 前3006原门，12算法 patch/204原子＋17资源载体；初始化 RESET221，首轮 syndrome MEASURE96/RESET96。当前 rigid ENV 前缀增加可复用的策略侧真实 SLM 汇集服务；不热换 frozen 轻量核或工厂运行，不声称完整 Enola codegen、factory/fullphysicalShor。
- 基线：managed HEAD `6bbafce2c9aad1e4aadc9938db64d9e07bf51b81`；原并行工作区只读，历史录制保留。

## 实施合同

显式在新profile初态声明有限、关闭的真实MZ SLM位，按设备整个home footprint最近合法竖直平移绑定目标。保持5um格点、10um停车/非伙伴、finite6 CZ、1um运输和5um Raman等阈值；照明x覆盖world。真实LOAD/route/OFFLOAD分趟卸载汇集，全部到位后一次RESET或一次MEASURE→原RESET，最后实际返回原holder。运输分波不强制服务分批。

## 验证与证据

`artifacts/collective-mz-2026-10-04/full12-attempt2` 实际执行并从原初态完整重放通过：3006门（H1777/CZ816/MEASURE96/RESET317）、413投影、96原报告、221原子、156plans，全部效果恰好一次、DAG与事件队列完成，全部原holder恢复，独立code/logical0和aux+1检查通过。模型时间34214.38814875767μs；编译/执行/录制742.0347s，包含完整独立原初态重放到导出前1269.5439s，共享主机计时，不作内核速度比较。新profile与8777几何不同，不声称同profile加速。

初始化收集/归还各5波：[60,48,48,48,17]；一次RESET221在5718.890192784996–5818.890192784996μs，完整服务含往返11489.535186326662μs。Syndrome收集/归还各2波：[48,48]；一次MEASURE96在31265.781380739376–31765.781380739376μs，随后一次RESET96到31865.781380739376μs，完整服务含往返5337.194000034524μs。两AOD运输顺序执行，实际跨设备运输重叠0；服务脉冲与运动/交接不重叠。

三项独立CLI审计均PASS：`audit_native_parallel_physical.py`核对原源、Stim投影、9401依赖区间与52全局CZ脉冲/816对/max36；`audit_patch_parallel_layout.py --mode enola`核对CSS/canonical四层（每层2实际脉冲）、350MOVE/12248载体端点与1263304非伙伴检查（最小10μm）；`audit_collective_mz.py`核对完整221独立纯态生成元、真实stable MZ holders、波次链、原报告完成、全M→R与原home归还，绑定8实际artifact SHA。连续运动资格来自Executor和完整原初态replay，不将端点审核单独推广为连续证明。

首次attempt1在执行前因观察器metadata白名单拒绝新合同字段而停止，opcount0；修复仅把合同留在平台/summary而不传观察器。失败诊断保存在独立attempt1。独立auditor补足完整生成元检查、仅允许已知prefix外层schema/严格false report_flip归一化，以及carrier集合顺序与源gate顺序分别核对；实际运行产物和生产代码未因审计格式修正变化。

最终集合服务/platform/专项audit/report测试67PASS（JUnit），与128已通过回归去重共195不同case；六个pending边界冷恢复、篡改与缺少完整生成元拒绝覆盖。架构278Python模块零违规，env/kernel本轮diff为空。现行RAG最终回执见`collective_mz_docs_2026_10_04.json`。小型可移植验收保存于`collective_mz_2026_10_04.json`；大型trace/plans/final与recording保持本地ignored。

实际[8778共用原子回放](http://127.0.0.1:8778/#physical-viewer)从同次Executor/VisualRecorder生成，绑定三audit及recording/decisions SHA。已核验初始化汇集/RESET221、syndrome汇集/MEASURE96/RESET96、终态3006门完成、测量结束前无报告/结束后96报告、同步缩放、390/320px无水平溢出、主统计展开/逐项折叠及console零error。真实截图和QA在run的`browser-qa/`；旧8777不替换。完整Enola codegen/轻量内核、E03连续两轮、factory/injection/完整physicalShor保持OPEN。

复现（Python3.12，PYTHONPATH含src、既有pytest与Stim依赖）：

```powershell
python -B examples/run_parallel_shor15_prefix.py --source references/qec_pbc_validation/shor15_native_prefix_seed0_2026_10_04 --output artifacts/collective-mz-2026-10-04/full12-attempt2 --patches 12 --layout enola --proposal references/qec_pbc_validation/enola_patch_proposal_2026_10_04.json --intra-patch --intra-services --pair-search --routing-policy standard --mz-service collective --wall-budget 1800
python -B tools/audit_native_parallel_physical.py artifacts/collective-mz-2026-10-04/full12-attempt2
python -B tools/audit_patch_parallel_layout.py artifacts/collective-mz-2026-10-04/full12-attempt2 --mode enola --proposal references/qec_pbc_validation/enola_patch_proposal_2026_10_04.json
python -B tools/audit_collective_mz.py artifacts/collective-mz-2026-10-04/full12-attempt2
```

阶段源码/小型证据按用户既有授权发布到原draft PR#3，保留pushurl=DISABLED、不merge；发布后独立fetch核对parent/tree/全部changedblob，回执另存。原并行工作区只读、历史与frozen源保持。

# 2026-10-04 · 批量 RESET 与终端 MEASURE 标准

- 状态：COMPLETED（标准固化与现有路径审查；后端接入仍 OPEN）。
- 用户目标：RESET 和最后 MEASURE 大规模并行，一起运到 MZ，作为标准方法。
- 本轮范围：更新既有 Enola＋MZ 唯一协议入口、E01/E04/E05 流程目录、迁移导航及 RAG；只读核查源依赖与历史合批实现。不启动新编译、工厂，不热换 frozen 源或重写已有回放。
- 基线：managed `codex/d3-shor15-stages`，HEAD `7a4eb36a70b31596149a61630cbbb4dfdde24b79`；原并行目录只读。

## 完成内容

默认跨 patch 汇集同阶段依赖允许的 RESET/MEASURE，联合运输到 MZ 后单批服务。分别声明运输容量与共同服务容量，AOD 多趟运送卸载汇集仍可保持一次共同服务；MZ 容量/依赖等不允许才拆服务批次，分别记录原因。联合载体的捕获、配置、slot、完整 RF 与旁观者仍全部计入；同批服务不把时长乘原子数或运输波次。测量轴、源屏障、逐原子 source/report、报告完成提交与唯一 Executor 保持。

明确区分初始化、辅助 syndrome、data 终端和 PBC/cat 终端。普通 round 不含 live data 末测；PBC 完整终端不能替换为全 data Z 读出。M→R 尽量共用 visit，实际终态按源要求。

## 验证

只读审查确认：旧 full12 RESET 四批 77/48/48/48；syndrome M 两批48、各随后同visit RESET48。算法 AOD 108交点、资源24，固定轴嵌入/捕获闭包仍约束可运输波次。新内核 `runtime.py` 多target effect/report 已支持；`native_kernel_memory.py` 的单目标服务是策略侧合批的接入点，未修改核心。

完整参考 `encoded_shor_native.py:271` 有逐门tail依赖。终端8个拉回observable由最终frame固定、两两对易，共用cat/verifier池使gadget串行；单gadget H_all→M_all→RESET_all与初始204RESET、失败cleanup108data M→R可作后续phase DAG目标。同一verifier重复核验和资源H9→M9→R9→frame/epoch释放顺序保留。未知输入d0不加入初始RESET。源参考随机投影/RNG顺序须保留，不能凭操作可对易就改变参考采样记录。

| 检查 | 本轮结果 |
| --- | --- |
| `artifacts/batch-mz-standard/repair_and_verify.py` | 目录10流程全部未资格化；批量规则、容量分波、66 frozen source 与旧 recording/replay SHA 一致。小回执保存于 `references/qec_pbc_validation/batch_mz_standard_design_check_2026_10_04.json`。 |
| RAG结构/来源与固定检索 | 72 chunks /62 sources、87/87召回；新增三项批量RESET/MEASURE及运输/服务容量区分检索。 |
| `git diff --check` | 文档/资料变更，无 src/tests/viewer 修改。 |

本地设计QA首次误替换capacity waves目录项，第二次发现Windows CRLF指纹未规范化；修复目录、按已声明text_lf归一化后重新验收，失败不作为物理结果。没有新 backend、调度性能、物理或浏览器资格。

## 下一步

新 Enola＋MZ 服务先验 E01/E04/E05 的单波、K+1 分波、跨 patch 报告、全 M→R 屏障与 cold restore；继续现有 E02/E03/E05/E10 单 patch 两轮路线。冻结工厂运行的新版接入另作版本化资格。

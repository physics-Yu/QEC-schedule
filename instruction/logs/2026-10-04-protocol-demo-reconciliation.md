# 2026-10-04 · 协议与 demo 口径修正

- 状态：COMPLETED（文档生效关系修正；新 backend/demo 仍 OPEN）。
- 用户目标：消除旧 QMAP 回放、Enola 同区目标和协议示意混用。
- 基线：managed `codex/d3-shor15-stages`，HEAD `c27aeabda63c30959ce8a8583c7b61f6758ff9f6`；原并行目录不写。
- 范围：现行文档与导航，保留 frozen core 和历史产物。

## 完成内容

在既有 `docs/qec_enola_mz_design.md` 增加唯一目标入口与要求表，没有新增第二套架构。迁移 instruction 的主图改为明确待实现的 Enola＋MZ 目标，QMAP freeze-v4 记录为已资格化的分区组件。architecture/current_version/agent/handoff 导航同步。

独立只读检查确认 attempt5 为 QMAP 17 原子、两轮 Z memory，共 25 报告＝16 辅助＋9 data 终端。其 recording/replay SHA 与 manifest 一致；CZ t=14846.1 μs 的 12 个照射原子恰成 6 对，各 5 μm。这些是旧产物的本轮核对，没有新编译或新物理资格。

发现旧 rigid MZ policy 从几何最近生成候选，再以完整服务时间优先排序；不能将该策略等同于用户的最近位置要求。新目标明确空间距离优先、时间只用于等距择优；旧代码/结果保持其版本和有界成本策略范围，当前新 MZ 适配仍未实现。

## 验证

| 检查 | 本轮结果 |
| --- | --- |
| `python artifacts/protocol-demo-reconciliation/check_and_refresh.py` | 10 流程均未资格化；新 E05 目标、现行导航/链接检查通过；66 frozen source 与 recording/replay 的原 manifest SHA 全部匹配。 |
| `python tools/query_qec_pbc_rag.py --check` | 72 chunks / 62 sources，无指纹错误；只刷新 8 个被修改文档/目录指纹，原 raw hash 和历史运行结论保留。 |
| `python tools/query_qec_pbc_rag.py --self-test` | 原有 84/84 召回通过。 |
| `git diff --check` | 通过；变更仅文档/资料，无 src/tests/viewer 修改。 |

[可移植检查摘要](../../references/qec_pbc_validation/protocol_demo_reconciliation_2026_10_04.json)保留 baseline、fingerprint 刷新清单与新能力未实现状态。仅文档检查、RAG 指纹/召回与旧产物完整性核对；未运行 native、factory 或量子态模拟，不产生新模型时长/质量结果。

## 未完成与下一步

新 Enola＋MZ 单 patch 纯两轮操作流及共用 viewer 尚未实现。落实显式活动轴语义/版本化 lowering，nearest-MZ 距离优先往返与纯 round；E02/E03/E05/E10 验收必须得到 16 辅助报告/16 辅助 reset、零 data 终端测量、独立作用对与精确恢复，再扩展两 patch。

未修改 freeze-v4 源码、viewer、旧 recording/replay 或任何物理阈值。8780 服务只读取既有离线回放，不运行编译。用户在浏览器当前状态为暂停 t=0；保持该状态，没有继续播放误导性的旧 demo。

## 阶段发布

文档修正提交 [c2db084](https://github.com/physics-Yu/QEC-schedule/commit/c2db0846f6cc6345fecb49915dfcc408c910dc37) 已发布到原 `codex/d3-shor15-stages`。独立 Git fetch 验证 parent `c27aeab`、完整 tree `a91c1cd1fcf34eac7c6cfcbee4f70e46bde5448f` 与全部 15 个修改 blob 和暂存字节精确一致；本地分支只在上述验证后 fast-forward 元数据，无文件覆盖。见[发布回执](../../references/qec_pbc_validation/protocol_demo_publication_2026_10_04.json)。保留 PR#3 draft/open/unmerged，pushurl=DISABLED；没有新 native 运行或新 backend 资格。独立源码复核确认旧 policy sort key 实为 `(actual_us, actual_distance, proxy_distance, x, y, zone_id)`。

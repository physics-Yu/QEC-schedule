# 2026-10-04 · Enola + MZ 同区兼容设计

- 状态：COMPLETED（本轮设计与目录目标完成；backend实现/物理资格另验）。
- 用户目标与范围：EZ/SZ合并，以Enola+独立MZ组织标准流程；本轮记录可审阅设计，不执行尚未实现的backend。
- 基线：managed `codex/d3-shor15-stages`，HEAD `1f996a7d121d88effa2873b70c081ae0dadd19ab`；原目录另一工厂任务源码不写。
- 相关规范：agent/handoff、native_kernel_migration、qec_factory_pipeline、architecture、全x EZ、标准routing与nearest MZ。

## 完成内容

[设计](../../docs/qec_enola_mz_design.md)和[目录](../../references/qec_pbc_validation/enola_mz_flow_catalog_2026_10_04.json)声明COMPUTE=EZ=SZ、带外MZ、作者2Q片段规划/项目适配/MZ服务/轻量唯一执行/controller。十项流程涵盖制备、compute、连续syndrome、终端读出、MZ分波、两patch、四patch/143背景、工厂、注入和恢复；所有physical_qualified=false。

固定Enola commit2944dbf的入口/router/codegen/placer只读审查，论文v2与官方文件分别记录为来源。兼容缺口：19×15/paired4硬编码与setter、空活动轴mask、Init起态、完整源依赖/重复coupling、独立连续几何和单AOD。现有SAproposal及scaling入口不冒称MZ集成。

独立设计审查指出并修正两项：旧rigid半格图最短性不能推广为row/column伸缩最短时间；MZ读出期间AOD可被复用，返程LOAD前必须从当时真实RF/masks重新绑定并实际配置。源`canonical_memory_program`含data终端读出，连续普通round需独立fragment。全带CZ需显式涵盖旁观资源。

RAG增加K72、项目设计L49与固定完整作者源码L50；不把旧placement来源范围扩为完整运行证据。

## 验证

| 检查 | 本轮结果 |
| --- | --- |
| `python artifacts/enola-mz-design/check_design.py`（本地设计QA） | 十项ID、两轮16报告/16reset、终端H→M、阶段引用、全部资格false及6个本地链接一致。 |
| `python tools/query_qec_pbc_rag.py --check` | 72chunks/62sources，全部207个唯一文件来源指纹检查通过。 |
| `python tools/query_qec_pbc_rag.py --self-test` | 84/84固定召回通过，新3项均首位K72。 |
| `git diff --check` | 通过；10个设计/导航/资料文件，未改src/tests或frozen core。 |
| 独立只读审查 | 修正rigid最短范围、返程RF绑定、显式mask准入、全带资源/光兼容、双设备review前置及有界工厂生命周期。 |

L47被修改的migration导航保留原SHA记录，新现状按text_lf刷新；新设计L49指纹绑定定稿。未运行新native/物理/浏览器，没有新时长或量子质量结果；freeze-v4及其源码不改。本地设计QA脚本仅检查文档/目录，不是backend功能测试。

## 下一步

实现单patch纯syndrome两轮、5μm版本化lowering、显式mask或逐步等价证明、nearest-MZ完整往返/分波和精确恢复；通过后才扩展多patch与factory-to-one-T。保持声明调度报告与fidelity=null，完整physicalShor待独立验收。

## GitHub 阶段发布

设计提交[1d936ce](https://github.com/physics-Yu/QEC-schedule/commit/1d936ceb6e9a921b1088e0650ea0e2d1af90c177)已发布到现有 `codex/d3-shor15-stages`；独立fetch确认parent `1f996a7`、完整tree `ae4b943999bcb6c9cf2501ee52aa02a1f122cd66`和全部10个changed blobs与本地index相同。没有执行checkout/reset、改pushurl或写原目录。PR#3仍draft/open/unmerged；[回执](../../references/qec_pbc_validation/enola_mz_design_publication_2026_10_04.json)明确本阶段只有设计、new_native_runs=0、physical_qualified=false。

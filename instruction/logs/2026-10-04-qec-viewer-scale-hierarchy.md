# 2026-10-04 · QEC 回放缩放、稳定子标识与统计层级

- 状态：COMPLETED
- 用户目标：原子只比 SLM trap 略大；原子、trap、AOD 与操作标记随空间缩放和窗口同步缩小；明确 X/Z 稳定子辅助角色；主要统计/时间占用优先，逐项详情默认折叠；重新展示上轮完整 12 码块物理前缀。
- 基线：attached managed worktree `codex/d3-shor15-stages`，HEAD `9cfa6ad9f3bdbaf6ebb5b2ac4063393e490019d6`；上一轮 3006 门/221 原子/双 AOD 已完成执行和原初态完整重放。本轮仅修改观察器与报告布局，不新增物理执行或工厂/完整 Shor 验收。
- 相关规范：[visualization](../visualization.md)、[workflow](../workflow.md)、[QEC 供应协议](../qec_factory_pipeline.md)。

## 完成内容

`viewer.js` / `viewer-shell.html` 使用统一投影：trap 显示半径 2、原子 2.3，比例 1.15；SLM 圆形/AOD 菱形、线宽、命中/选择轮廓、门与交接动效同步缩放。已占据 trap 环在原子填充后绘制，避免略大的原子遮掉 holder 类型标记；X/Z 使用内部白色几何字形，活动填充色保持。

全宽画布之后首先展开主统计、11 类实际时间和五条设备资源占用。653 资源行、逐项状态/报告/原子与操作详情默认折叠；画布、列表/API 选择原子自动打开父层与 inspector。报告外层逐项卡片也默认折叠，保留七操作书签。主时间图不再显示批量 gate_id=null；不足以读文字的短脉冲仍保留真实区间、可点击色块及悬停详情。

从同一 full12 录制重建 `animation.html`、`atom-viewer.js` 和 `index.html`，本机8773服务继续显示上一轮真实前缀。录制 SHA `5e9cdce1b69e29eed8de73e18547ab05be42376d099b4c94cb51ae427e1a6d36`、source-prefix、summary 和独立审计字节均保持。物理模型与 runtime 源码未修改，没有重跑196plans或新增物理验收。

新合同见[呈现方案](../../docs/qec_viewer_presentation.md)，可移植[验收摘要](../../references/qec_pbc_validation/qec_viewer_presentation_2026_10_04.json)。RAG 新增 K65/L41、两项检索；旧L40受影响来源刷新已重新审阅的 normalized 指纹，历史raw留存。

## 决策与边界

- X/Z 标识来自 canonical 角色绑定，不能从坐标、当前 gate 或活动色推断，也不表示读出值。
- 算法共 48 个 X 和 48 个 Z 稳定子辅助位；右侧资源的八个辅助位只是未编码的预留模板角色，不宣称魔态工厂检查已执行。
- 符号尺寸是观察器的世界坐标显示参数，不代表光腰或物理作用半径，不进入物理验证。
- 时间占用沿用 committed recording 的类别/资源区间并集；不得把并发资源时长相加当总耗时。

## 验证

| 检查 | 本轮结果 | 证据 |
| --- | --- | --- |
| `pytest` visualization / replay_interaction / multi_aod_visualization / raman_batch_visualization / native_parallel_report / environment_boundary / slm_display | 31不同测试通过，6.31秒；不加历史234或重复peer结果 | 下方完整命令；public摘要 |
| `node tests/viewer_qec_scale.cjs RUN_DIR/animation.html` | 最终真实full12录制通过：1.15比例、按钮/resize、104字形、holder/红色CZ、父详情自动展开、无null标签、recording不变 | 新CJS；Node为DOM/Canvas替身，与实际浏览器分开 |
| `node tests/viewer_fit_resize.cjs RUN_DIR/animation.html` | 完整码块聚焦/resize、手动zoom/pan与录制不变通过 | 共用旧fit合同 |
| 独立读录制重算 | 全653资源区间并集，误差阈值1e-7μs，0不一致；48X/48Z算法角色+4X/4Z资源模板 | `artifacts/qec-viewer-refinement-2026-10-04/independent_observer_audit.json` |
| 真浏览器 | 七书签、X/Q009与Z/Q013详情、Q213资源模板说明；放大/缩小对照；390与320px均client=scroll（375/305）；主统计优先展开，其余默认折叠；console0错误 | 同目录`acceptance.json`、`final-cz-and-statistics.png`、wide/narrow截图 |
| architecture | 263模块、0违规 | `python tools/check_architecture.py` |
| RAG fresh/retrieval/portability | 65chunks/53sources/145本地路径，0陈旧；60/60检索、11/11可移植检查通过 | `--check` / `--self-test`；当轮`rag-retrieval.json`与原rag-portability档案 |
| 原始物理记录与原工作区 | 四个物理输入/审计文件SHA不变；本任务未写原目录tracked文件；其余35dirty及HEAD保持 | baseline / independent audit；并行handoff更新如下 |

命令：

```powershell
python -m pytest tests/test_visualization.py tests/test_replay_interaction.py tests/test_multi_aod_visualization.py tests/test_raman_batch_visualization.py tests/test_native_parallel_report.py tests/test_environment_boundary.py tests/test_slm_display.py -q
node tests/viewer_qec_scale.cjs artifacts/qec-parallel-prefix-2026-10-04/full12-dual-sparse-slm-attempt1/animation.html
node tests/viewer_fit_resize.cjs artifacts/qec-parallel-prefix-2026-10-04/full12-dual-sparse-slm-attempt1/animation.html
```

保留失败/纠正：初始15专项中的3个旧13px断言按已批准投影合同更新后通过；专用2MOVE夹具CJS误用于791MOVE full12的失败不计PASS，正确四项multi-AOD pytest使用其专用真实夹具通过；只读浏览器作用域不暴露页面global/compareDocumentPosition，改用实际DOM和离线独立几何检查；滚动位置下fullPage截图保留sticky浮动的旧图，最终在页标题可见时取完整图。统计null标签在真实浏览器发现并从生成源码修复。未独立重跑全部旧八份CJS，也未重跑长物理Executor；上述当轮测试范围明确列出。

原目录另一个任务追加“2026-10-04 工厂到单 T 交互设计演示”，保留其handoff更新；其他35 dirty及原HEAD9e28b2e保持。开始handoff SHA `18df69394076bdf6e6c8fcecc514ff27174ede5e8e445b3aa5dc472452dc6cdd`，收尾 `0d476a33b9c078180d66719a97ce5ccf8a4c6187c595c1368cdc98531769c3e3`。此任务没有写回任何原目录tracked文件。

## 下一步

本轮呈现已完成，stage沿用draft PR#3、不得merge。主线仍为 factory-first F1，不以显示X/Z或时间图宣称魔态工厂、tracked T/Born、noise/FT或完整物理Shor完成。

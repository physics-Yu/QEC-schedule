# 第四步 attempt2：物理矩阵通过，界面撤销子验收暂停

2026-09-12。用户批准补齐测试参数后，实际执行
`node tests/workbench_qec_controls.cjs artifacts/qec-ui-tests/input.json`，结果 PASS；没有修改 compiler 或物理规则。

## 已通过的范围

三份输入均完成真实编译和 compiler-free 独立重放：六门编辑线路、X(Q014)/seed23 的完整483槽GHZ₂、原点(0,0)/(45,5)的完整481槽GHZ₂。量子预期、效果各一次、原SLM位置及holder归还通过。矩阵证据在 `artifacts/qec-roadmap/step4-attempt2-matrix/matrix.json`。完整案例都通过协议检查；六门短线路预先声明不是GHZ协议。

错开布局耗时36861.8μs、65轮装卸，比默认布局明显退化。它改变了几何和实际随机测量分支，不能作为同分支公平速度对照；精确成本与分组不足见 [布局分析](qec_generalization_layout_analysis.md)。没有为此改策略或重试。

## 正式失败事实

新8785一致代码服务已恢复上述481槽真实执行产物，没有重编完整线路。真实Edge界面原点显示、输入JSON一致性、修改原点后只改变原点字段的检查通过。随后 `examples/accept_qec_origins_ui.py:74` 的 `assert undone == original` 失败：

- 原始第二原点为(45,5)。
- 编辑后为(40,0)。
- 点击一次撤销后仍为(40,0)。
- 三份导出的其余字段完全相同，包括门表与AOD配置；`page_errors=[]`。

证据：`artifacts/qec-roadmap/step4-attempt2-matrix/staggered_patches/ui-subcheck/` 内 failure.json、三个 full-export JSON 和界面截图。未执行后续双模式32×完整回放，也未进行短线路编译；4A不能标记为整体通过，4B/4C未开始。服务8785 PID14568，保存job `23e9ef476f5e1d6091bc7851a1aa75e4`，仅为未完成UI验收的入口。

## 原因假设与拟议重试

脚本先 `fill('40, 0')`，再人工 `dispatch_event('change')`，然后点击导出导致输入框失焦。浏览器可能在失焦时再触发原生change；目前原点onchange无相同值短路，而 `change()` 每次都压入撤销历史。这可解释一次撤销只撤掉重复历史项，但没有重新运行来验证，不能把推断写成已复现根因。

建议仅修正验收脚本：用 fill 后 Tab 自然提交一次，删去人工change；保留一次撤销必须精确恢复输入的断言。新attempt3只续做UI验收及原定下游；不改物理模型、不重跑已通过的三份完整物理编译。如果自然交互仍失败，再保留证据并暂停，不能临时改为点击两次撤销来通过。

依据用户“失败后由我审批再新尝试”的指令，当前状态 awaiting_approval；尚未修复或重试。

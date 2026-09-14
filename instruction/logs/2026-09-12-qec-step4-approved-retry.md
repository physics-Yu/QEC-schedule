# 第四步：获批补齐参数与继续矩阵

状态：STOPPED / AWAITING APPROVAL（attempt2真实UI子验收失败）。用户原文：“没太看懂，但是没有物理事实上的错误的话你就补齐参数好了”。已确认上一失败为主任务测试命令漏传JSON路径，没有执行界面断言，也没有物理失败证据。

已在`artifacts/qec-roadmap/status.json`记录审批原文，将attempt1的approval改为approved并新建attempt2，保留旧失败事实。实际命令`node tests/workbench_qec_controls.cjs artifacts/qec-ui-tests/input.json`通过；未改编译器、输入门序或物理规则。

48项布局/接口测试沿用本轮同源码通过证据，不重复运行。矩阵脚本只增加attempt参数及动态证据路径，避免把获批attempt2写成attempt1；没有改实验算法。执行：`python examples/run_qec_generalization_acceptance.py --attempt 2 --output artifacts/qec-roadmap/step4-attempt2-matrix`。

六门编辑线路compile+compiler-free重放PASS。完整X(Q014)/seed23实际483门/控制槽（不强称481），compile+独立重放PASS：19256.9μs、37轮装卸、Raman33μs、编译201.077s，同源稳定，量子GHZ₂/协议完整及原SLM终态通过。当前错开布局待结果。继续按单份编译/重放各600秒、4096候选/100000路径节点/10000决策，失败立即停并保留状态。4B重复带噪纠错及4C四逻辑仍未开始。

三项矩阵均compile+独立verify PASS。错开481槽：36861.8μs、65轮装卸、56CZ pulse、16批测量及16批RESET；编译415.796s，184计划重放通过。这是正确性泛化通过但性能退化，不能称性能胜出。当前仅推进新8785一致源码真实UI；4B/4C仍未启动。

新8785 UI首次检查失败：一次undo未恢复原点，AssertionError，证据ui-subcheck/failure.json及三份导出。无page error，未回放、未短编译、未开始4B/4C。只读推断为人工change和失焦自然change重复入历史，未修复/验证重跑。拟议只修测试交互为fill+Tab，保留undo强断言；须获用户批准。详情docs/qec_step4_attempt2_failure.md。8785 PID14568，savedjob23e9ef476f5e1d6091bc7851a1aa75e4；旧服务保留。

报告显示检查：首次等待弹窗超时，查明主任务写入approval字符串而合同要求对象；仅纠正报告账本为{status: pending, user_message: null}，未重试实验。随后8782真实浏览器弹窗已显示attempt2事实/假设/拟议范围，截图roadmap-failure-popup.png；open_in_codex返回queued，不宣称用户已看到。

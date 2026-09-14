# 2026-09-11 · M4 完整策略与可编辑验收

- 状态：COMPLETED
- 用户目标：授权多个子 agent 完成原 M4；专门调研 agent 接收核查 request，核实 EZ 中 CZ 上下 2 μm 配对能力。
- 起点：已有局部 greedy、动态 EZ、固定门集与 1/2/4 trap 联合运输；critical-path、有限 lookahead 与当前规则下统一比较未完成。
- 规范：milestones.md、compiler_contract.md、validation.md、physics.md、visualization.md。

## 实施分工与合同

- scheduler：同动作空间 basic/greedy/critical_path/lookahead、驻留/归还候选、有限真实分支与终态成本。
- acceptance：同初态/平台/终态比较、收益和反例、独立 replay、可重建报告。
- physics_research：一手论文及本地 Qiuniu ISA 核实，仅写调研报告并反馈审查问题。
- 主 agent：工作台/API接入、MOVE 内安全 Raman 子窗口、方向模型测试、整合与真实浏览器验收。

## 初期专项证据

- `python -m pytest tests/test_m4_direction_contract.py -q`：5 passed；真实准备后左右/上下相距 2 μm 均允许、4 μm 拒绝。
- `python -m pytest tests/test_raman_windows.py -q -k "not fill_starts"`：3 passed；解析窗口辅助函数，不代表调度整合已验收。
- `node --check src/neutral_atom_env/visualization/workbench.js`：通过。

## 物理结论

见 [定向调研](../../docs/m4_physics_research.md)。区域光照和标量距离模型没有水平限定；保留四方向，但不宣称 Qiuniu 真机上下/左右保真度已经标定。“中心上 2 / 下 2”是相距 4 μm，当前模型拒绝。

## 收口状态

四策略、统一比较、真实浏览器与交接均已完成。M4按原milestone在声明的单AOD/单trap有限线路族收口；M5/M6保持未实现。

## 最终实现与可视化证据

- 新增 `simulation/m4_policies.py`，`run_m4` 支持四策略和有限搜索参数，独立状态真实推演，不修改 live state。原始greedy为默认；CP对所有READY门排序。新 `simulation/raman_windows.py` 求解析安全子窗口。
- 调研agent复核发现并修复：EZ日志不能在末态重验早段Raman；恰好用完节点预算不等于截断；所有policy根候选失败必须携带原始rejections/report。故障注入确认失败不改变实时快照。
- 工作台新增四策略选择、数值预算、编译wall time、实际评分和完整决策JSON；保留原编辑/随机/撤销/导入导出/失败弹窗/32×管线。
- 新服务：`http://127.0.0.1:8768/`，PID **9692**，output `artifacts/workbench-m4-complete`，tab **19** 已标记deliverable。未刷新用户8767草稿，旧8766/8767服务保持。
- 真实浏览器：lookahead四门 **952.6 μs / 28 ops**；手动新增Q003上的H并切critical_path后五门 **983.6 μs / 30 ops**；随机载入八门 **1046.3 μs / 39 ops**。关键帧和真实时间模式32×均到终态，browser error日志为空。
- basic四H预设真实显示四颗SLM原子同时门操作，**4门 / 1 μs / 4 ops**。
- max_decisions=1时真实失败 **2/4门，476.3 μs / 14 ops**，弹窗DECISION_BUDGET_EXHAUSTED保留片段；关闭后换线路并重新编译成功。最终恢复四门lookahead，停在CZ的 **476.15 μs** 以便查看实际配对。
- 浏览器数值预算的Playwright fill没有触发change提交，改用真实键入+Tab已提交；不是用直接JS调用伪造浏览器交互。`browser-acceptance.json`记录观察与server产物。
- 四份实际录制的Node速度检查通过（greedy8门、CP5/8门、lookahead4门），覆盖0.25–32×、两种时间映射、终点停止及原物理数据不变。初次Python子进程捕获输出遇GBK解码失败，显式UTF-8后重跑通过；这是工具输出编码问题。

## 同平台比较结果（仿真 μs，含完整归还）

| 输入 | basic | greedy | critical_path | lookahead |
| --- | ---: | ---: | ---: | ---: |
| 四H并行 | 1.0 | 1.0 | 1.0 | 1.0 |
| 重复配对复用 | 2856.9 | 952.9 | 953.9 | 952.9 |
| 依赖分支 | 2956.9 | 3023.9 | 2398.9 | 2078.9 |
| 关键路径竞争 | 3056.9 | 2383.9 | 2335.9 | 2035.9 |
| 六原子占位 | 4229.2 | 4158.2 | 3869.2 | 3578.2 |

`artifacts/m4-complete-final/acceptance.json`：20/20运行 verified，各自独立重放。相同初始snapshot/terminal哈希；1trap、adaptive、site1、READY8、depth2、beam2、每次8nodes。等距终态见证两条首段均98μm/496.3μs，下一服务392.3对382.3μs，完整终态1684.6对1654.6μs。预算失败另存，最终诊断两见证独立验证。

矩阵期间的最后补丁只改诊断，不改评分或执行顺序。manifest如实记录source_changed_during_run=true，物理矩阵对应开始时编译版本；最终代码另验证诊断与实际计划重放，不说全矩阵由最终诊断版本重新编译。generator导出遗漏ready/site字段已依保存run_options补齐input元数据，trace/checkpoint不变，详见验收文档。

## 当前边界

M4交付限声明的有限调度/布局族，不保证全局最短或任意障碍布局可路由。CP权重是脉冲时长；lookahead的端点评分不预测未搜索运输，只有剩余脉冲项是下界。非抢占单AOD服务仍保留。1/2/4trap可调用新策略，主矩阵固定1trap，多trap仍联合运输后cell0服务。

复杂前瞻CLI实测151.2/167.8秒（开发主机有并发验证负载），超过HTTP90秒预算；不能承诺所有32原子/64门可交互完成。M5批量CZ、多独立AOD、RL、真机保真度仍未实现。本轮未创建commit、PR或发布。

## 最终回归与文件校验

| 检查 | 本轮结果 | 证据 |
| --- | --- | --- |
| `python -m pytest -q --tb=short` | 417 passed，1 warning，1196.58s | `artifacts/m4-full-pytest.txt`；warning为第三方dateutil弃用UTC接口 |
| 最后诊断补丁后 `python -m pytest tests/test_m4_policies.py -q --tb=short` | 20 passed，37.53s | `artifacts/m4-final-policy-pytest.txt` |
| `tests/test_raman_windows.py` + `tests/test_workbench_m4_policies.py` | 20 passed，1.89s | 主agent本轮运行 |
| `tests/test_m4_direction_contract.py` | 5 passed，3.67s | 主agent本轮运行 |
| `tests/test_m4_acceptance.py` | 4 passed，58.87s | 同初终态、并行与等距终态见证 |
| 完整比较及诊断记录 | 25份实际记录独立replay verified | 20矩阵+1预算失败+2等距终态+2最终诊断 |
| Node语法/播放 | 通过 | `playback-checks.json`，四份真实录制，两种时间模式0.25–32× |
| 真实浏览器 | 通过上述限定操作 | `browser-acceptance.json`，tab19 |
| 新文档相对链接 | 无缺失 | M4合同/调研/验收/日志；handoff与milestones同步 |

全量回归启动后仅有诊断补丁和对应测试追加；故最终补丁另做20项策略整模块复验，不把两次数量相加冒充新的全量测试总数。服务8768最终监听PID9692已核验。

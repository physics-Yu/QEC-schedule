# 2026-09-11 · 门集与同类型并行规范

- 状态：COMPLETED（本轮门规范实现与验收，不代表整个 M4 完成）
- 用户要求：可运行门仅 H、X、Y、Z、T、CZ，只有同一种门才可并行。
- 解释：H/H 可并行，H/X 和 CZ/H 的实际门作用区间不可重叠；不同原子运输仍可与门重叠。相同门也须满足依赖、占位与硬件资源约束，不新增多 CZ 物理能力。
- 实施：统一执行门集、独立执行器审计、M4 类型兼容时间窗口、编辑/随机/示例、schema 15；旧输入中不支持的门明确拒绝，不自动改写用户电路。

## 完成内容

- 新建 [门规范](../../docs/gate_contract.md) 与 `hardware/gate_contract.py`，统一可运行门集合 H/X/Y/Z/T/CZ。domain 仍可表示历史通用门以供数学检查和错误诊断，物理 Raman backend 拒绝所有非 H/X/Y/Z/T；entangling backend 拒绝所有非 CZ，防止 CPHASE 通过低层接口伪装 CZ。
- `simulation/m4.py` 在每个原子原有稳定可用窗口上，再排除与已安排异类门脉冲相交的完整区间。H/H 可以重叠；H/X、CZ/H 的部分或完整重叠都不可接受。`operation_program.transition` 独立检查在途门类型；手工计划、Executor.submit 和恢复仍须通过完整重放。
- 同一 qubit 的依赖与 atom/trap 资源、稳定 SLM 支撑、全路径碰撞、AOD/CZ 资源约束保持。运输/交接可以与不相关原子的门操作重叠，单比特固定 1 μs。CZ 同类兼容不等于实现多 CZ 并发，当前仍受单 AOD/单作用槽限制。
- 工作台 palette 仅六门；随机载入和维护的 `configs/workbench` 示例只生成新门集。删除可编辑 U3/旋转门参数入口，固定门仍可修改列和操作数。旧导入或旧页面发送 U3 等输入时明确拒绝并提示修改，不改变用户保存的输入。
- 四门预设改为四个 H；保持初始条件 → 编辑 → 真实编译 → Executor → recorder → viewer、失败报告与最高 32×。viewer 仍如实播放历史记录，不把旧异类并行记录重新标成新执行结果。
- checkpoint schema **15**，拒绝 1–14；同步 agent、物理/状态/执行/编译/路径规范、工作台/M4 文档与 handoff。旧日志与旧产物保留历史含义。

## 已完成验证

| 检查 | 结果与证据 |
| --- | --- |
| `python -m pytest -q tests/test_gate_contract.py tests/test_parallel_orthogonal.py tests/test_raman.py tests/test_workbench.py tests/test_m4.py --basetemp=artifacts/pytest-gate-contract-focused` | **73 passed，103.52 s**，`artifacts/gate-contract-focused.log`；包含各类同门并行、混合类型分组、跨类型冲突拒绝、旧门双层拒绝、固定时长、恢复、原路径限制 |
| `python examples/validate_gate_contract.py` | 五例符合预期，五份输入/trace/checkpoint/HTML 经不调用 compiler 的 verifier 独立重放 verified；`artifacts/gate-contract-matrix.log` |
| `node tests/m4_workbench_controls.cjs http://127.0.0.1:8767` | PASS；实际 HTTP 编辑/重编译、T 操作数修改、初态、随机/撤销/重做、导入导出、不支持门导入拒绝、预算失败弹窗/下载和恢复；`artifacts/gate-contract-editor.log` |
| `node tests/parallel_1q_controls.cjs artifacts/gate-contract/four-h/index.html` | PASS；4 个 H 在 0.5 μs 的四脉冲、标签/逐原子资源、终态与不可变录制数据 |
| `node tests/m4_controls.cjs artifacts/gate-contract/mixed/index.html` | PASS；混合线路同类型 Raman、后继释放、交接重叠与终态 |
| `node tests/playback_boundaries.cjs artifacts/gate-contract/four-h/index.html artifacts/gate-contract/h-x-groups/index.html artifacts/gate-contract/mixed/index.html` | 三例 1×/32× 完整关键帧播放与暂停续播 PASS |
| 真实内置浏览器 | 四 H 真实编译 1 μs，0.5 μs 显示四门同时执行；实际删除两 H 并放入 X 后，编译 2 μs，资源图清楚显示 H 在 0–1、X 在 1–2；随机线路 8 门/82 操作/2497.9 μs 完成编译及 32× 关键帧到终态，截图已查看 |

第一次 HTTP 控件检查与新浏览器页自动编译同时使用同一个服务，触发其“新编译取消旧编译”行为，导致检查拿到前一次 4 原子结果而预期 6。停止并行使用该服务后独立重跑全部编辑链通过；不把第一次检查记作 PASS，没有放松断言。浏览器随机线路等待控件首次超时后，实际作业仍在最终归还，随后完成；没有当作编译失败或跳过退出。

最终完整回归 `python -m pytest -q --basetemp=artifacts/pytest-gate-contract-full`：**340 passed、1 warning、780.60 s**，见 `artifacts/gate-contract-full.log`。警告为既有 dateutil utcfromtimestamp 弃用提示。

完整回归启动后，审查低层 backend 发现还应显式检查 entangling pulse 的 gate_type。补上仅 CZ 的校验及 CPHASE 伪装负例后，执行 `python -m pytest -q tests/test_gate_contract.py tests/test_milestone2.py`：**49 passed、321.09 s**，见 `artifacts/gate-contract-final-backend.log`。这项新增负例在补充检查中，不能将其算进前述 340 项。最终源码指纹在 `artifacts/gate-contract/source-sha256.json`。

最终 backend 下再次对五份矩阵记录执行独立 verifier，全部 verified，见 `artifacts/gate-contract-final-verification.log`。

## 验收矩阵

`artifacts/gate-contract/acceptance.json`：

| 案例 | 完成门数 | 总时间 μs | 实际行为 |
| --- | ---: | ---: | --- |
| four-h | 4 | 1 | 四 H 均为 0–1 |
| h-x-groups | 4 | 2 | 两 H 为 0–1，两 X 为 1–2 |
| two-layers | 8 | 2 | 四 H 后接四 T |
| mixed | 8 | 969.9 | H/H 重叠，X/T 顺序执行；所有 CZ 与 1Q 脉冲不重叠 |
| budget-failure | 5 | 484.3 | max_decisions=1，stalled，真实部分片段及失败原因 |

实际浏览器随机输入：`artifacts/workbench-gate-contract/73ba7e49fffe433989c7f46c9a68031c`；门序 H/CZ/T/X/T/H/CZ/CZ。最终留给用户的 H/X/H/X 页产物 `17c102dfd14942c9a8b17b8679feb8bb`，保留编辑能力。

## 服务、边界与下一步

8767 当前 PID **13816**，`python examples/circuit_workbench.py --port 8767 --output artifacts/workbench-gate-contract`；8766 主服务已更新 PID **17980**。重用前核实 PID/命令。新增验收 tab 14 已 markDeliverable；未刷新旧用户草稿。Windows/Python 3.12，未创建 Git 提交、未发布、未修改 memory。

这是用户指定的当前研究模型，不推论为任意实验设备规律。M3/legacy 保留原基线策略，类型约束由共享物理执行层同样执行。M4 仍为有限贪心、单 AOD 非抢占服务，不保证全局最优或所有线路可路由；未实现批量 CZ、多 AOD、测量反馈。后续 next-use/critical-path/lookahead 比较须固定本轮门集合、并行规则、半格路径和完整终态；不能继续用旧不同类型同时执行的耗时作同条件比较。

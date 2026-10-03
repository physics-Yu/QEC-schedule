# d=3 QEC/PBC 完整物理 memory 电路

本入口把 `memory_program()` 的全部任务送入项目的中性原子执行链：制备、测量纠正、r1–r3 存储纠错、九 data 的末端读出、原子归位。原生线路与原子运输计划分别导出，不把门清单当作已经物理执行的证据。

## 使用

Python ≥3.11，在项目根目录运行：

```powershell
python examples/run_qec_pbc_memory.py --basis Z --rounds 3 --seed 0
python examples/run_qec_pbc_memory.py --basis X --rounds 3 --seed 0
```

默认使用 `sparse` 策略；已有目录保留，新运行自动增加 `attemptN`。`--output` 指定产物目录，`--wall-budget` 限定执行阶段仿真电脑的耗时，不能将它与量子硬件时间混用。

## 两级 physical circuit

`physical_circuit.json` 是原生门 DAG，包含 H/X/Z/CZ/MEASURE/RESET、目标、原生测量条件和显式依赖。`compiled.json` 同时保存 QEC/PBC 协议、role→atom、测量位映射、detectors、observable 和门来源。

随后 `run_qec_sparse()` 规划真实动作；所有 accepted plans 经既有 `NeutralAtomEnv.submit/step` 执行。`schedule.json` 包含每个 trap switch、load、move、pulse、measurement、reset、offload 的绝对时间与资源；`gate_schedule.json` 把执行时刻、触发/跳过状态关联回每个原生门。时间从 accepted-plan intervals 与 committed trace 交叉核对，不在上游估算。

| 电路（r0＋3 storage） | 门槽 | CZ | H | MEASURE | RESET | 条件 X/Z |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Z memory | 416 | 96 | 160 | 41 | 73 | 46 |
| X memory | 434 | 96 | 178 | 41 | 73 | 46 |

每轮有八个 checks；总共四轮，32 个 syndrome 结果，末端再读出九 data，共41个测量结果和32个detectors。条件修正的46个分支槽全部完成一次，只有实际测量结果选择的分支施加 Raman 光；未触发的槽仍有明确1μs控制时间。MEASURE 后立即就绪的 ancilla RESET 可共享一次 MZ 往返。

## 布局与硬件约束

使用原有34原子平台。A 块的9 data 为 Q000–Q008，8 syndrome ancilla 为 Q018–Q025；其余17个原子留在 SZ，仍参与碰撞、捕获、全局 CZ 配对和量子验收。

当前本地 Enola 硬件默认 CZ 半径6μm、接近偏移4μm。旧密集工作布局的第二次 CZ 会出现额外实际 pair，八个候选方向全部被物理核拒绝。`--strategy dense` 可重现，失败记录保留；增加搜索预算不能修复非法端点。

稀疏策略将现有 A 块工作坐标间距加倍，并平移至已有 EZ 陷阱：data 为 `(20列, -100＋20行)`，check ancilla 坐标为原 check 坐标乘2，再加 `(0,-100)`。所有17个目标都是已有陷阱，没有增加平台容量或修改半径/速度/规则。逐原子 AOD 搬运在每段路径上检查活动 row×column、附带原子与支撑。读出实际进入 MZ 后返回工作位；末端逐原子归还，再恢复原 AOD pose 与 trap masks。

这是一条构造性串行基线；总时间包含初始化和最终归还，不承诺最优布局或调度。GitHub 上一次发布继承的旧硬件配置与当前本地 Enola 参数不同，不能直接比较时间。

## 验收与产物

`result.json` 只有全部机器检查成功才标记 `completed`：

- 全部原生槽完成一次，包括未触发条件槽；实际 applied IDs 与基于原生报告位的独立条件回放相同。
- 逐操作起止时间与 trace 一致，资源不重叠，所有原生依赖在后继开始前完成。
- closing round 完成、破坏性读出开始前，八个 stabilizer 和逻辑基算符均为 +1。
- 41测量和73reset projection 位完备；独立 native Clifford 回放只使用记录的分支，拒绝不可能的结果，比较全部34个带符号的 stabilizer generators。
- 32 detectors 全零、理想完美读出 decoder 的 logical parity 为0；不丢弃随机 r0 分支。
- 最终九 data 已测量且量子态与其报告位一致，八 ancilla 已复位、旁观者不变，terminal 合同成立、无 pending events。
- 从 `initial.json` 恢复独立环境，重提交全部实际 accepted plans，最终完整快照与原执行相同。

`physical_circuit.html` 显示全线路、角色绑定及可筛选的逐门表；线路横轴是门顺序，实际时间在表中。`animation.html` 使用项目共用 viewer 显示完整运输。另保存 `plans.json`、`trace.jsonl`、`checkpoint.json`、`recording.json`、`decisions.json`、`platform.json`、`working_destinations.json` 和源码/平台/协议指纹 `run_metadata.json`。这些文件均来自执行，不手改生成产物。

当前本机验收数字及失败尝试见[执行日志](../instruction/logs/2026-10-02-qec-pbc-full-memory.md)。相关测试：

```powershell
python -m pytest -q tests/test_qec_pbc_physical.py tests/test_qec_pbc_verification.py tests/test_qec_sparse.py
python tools/check_architecture.py
```

## 范围

这是完整 d=3 编码 memory 的理想量子语义、几何与时间验证。Pauli measurements 仍使用 bare ancilla；尚未证明电路级容错距离或在噪声下的逻辑错误率。Shor、magic-state 工厂、Y measurement、一般 Clifford+T→PBC 和时域 noisy decoder 仍是[架构后续阶段](qec_pbc_architecture.md)。本轮不改写 M5/M6 为完成。

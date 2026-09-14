# 状态、身份、世界与逻辑电路

2026-09-12 测量扩展优先于下方历史描述：checkpoint **schema19**；`SimulationState.quantum_state` 可选保存不可变 Clifford stabilizer 态，`measurement_results` 按 MEASURE gate ID 保存报告位；`readout_flip=true` 只翻转报告，真实投影与翻转标记在完成事件trace中独立保存，不改量子投影或RNG消耗。普通工作台仍为几何/操作模型；两块/四块QEC工作台显式启用量子态；三噪声轮后的纠正只读取已提交的报告历史。`PhysicalGate.condition`（读出位等值 AND，仅 X/Z）和 `depends_on` 与同 qubit 前驱合并为 DAG。MEASURE/RESET 经 MZ 物理操作提交，RESET 恢复 |0> 且清除 measured，均不隐含运输或原子损失。详见[量子读出合同](../docs/quantum_readout_core.md)、[协议](../docs/surface_qec_protocol.md)。

**普通模式门规则（2026-09-11，QEC读出扩展见上）**：仅 H/X/Y/Z/T/CZ 可执行；仅同类型门可并行，异类型门（含 CZ/1Q）不得重叠。内部 U 参数仅记录固定门效果。当时checkpoint schema17；当前schema19，旧输入不自动转换。详见 [门规范](../docs/gate_contract.md)。本页旧门集和任意类型并行描述以该规范为准。

用途：修改 domain/world/circuit、holder 或 checkpoint 字段时读取。相关文件见 [模块图](architecture.md)。

## 1. 真值表

| 对象 | 真值 / 派生值 |
| --- | --- |
| `Atom.id` | 同时是原子与物理比特 ID；`alive`, `measured`, `quantum_state_ref` 是元数据，当前不承载真实量子态 |
| `PlacementState.atom_to_holder` | 每个 Q 编号的唯一持有映射 |
| `static_occupancy`, `mobile_occupancy` | 从 holder 派生，只读，不再维护可独立写入的占据表 |
| `WorldState.traps/zones/bounds` | 预配置的静态几何；SLM trap 不绑定特定原子 |
| `AODRuntimeState.pose` | row=0,column=0 的连续坐标；cell 位置由 pose 与配置的行列 offsets（缺省才为固定间距）派生 |
| `DynamicGateDAG.nodes` | 逻辑门状态、剩余 predecessor 数与 successors |
| `SimulationState` | 时间、版本、队列、RNG、trace、active_plan、reservations 和 metrics 的集合 |

未来编码逻辑比特或 SWAP 编译映射若需要独立身份，应另加逻辑层，不恢复原先无意义的 A→Q 一一重复映射。实际量子信息位于原子的内部态，trap 是外部束缚位置；移动 holder 不等于换了一个物理比特。

## 2. Holder 与位置

```text
STATIC -> holder_id = SLM trap ID -> world.traps[id].position
MOBILE -> holder_id = MobileCellIndex(row,column) -> aod.position(cell)
LOST   -> holder_id = None; alive=False; position=None
```

每个 alive 原子恰好一个可用 holder；同一不可双占据 holder 不能放两个原子。不同 holder 的坐标可能在装载转移语义下重合，所以不能只靠 holder 一致性替代操作阶段的几何安全验证。

当前位置校验保证 trap 启用、AOD cell 有效、原子在世界内；`WorldState` 验证 SLM 实际 position 位于允许区域的候选网格。`StaticTrap.grid` 目前不是校验和显示的几何真值，M0/M1/M2 factory 已修正为相对 grid_origin 的真实网格坐标；外部输入仍由 position 校验，grid 不参与路径推导。

世界采用 y 向上，三区由上到下 storage / entanglement / measurement。zone 表示操作权限，不是禁止穿越的墙；隔离带可运输，但不自动允许配置 SLM trap。矩形内部不重叠，当前示例还留有间隙，避免共享边界权限含糊。

## 3. 电路与 DAG

`PhysicalCircuit` 保存输入顺序。构建 DAG 时，对每个 Q 编号记住上一个使用它的 gate，建立前后依赖。例子：

```text
G0 = CZ(Q000,Q001)
G1 = H(Q002)
G2 = CZ(Q000,Q002)
依赖：G0 -> G2，G1 -> G2
```

可发出的 ready frontier 要求 `status == READY`，而不只是 predecessor 数为零。已预约或完成的门即使 predecessor 为零也不能重复选择。

```text
BLOCKED --predecessors completed--> READY
READY -> RESERVED -> RUNNING -> COMPLETED
                    RESERVED / RUNNING -> FAILED
```

只有成功完成才递减 successors 的依赖计数。DAG 更新不得搬动原子；完成门时立即释放逻辑后继，不表示物理 AOD 周期已空闲。

`transitioned()` 返回新 DAG。纯 DAG 测试可以独立验证拓扑，但不能作为 storage 中完成物理门的证据。

## 4. 门支持程度

domain 保留通用门的数学表示，当前物理执行仅支持 H/X/Y/Z/T/CZ，规范见第 7 节。CPHASE 需要角度但物理执行仍拒绝；MEASURE 无结果/反馈语义。legacy MotionCompiler 仍为受限 CZ 基线，SingleTrapCompiler 和目标任务接口支持真实 Raman。

MEASURE 在显式 LogicalTestExecutor 测试入口仅做区域/静止校验并置 `measured=True`；没有测量结果、条件分支、重置、采样或 syndrome。测量不自动丢失原子，`measured` 与 `alive` 是不同含义。

## 5. 不可变性与提交

领域值使用 frozen dataclass，映射通过只读包装；DAG、队列和 trace 更新返回新值。Executor 构造并验证完整下一状态后安装，失败时实时状态保持不变。这个边界用于防止普通模块误写，不是防御 Python 反射的安全隔离。

`version == committed_events == len(trace)` 是事件提交不变量。`schedule()` 改变待执行队列，但不增加已提交事件版本；所以计划不仅检查 version，也检查完整 snapshot fingerprint。

## 6. 保存与恢复

schema 13 曾增加独立任务目标、操作 gate/dependency/interval 与原始 DAG；另保存参数化门、Raman 成本/资源及指标，同时保存动态 masks、交接阶段、计划起末支撑和独立开关；并保存 backend、完整行列几何、计划起始轴、路线元数据与逐操作交接 bindings（见 [AOD 后端](aod_backends.md)）；包括 world、placement、atoms、aod、circuit、DAG、pending event 的稳定序号、真实 RNG 状态、trace、硬件参数、活动 plan/cursor、资源预约与指标。JSON 编解码不执行内容、不使用 pickle；相同输入应在不同进程/hashseed 下生成一致结果。

恢复成功不能仅意味着字段可反序列化，还应保证可继续执行。M1/M2 已覆盖合法轨迹的所有事件边界，恢复时交叉检查 plan/cursor/reservation/queue/trace/placement/pose/DAG，拒绝缺失、重复、错属、错序和错时事件；详见 [BUG-002 修复](model_audit.md#bug-002)。这不是对任意人为协同伪造所有字段的密码学验证。

## 7. 参数化门契约（串行 1Q 已实现，并行待实现）

内部数学表示使用 CZ 与 U(theta,phi,lambda)，用于记录当前固定 H/X/Y/Z/T 的效果；U3 是历史输入别名，当前不可执行。角度单位 rad，顺序固定为 theta、phi、lambda，所有参数必须是有限实数。采用下式以免不同工具对 U 的相位约定混淆：

```text
U = [[cos(theta/2), -exp(i*lambda)*sin(theta/2)],
     [exp(i*phi)*sin(theta/2), exp(i*(phi+lambda))*cos(theta/2)]]
```

支持 X/Y/Z/H/S/T、Sdg/Tdg、RX/RY/RZ 输入别名并归一化；I 可作为明确的空效果，但保留依赖/映射语义。旋转定义 Rj(a)=exp(-i*a*sigma_j/2)。RZ(a) 与 U(0,0,a) 差整体相位；当前无受控 U/量子态模拟，允许在注明整体相位约定后归一化，不能用于偷换受控门。

| 输入 | 对应 U 参数 |
| --- | --- |
| X / Y / Z | (pi,0,pi) / (pi,pi/2,pi/2) / (0,0,pi) |
| H | (pi/2,0,pi) |
| S / Sdg | (0,0,pi/2) / (0,0,-pi/2) |
| T / Tdg | (0,0,pi/4) / (0,0,-pi/4) |
| RX(a) / RY(a) / RZ(a) | (a,-pi/2,pi/2) / (a,0,0) / (0,0,a) |

保留输入 gate ID、操作数顺序、原参数和归一化效果的映射；检查 arity、重复 Q、未知 Q、缺角度/多角度及 NaN/Infinity。CZ 不接受任意条件相位参数；CPHASE 不可当 CZ 别名，未显式分解则拒绝。测量/reset 另立含结果与状态效果的契约，不能归一化成 U。

1Q 的资格允许完成交接后的稳定 SLM / 静止 AOD 原子，且与任意其他存活原子间距 ≥5 μm（含 5），合法区域和 Raman 寻址资源由平台声明。U 的实际时长/资源从成本模型取得，不假设免费或无限并行。当前 PhysicalGate.parameters 保留原参数，u_parameters 给出规范效果；motion/raman.py 通过统一 program/validator/Executor 执行 RAMAN_ROTATION。Raman 时长固定 1 μs（用户确认，不作为可选项），资源已按 2026-09-11 用户纠正改为逐 qubit 的 RAMAN:Qxxx，不同 qubit 上只有同类型单比特门可同时执行，异类型门区间互斥；原参数、规范效果、trace、checkpoint schema 17 与 viewer 同步。串行恢复和混合电路见 [工作台证据](../docs/circuit_workbench.md)。

## 8. 动态状态分离（M3-A 已实现）

静态配置保留候选 SLM 点、AOD 容量、能力、运动限制和计时参数。运行状态已有 `slm_enabled`、AOD `enabled_rows/columns`，初始 AOD 默认全关；占据仍从唯一 holder 派生。活动交点等于行列启用的 Cartesian 积，空阱也属于几何检查对象。容量轴存在但可全部关闭，不通过删除/重建轴改变 cell ID。

交接中的源/目的、时间区间、支撑阶段和完成后的 masks 已有可恢复记录（见 [动态光阱](../docs/dynamic_traps.md)）；holder 在完成事件提交。普通空闲状态的 holder 必须指向活动 trap；进行中的转移允许重叠支撑，但不允许双 holder 或无支撑。开关不是 observer 层的显示参数。

M3-B 已实现 TaskIntent/TaskTarget、零门运输与 prepare/effect/cleanup 拆分；任务保存原始 DAG，恢复时检查零门不改变逻辑、效果恰好一次。见 [任务 API](../docs/task_program.md)。M3-C 已建立单 trap 声明平台族的持久构造与退出；M3-D 的 scheduled program 保存全部在途操作/轨迹、分资源预约、待发生事件和一次性的 gate 效果，见 [M3](../docs/milestone3.md)。更广状态/障碍仍受有限路由约束。不同操作写入的字段要合并到最新状态并统一验证，不能安装旧候选的整份 predicted snapshot 覆盖其他操作结果。详见 [目标契约](compiler_contract.md)。

当前 checkpoint schema 为 14；1–13 均需从原始输入重编译，逐 qubit Raman 资源语义不使用旧全局通道的在途快照。

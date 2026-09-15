# QEC GHZ：有序行列贪心与 SMT 对照

本轮把完整两逻辑 surface-code GHZ 协议接入 ROUTES V2，而不是把物理原子 GHZ 当作逻辑纠错示例。交付入口、最终测量数据及本轮测试结果见 `instruction/handoff.md` 和对应日志。

## 分层与共同实验合同

- **协议层**：复用 `experiments/surface_qec.py` 的两块 rotated [[9,1,3]]。18 个数据原子、16 个稳定子辅助原子；先测量制备，9 个 transversal CNOT，注入 Q013 的 Y 数据故障，最后测量与条件 Pauli 恢复。当前生成器实际输出 **483 个门与控制槽**：105 CZ、129 H、184 条件 X/Z、1 Y、32 MEASURE、32 RESET。条件不满足时不会实际打光。
- **控制层**：`experiments/qec_ordered_comparison.py` 保留调用者的完整 DAG、门 ID、经典条件和显式依赖。双方共用初始 SZ→EZ、同类型 Raman 服务、MZ 测量/复位/返回、最终归还。每批 CZ 恢复原 SLM，因此策略不获得不同的驻留权限。
- **批次策略层**：`scheduling/ordered_greedy.py` 的有限 beam 与新 `scheduling/smt_ordered.py` 互换；二者只在当前 READY CZ 的选择、操作数角色和配对落点上不同。
- **移动层**：共用 `ordered_routes.py` / `realize_batch`；`motion/ordered_transfer.py` 执行有序行列 SLM 交接。2.5 μm 离散网格只把 SLM 原子的占据位置标为障碍，绝不因此关闭承载原子的支撑。所有活动交点，包括空交点，仍接受连续轨迹校验。
- **环境层**：`neutral_atom_env` 继续独占物理验证、时间推进、量子效应与真实提交。本轮没有改变物理硬约束或 checkpoint schema。

共同布局使用已有两个二维 patch，SLM 基础网格 5 μm、数据间距 10 μm；单台 7×14=98 容量的 row_column AOD。初始非均匀列偏移和行偏移沿用 QEC 平台。四邻停驻保护沿用用户之前允许该 QEC 示例关闭的设置；其余碰撞、支撑、轴序、作用对及 Raman 条件保持。两者完整初态 SHA256 必须相同。

### SMT 实际求解的约束

每个 READY CZ 有 8 种符号选项：两种移动/静止角色 × 上下左右 2 μm 配对。求解器同时决定选哪些门和使用哪些选项；它不消费贪心 beam 的候选。

约束包括门互斥、操作数互斥、共享行列目标相同、轴序与最小间距、行列容量、完整笛卡尔捕获闭包，以及端点实际作用对恰好等于所选门对。第一目标为最大当前门数，第二目标为最小最大 Manhattan 位移估计。最终轴边界、源支撑、全部连续扫掠、时间参数、完整程序仍由共同 realizer/backend 审核。被拒模型完整记录，继续排除该精确模型后求解；`unknown` 与有限模型/路线预算耗尽明确区分，不称为物理无解。

这不是 OLSQ-DPQA 的完整复现，不是整个 483 槽电路的多阶段 SMT，也没有证明最小物理总时间。贪心在有限候选内比较实际本批时长；SMT 的几何次级目标没有包括空载轴重定位和完整往返时间。因此相同批次数下，SMT 也可能更慢。

### 交接处去掉人为折返

首轮沿用了“离开段和接近段必须分开”的策略约定，运输到关闭的空 SLM 时仍会越过目的地再折返。该约定不是现有物理环境的要求：关闭的目的 SLM 不需接近豁免，AOD 可经合法直线到达，再在 OFFLOAD 中建立目标支撑。

修正后，直达路线可使用一个明确的 departure MOVE；OFFLOAD 保持完整支撑交接、100 μs 时长及所有校验。转弯或任一轴反向仍有零速停点。未扩展 transfer phase 或放宽排斥条件。首轮产物保留在 `artifacts/qec-ordered/attempt1`，修正后重新运行双方在 `attempt2-direct-transfer`。

## 验收与数据

最终完整结果：`http://127.0.0.1:8796/`，产物在 `artifacts/qec-ordered/attempt2-direct-transfer/qec_ghz2/`。

| 指标 | 有序行列贪心 | SMT 最大当前批次 |
|---|---:|---:|
| 物理总时间 / μs | 32017.275973 | 32322.576528 |
| CZ 批次 / 最大并行 | 17 / 9 | 17 / 9 |
| AOD 移动时间 / μs | 20173.175973 | 20478.476528 |
| 移动段数 | 260 | 265 |
| 原子累计路程 / μm | 16550 | 16562 |
| 原子次装载 / 卸载 | 237 / 237 | 237 / 237 |
| 实际 LOAD / OFFLOAD 操作数 | 35 / 35 | 35 / 35 |
| 编译执行墙钟 / s（共享主机） | 382.200 | 116.964 |
| 独立重放 / s | 79.220 | 89.196 |
| 完整物理 / 量子 / 重放验收 | PASS | PASS |

双方 CZ 批次均为 `8,8,4,4,8,8,4,4,9,8,8,4,4,8,8,4,4`。`QEC0302…QEC0310` 是横向 CNOT 的9个 CZ，实际处于同一个脉冲。相同初态、483槽恰好一次、终态归还、32测量/32复位的协议完整性、16码稳定子及逻辑XX/ZZ均通过；每策略66计划独立重放checkpoint逐字一致。两份导出计划的非正交移动和多余同向直线停点计数都为0。

本例 **SMT 没有超越贪心并行度，物理总时间反而增加 305.301 μs（0.954%）**。差额全部属于 AOD 运输，装卸、Raman、CZ、测量和复位总时间相同。这支持把下一轮优化重点从“继续扩大当前批次搜索”转向完整运输代价和跨批次状态，但不构成任意电路上贪心达到SMT水平的结论。

本轮 SMT 建模2.243s、求解0.236s；编译执行总计116.964s，其中共同计划构造/校验计时32.368s（含求解），执行与记录80.781s。**求解器不是这个案例的主要耗时源**。贪心候选会重复实际计划构造和验证，且其运行与首轮重放重叠；不要把382s/117s之比直接解释成隔离条件下SMT加速倍数。下一步应补细分剖析、字节等价的状态/审计复用，再评估更完整的路线成本次级目标。

每个策略生成 input / plans / trace / initial / checkpoint / recording / animation / result，以及每原子的距离、装卸、门数和等待时间 JSON/CSV。

1. 实际 Executor 完成全部门槽且恰好一次；实际条件门次数单独统计。
2. 34 个原子回到初始 holder，AOD 和 trap 开关满足共同终态。
3. 从初始 checkpoint 重新提交全部计划，独立重放的完整 checkpoint 逐字一致。
4. 32 次真实测量与32复位，完整稳定子协议核验；逻辑 XX/ZZ 与16码稳定子都为 +1。
5. `examples/analyze_qec_ordered_experiment.py` 从已导出的计划/记录独立汇总操作时间、装卸、路程、横向 CNOT 对应 CZ 批次和轨迹方向。
6. 实际 GUI 中编辑、编译及回放；线路 JSON 不丢弃条件和依赖。编辑后的电路即使物理执行成功，也单独显示是否仍通过 GHZ/完整协议验证。

编译墙钟含规划、验证、执行和记录，不含导入/独立重放/导出。实验是在共享开发机上运行，期间存在其他检查与上一轮重放，墙钟数值应视为诊断测量，不能当作隔离环境的编译器性能排名。物理总时间来自相同硬件模型，不受主机负载影响。

```powershell
C:/python312/python.exe examples/run_qec_ordered_experiment.py --output artifacts/qec-ordered/new-attempt
C:/python312/python.exe examples/analyze_qec_ordered_experiment.py artifacts/qec-ordered/new-attempt/qec_ghz2
C:/python312/python.exe examples/run_qec_ordered_experiment.py --serve --port 8796 --output artifacts/qec-ordered/new-attempt
```

## 保留的限制

- 完美测量下声明单数据 Pauli 恢复；不是全电路噪声容错。Clifford 跟踪不支持 T；界面明确限定 H/X/Y/Z/CZ/MEASURE/RESET。
- 固定这套 34 原子平台可编辑电路，未声称任意新布局都可路由；输入可合法而有限搜索仍失败。
- 轴映射以源坐标排序，剩余轴采用共同的固定延伸构造；没有搜索全部空轴摆放方式。
- 2.5 μm 的 portal/corner 候选不是高维完备 A*。保持序关系只解决一部分必要条件，不能替代连续物理验证。
- 每批归还限制了跨门驻留和测量行程的优化空间；该限制对双方相同。
- 本轮没有替换生产工作台的默认编译器，没有实施 RL 或全电路多阶段 SMT。

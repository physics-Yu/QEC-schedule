# 逐原子执行统计

2026-09-14：独立模块 `neutral_atom_env.statistics` 已实现。它从 Executor 已提交的执行记录派生统计，不在 Atom 内增加可变计数，不依赖具体编译策略，也不改变 checkpoint schema19、物理校验或调度决策。

## 统计口径

| 每原子字段 | 定义 |
| --- | --- |
| `distance_um` | 该原子实际移动的累计路程，单位 μm；按所占 AOD 行列交点分别计算，每段路程相加，包含附带捕获与回程。空载 AOD 移动不计入任何原子。 |
| `load_count` | 完成的 LOAD + RECAPTURE 次数。批量抓取中的每个原子各加一次。 |
| `offload_count` | 完成的 OFFLOAD + PARK 次数。局部装卸只影响实际绑定的原子。 |
| `gate_counts` | 按门类型分别计实际完成次数；H/X/Y/Z/T/CZ，QEC 另含 MEASURE/RESET。CZ 的两个参与原子各加一次；未触发的条件槽不算打光。 |
| `busy_time_us` | 该原子的实际移动、装卸、已触发门/测量/复位区间的并集长度。 |
| `waiting_time_us` | 运行起点至最新提交时间减去上述忙碌区间并集。静止持有、等待伙伴/依赖、未触发的控制槽均属于等待。 |

相同类型门并行时，各原子分别记门数和各自的忙碌时间，不平分一束光的时长。一次 AOD 操作中某交点位置不变，该原子不计移动忙碌时间。SLM/AOD 保持支撑和硬件资源预约不自动算原子忙碌；本字段不是退相干时间或保真度估计。跨原子的等待时间之和单位为 atom·μs，不能当作程序总时长。

时间区间先取并集，避免并发重叠被重复扣除。距离按实际轴坐标计算，不能用整批平均距离代替；当前 linear/cubic 后端各段采用共同插值参数，因此该交点的分段轨迹长度为自身端点距离。未来若引入非共同参数或弯曲轨迹，需要扩展这里的轨迹积分。

门数与装卸次数在 `operation_completed` 才提交。统计中途停止时，仅累计已观察的运动与忙碌时长；三次插值采用 `u²(3−2u)`。`pending_operations` 明示尚未完成操作，不能把预定的未来门记成已执行。

## 使用与导出

```python
from neutral_atom_env.statistics import AtomStatistics, summarize_atoms, write_atom_statistics

# 任意已提交状态，包括从完整 checkpoint 恢复的状态。
report = summarize_atoms(state)
write_atom_statistics(report, "artifacts/my-run")

# 需要持续观察时：初始化重建一次，此后仅处理新增记录。
stats = AtomStatistics.from_state(state)
stats.observe(state)  # 可接在 Executor/scheduler 的提交后观察回调
report = stats.report()
```

`AtomStatistics(atom_ids, gates)` + `consume(record)` 可直接消费 JSONL 字符串或解码记录，不需要模拟状态、编译器或浏览器。每份统计对应一次运行；恢复时可以从完整历史重建，回退或分叉运行应新建对象。要求从 sequence=0 开始的完整、有序、已提交 trace；重复消费、时间回退、未知事件或未知操作明确报错。它是合法执行记录的统计消费者，不替代独立物理验证器。

默认运行起点为 0 μs；`start_time_us` 仅用于原始运行的时钟起点，不是任意截取统计窗口。报告截至最新提交事件，不能传未来的 end time 外推。渲染器任意播放时刻的插值不写入这里；恢复中途 checkpoint 后，统计包含 checkpoint 内的完整执行前缀。

工作台新编译 worker 和 `examples/compile_workbench.py` 自动输出：

- `recording.json` 中的 `atom_statistics`：格式 `neutral-atom-statistics/1`，含窗口、事件数、未完成操作数和以 atom ID 索引的逐原子表。
- `atom_statistics.json`：相同的独立汇总。
- `atom_statistics.csv`：每原子一行，各实际出现的门类型单列 `gate_H`、`gate_CZ` 等；缺少的次数填 0，UTF-8 BOM 便于表格软件打开。

已有完整工作台记录无需重新编译：

```powershell
python examples/summarize_atoms.py --input artifacts/qec-roadmap/step4C-resumed-attempt3/input.json --trace artifacts/qec-roadmap/step4C-resumed-attempt3/trace.jsonl --output artifacts/atom-statistics-2026-09-14/ghz4
```

该 CLI 使用工作台的 Q000…身份约定；其他身份使用 Python API。旧运行的 recording 不自动改写，已运行的 Python 服务需重启才加载新代码。纯逻辑演示无真实物理记录，VisualRecorder 明确返回统计不可用及原因。当前交付是独立数据模块与导出，尚未增加逐原子统计 GUI；失败/取消若没有保存完整已提交 trace，也不能凭进度百分比补算统计。

## 本轮验证

- 最终 29 项专项/集成通过，覆盖真实单 trap、行列形变、附带捕获、局部 PARK/RECAPTURE、并行门、报告位条件分支、测量/复位、部分三次轨迹、checkpoint 重建一致及只读性、工作台真实六门编译和 CLI/CSV 导出。
- 现有四逻辑 GHZ 的 68 原子、8360 条完整 trace 已生成独立汇总；单次约 5.64 秒，仅为历史统计耗时，不是重新编译成绩。
- 路程合计 **62282 μm**，装载/卸载各 **853 原子次**，分别与历史路程及捕获总数一致。原全局装卸指标为 **231 批次**，两种口径保持独立。
- 按原子参与数累计：H=689、CZ=1014（507 个 CZ × 两个参与原子）、X=2、Z=3、MEASURE=160、RESET=160，与历史实际 applied-gate 审计一致；347 个未触发条件槽不计入门数。每个原子的忙碌+等待均等于 105285.60000000036 μs。
- 证据：`artifacts/atom-statistics-2026-09-14/ghz4-verification.json` 和该目录的 JSON/CSV。artifacts 按仓库规则不提交，可用上述 CLI 复现。没有重跑整份量子重放、完整编译或真实浏览器验收。

历史兼容失败及修复详见 [本轮日志](../instruction/logs/2026-09-14-atom-statistics.md)。

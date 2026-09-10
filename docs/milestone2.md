# Milestone 2 · 连续 eager 电路

实现范围：单刚性矩形 AOD、单 CZ、每个计划 RETURN_AND_OFFLOAD。所有门使用同一持续 state；静态伙伴始终不动，源原子的真实装载、运输、卸载和空载移动通过 Executor 事件提交。

## 运行与恢复

```powershell
python -m pytest -q
python examples/run_single_gate.py
python examples/run_circuit.py
node tests/replay_controls.cjs
```

M2 报告为 `artifacts/milestone2/index.html`；包含初始/最终 state、逐事件快照、所有 plans、trace、metrics、diagnostics、真实关键帧/DAG、timeline 和共享模板回放。无解场景的 PASS 指预期拒绝被验证，其执行结果仍为 stalled。

```python
from neutral_atom_env.simulation.milestone2_factory import make_circuit_state
from neutral_atom_env.simulation.scheduler import EagerScheduler
from neutral_atom_env.simulation.state import SimulationState

state = make_circuit_state('three_gate')
scheduler = EagerScheduler(state)
scheduler.step()  # 每步推进一个真实事件
saved = state.snapshot()
restored = SimulationState.restore(saved)
result = EagerScheduler(restored).run()
assert result.status == 'completed'
```

schema 5 显式拒绝 schema 1–4；旧产物请重建。physical compiler 只接受 CZ；参数化 CPHASE/RX 等与物理测量尚未实现，返回 UNSUPPORTED_GATE。M0 的 GATE_* 演示由 testing.logical_executor.LogicalTestExecutor 独立承载。

## 公开初始布局

| 原子 | 位置 μm | 初始承载 / 角色 |
| --- | --- | --- |
| Q000 (a) | (0,0) | storage S000，移动源 |
| Q001 (b) | (5,-25) | EZ S001，静态伙伴 |
| Q002 (c) | (15,-25) | EZ S002，静态伙伴 |
| Q003 (d) | (20,0) | storage S003，另一移动源 |

伙伴已在 EZ 是受限初始条件，准备成本不计入当前电路时间，也不声称已实现从全 storage 出发。所有门必须有一个静态 EZ 端和一个区外静态端；具体候选还须通过捕获、世界边界、完整路径 clearance 和全 EZ pair 校验。测试布局的 sources 位于 storage。

硬件沿用 M1 未标定运动学参数：2×3 AOD、5 μm spacing、0.5 μm/μs、LOAD/OFFLOAD 各 100 μs、pulse 0.3 μs、clearance 1 μm、作用半径 2 μm、escape 2.5 μm。新增相对作用偏移 `interaction_offset=(-2,0)` μm 取代绝对作用 pose；半径仍是独立校验参数，不能随目标或路径放宽。

## 独立时间与距离核算

三门：G000=CZ(a,b)，G001=CZ(a,c)，G002=CZ(b,d)。每个 plan 完成后源原子回到该次来源 trap，空 AOD 回到该次 plan 起始 pose。

| plan | loaded 单程 μm | 空载总程 μm | AOD 总程 μm | plan 时长 μs | pulse 完成 μs |
| --- | ---: | ---: | ---: | ---: | ---: |
| G000 | 2.5+25+0.5=28 | 0 | 56 | 100+112+0.3+100=312.3 | 156.3 |
| G001 | 2.5+2.5+10+22.5+0.5=38 | 0 | 76 | 100+152+0.3+100=352.3 | 488.6 |
| G002 | 2.5+2.5+15+22.5+0.5=43 | 40 | 126 | 80+100+172+0.3+100=452.3 | 890.9 |

G002 先空载 (0,0)→(20,0)，装载 Q003；loaded route 为 (20,0)→(17.5,0)→(17.5,-2.5)→(2.5,-2.5)→(2.5,-25)→(3,-25)，与 Q001 配对。逆路回源并卸载，然后空载 (20,0)→(0,0)。每次空载 40 μs；空载不计入原子路程。

总 wall=1116.9 μs，逻辑完成=890.9 μs，AOD 路程=258 μm，原子路程=218 μm；3 次装卸、3 个计划、3 个完成 CZ。37 个 operation、80 个事件。AOD 利用率=1，激光利用率=0.9/1116.9，吞吐=3/1116.9 gate/μs。

| 场景 | 总 wall μs | 逻辑完成 μs | AOD / atom 路程 μm |
| --- | ---: | ---: | ---: |
| repeat：ab,ab | 624.6 | 468.6 | 112 / 112 |
| switch_partner：ab,ac | 664.6 | 488.6 | 132 / 132 |
| three_gate：ab,ac,bd | 1116.9 | 890.9 | 258 / 218 |
| join：ab,dc,ac | 1076.9 | 900.9 | 238 / 198 |

join 的 dc 单程为 2.5+2.5+5+22.5+0.5=33 μm，因此该 plan 为 412.3 μs；最后 ac 等两个 predecessor 完成才 READY。它与 three_gate 的第三门路径不同，不能共用同一时间期望。

## 验收与限制

测试检查 pulse 释放 successor、cleanup 前不提交下一 plan、首个 READY 不支持时继续试后续 READY、所有事件边界恢复、损坏活动 checkpoint 拒绝、不变性、非零 episode 起点、非零 capture cell 的配对、第三计划附带捕获和 unsupported 诊断。第三计划额外捕获 Q004=(25,5) 时，AOD 路程仍为 258 μm，原子路程为 56+76+86×2=304 μm。

有限通道候选失败表示候选范围耗尽，不证明物理上无路。空 trap 光场影响、加速度、温度、损失、量子态和真实保真度没有模拟。KEEP、batch、多 AOD、任意参数电路和 RL 没有提前实现。指标详细口径见 [motion_execution](../instruction/motion_execution.md)。

当前路线与可替换接口见 [motion_planning](../instruction/motion_planning.md)。SLM 几何排斥已加入，光场与实验噪声仍未模拟。

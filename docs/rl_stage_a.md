# 隔离的 RL 阶段 A：决策接口与小电路验收

2026-09-15。实现的是训练基础，不包含神经网络、PPO更新、训练权重或学习收益。独立入口不注册到生产 strategy registry，不改变 8798 工作台。

## 隔离范围

- 新增 `src/neutral_atom_strategies/learning/`：DecisionEnv、有限物理候选、随机策略、独立局部成本基线。
- 新增 `src/neutral_atom_experiments/rl/`：小电路、并行验收与报告导出。
- 配置 `configs/rl/stage_a.json` 与输出 `artifacts/rl-stage-a/` 单独保存。
- 不导入 `neutral_atom_strategies.scheduling` 或应用，不调用、继承、修改旧 greedy。只复用纯物理核、ProgramBuilder、`axis_hold_routes`/`OccupiedSLMGrid` 路线工具。
- 相对于本轮开始时保存的哈希，150个既有 src 文件完全未变。仓库此前未提交的改动仍保留；这个结论不是声称 git 工作区干净。

## 支持范围

适配器支持2–8个初始静止SLM原子、显式 row_column / row_column_orthogonal 后端，无条件 H/X/Y/Z/T/CZ。自带4/6/8原子两行EZ小实例，使用 row_column_orthogonal、1×N AOD、默认物理参数及保持开启的EZ四邻保护。不是完整QEC、测量候选学习或任意电路可完成性证明；自带样本没有量子态跟踪，只验收真实操作、逻辑效果与物理终态。

1Q候选包含同种全批与单门。CZ枚举移动端、四个相对作用方向、同位移且无共享原子的最多4门子集，利用可配置有序轴进行捕获；源捕获闭包、全部交点、路径和全局作用对仍由真实物理后端审核。原子在每个CZ服务结束回原SLM，空AOD坐标可以跨服务保留；全部门完成后还有显式清理动作，恢复原始AOD与开关。

默认最多8个READY门、24个尝试、每候选16条路径，单次构造有30秒协作式时间预算。时间检查在候选/路线边界，不是可强杀底层校验的严格墙钟上限。记录生成、尝试、未尝试、READY遗漏、拒绝及预算耗尽。当前排序仍会限制候选覆盖，不是已完成自由合批/驻留动作空间。

## 决策与连续分段

```python
from neutral_atom_experiments.rl.instances import make_snapshot
from neutral_atom_strategies.learning import DecisionEnv, EpisodeConfig
from neutral_atom_strategies.learning.policies import RandomPolicy

initial = make_snapshot([('H', [0]), ('CZ', [0, 2]), ('X', [0])], atom_count=4)
env = DecisionEnv(initial, EpisodeConfig())
policy = RandomPolicy(seed=7)
fragment = env.collect_fragment(policy, length=2)
# fragment_cut / bootstrap_required 不等于任务结束，不自动归位或重置。
next_fragment = env.collect_fragment(policy, length=2)
```

`observe()`给出JSON安全的原子/轴、门图与后继、状态、合法候选和mask、剩余预算；模型只接收这些数据。特权 checkpoint、实际程序、RNG、tableau、trace不进入观测。规划耗时只写诊断，不混入学习观测；冻结物理输入加上未耗尽的确定性预算可复现候选。发生墙钟截断时，重建候选可能受到负载影响，需保留实际采样候选表，不以重建结果替换PPO旧样本。

`step(action_id)`执行一份完整服务，经 env.submit/run 推进到静止决策边界；输出实际时间增量、奖励、是否终止、失败及原候选表。它不是逐物理事件step，不支持操作内部并发决策。无候选由 `step(None)`显式终止失败；错误/过期ID同样失败且不提交操作。已经终止后再step属于调用错误。

`collect_fragment`仅切数据，返回最后观测与`bootstrap_required`。本轮尚不计算价值网络/GAE；训练器接入后必须处理该标志。`snapshot/restore`保存初始终态合同、现场、预算计数和累计奖励，恢复后不会把中途位置误当作最终归位位置。`RandomPolicy.state_dict/load_state_dict`单独保存采样RNG；同时恢复二者才可续接随机策略轨迹。checkpoint是可信本地实验恢复格式，不是完整的不可信上传验证接口。

## 奖励与失败

固定episode尺度默认1000μs，逐决策奖励 `-Δtime/1000`；成功累计回报严格等于从起点到含清理终点的负总时间。这个首版尺度不是逐电路baseline归一化。

默认物理上限100000μs，最大1000决策。若服务会越过物理上限，提交前拒绝。无候选、无效动作、物理验证错误或决策预算耗尽，累计总回报设置为 `-time_limit/scale-1`，终止奖励补足差值，保证失败不能优于预算内成功。

片段长度不使用这些失败规则：片段结束仍是running，`terminated=False`、`truncated=False`、`fragment_cut=True`。没有免费归还、免费清理、空等动作或切段后把未来代价置零。

## 重现

在已安装项目的仓库根目录：

```powershell
C:/python312/python.exe -m pytest tests/test_rl_stage_a.py tests/test_environment_boundary.py -q
C:/python312/python.exe tools/check_architecture.py
C:/python312/python.exe -m neutral_atom_experiments.rl.evaluate --workers 2 --output artifacts/rl-stage-a/acceptance-final
```

未安装项目时先按仓库README安装；本实验无额外Torch/Gym/Z3依赖。每个worker使用独立env和seed，不共享可变状态。`--cases parallel_h parallel_cz`可缩小验收集。`--config`支持独立JSON配置，`--workers`只改变采样并行度。

输出含 `report.json`、可读 `index.html`，每例的输入、片段/候选、程序、checkpoint和结果。8原子局部成本基线额外导出共用viewer动画，来自相同真实程序的独立物理重放。GUI没有改动，未进行本轮真实浏览器交互验收。

## 本轮检查与后续

29项适配器/环境边界测试通过，覆盖同种并行/异种分开、时间奖励、片段续接、AOD最终清理、恢复与随机RNG、失败不获利、预算披露和独立性。146模块架构检查零违规。完整最终实验结果见 `artifacts/rl-stage-a/acceptance-final/report.json`；历史首次运行保留在attempt1，不覆盖失败或旧证据。

最终2进程、6类小电路×2策略×2 seed 共24/24完成，所有终态、逐门效果恰好一次、独立物理重放通过。4个H全批1μs，逐个基线4μs；8原子seed0局部成本基线真实4对CZ同脉冲，含准备与最终清理847.324143μs，随机对照1771.264138μs。这是未训练基线的比较，不是RL收益或与生产greedy的比较。

整套验收96.128秒，端到端约1.228决策/秒、0.250 episode/秒，包含独立重放及导出，不是纯训练吞吐。各worker累计候选构造/校验157.455秒、执行15.855秒（进程累计时间不能当作墙钟相加），规划约占这两类时间的90.85%。实测说明先降低候选生成/校验开销比盲目增加网络规模更有价值；并行加速比尚未做受控测量。

下一步先分析候选实现成本与动作覆盖，再接小规模价值/策略网络，比较学习效果与同动作空间局部成本基线。扩大动作空间、添加测量/驻留和操作重叠属于后续阶段，不把本次合批基线的优势记作学习收益。

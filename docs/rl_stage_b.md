# RL 第二步：小规模真实训练与性能反馈

2026-09-15。训练链路与执行验收完成；稳定优于局部成本基线、解决指定长程反例的性能目标尚未通过。正式结果在 `artifacts/rl-stage-b/attempt2-normalized-validation/`，旧greedy、阶段A源码、8798工作台均未修改。

## 本轮实现

新增独立模块：

- `strategies/learning/network.py`：10,594参数图actor/critic、两轮门依赖消息传递、候选屏蔽、PPO clipped objective、gamma=1的GAE、可加载的NeuralPolicy。
- `strategies/learning/cache.py`：128项LRU，以完整环境checkpoint、终态和生成配置的SHA256为键复用已验证候选；不缓存墙钟超时结果，实际提交仍经过Executor验证。
- `experiments/rl/training_cases.py`：显式互斥的训练/验证/测试清单；独立小规模1Q最少脉冲动态规划参照。
- `experiments/rl/train.py`：模仿预训练、同步多进程on-policy片段采样、PPO更新、验证集选模、独立物理重放和报告。
- `experiments/rl/analysis.py`、`diagnose.py`、`acceptance.py`：全种子汇总、训练结束后的反例物理核查及单独性能验收状态。

无生产策略注册、无物理模型修改、无新的GUI编译入口。复用阶段A有限合法候选，因此当前仍是候选选择学习；没有自由生成新批次、测量策略学习、跨批次驻留或操作内部并发。网络使用稠密小图邻接矩阵，只面向本轮小电路，不能直接当作长电路可扩展实现。

## 实验条件

| 项目 | 本轮配置 |
| --- | --- |
| 训练 / 验证 / 测试 | 13 / 4 / 9条，输入指纹不重复 |
| 训练内容 | 12条H/X短wire序列＋4原子CZ合批 |
| 测试内容 | 未见短序列、较长反例、Y/Z门、6原子wire、8原子CZ与交叉CZ依赖 |
| 训练seed | 11、29，两者都报告 |
| 模仿预训练 | 独立local_cost教师，55决策，20 epoch |
| PPO | 每seed24次更新、每次4个采样槽、片段最多4决策、4优化epoch |
| 时长目标 | gamma=1；真实全局时间增量；1Q样本按1μs、含CZ样本按1000μs归一化 |
| 选模 | 验证集平均负归一化回报最小，模仿模型作为update0候选 |
| 计算 | CPU、2工作进程、每进程Torch单线程 |

只有12条训练wire、2个训练seed，这是先导实验，不构成对任意电路泛化或统计优势的证明。测试数据不用于梯度更新、模型选择或超参数调整；第一次实验后的代码复核修正了验证评分单位不一致，按相同配置完整重跑。既有测试集已用于此次研究，后续调参后应另冻结新的测试集。

片段不重置现场；本轮90个片段边界需要bootstrap，GAE使用边界价值估计。真正完成/失败时bootstrap为0。采样中保存原观测、候选/mask、所选index和旧log probability；优化不重新生成候选，不借用未来测量/隐藏量子态。

## 结果

正式尝试耗时208.570秒（含预训练、验证、测试、物理重放及导出）；PPO合计615个实际采样决策，训练失败0。9测试×6策略×2种子共108次，全部完成、终态正确、门效果恰好一次、独立重放一致。

| 策略 | 平均负归一化回报，越低越好 | 逐电路耗时比平均，local_cost=1 |
| --- | ---: | ---: |
| 未训练网络 | 5.353074 | 1.481205 |
| 模仿预训练 | 3.722943 | 1.022222 |
| PPO最后模型 | 3.611832 | 0.997222 |
| 验证集选中模型 | 3.611832 | 0.997222 |
| 独立local_cost | 3.611832 | 1.000000 |
| 随机策略 | 5.994845 | 1.770776 |

两个指标的加权方式不同，0.997222不能当作训练主目标已改善。主目标总体与local_cost打平。Seed11选中update0，仍是模仿模型；seed29选中update16，其两个测试案例从6→5μs、5→4μs，说明部分PPO改进确实发生，但不能只挑该seed宣称稳定胜出。

在8原子CZ测试中，模仿与PPO均实际实现4对CZ同脉冲，含准备和最终清理847.324143μs，与local_cost相同。这个并行能力已存在于共同候选空间，网络学会选择它；不能记作RL创造了新的硬件自由度。

缓存命中159次、未命中546次（训练采样阶段），所有缓存键依赖完整状态。没有进行同等工作量的缓存开关性能消融，因此不声称相对阶段A有确定倍数加速。

## 未通过项与原因

`acceptance.json`明确区分：执行PASS；`better_than_baseline_in_every_seed=false`；`nonlocal_counterexample_solved=false`；性能优势`NOT_ESTABLISHED`。

已做两个独立动态规划＋真实Executor反例核查，16次模型/参照执行全部重放一致：

| 反例 | 真实可执行最优 | local_cost | 两seed模仿/最终/选中网络 |
| --- | ---: | ---: | ---: |
| 训练集train-words-2 | 3μs | 4μs | 4μs |
| 测试集test-greedy-trap | 6μs | 7μs | 7μs |

这两个更优解已在现有候选空间中实现，故不能将差距归咎于本例没有合法动作。可以确认教师在训练反例中也提供了次优行为，而本次PPO没有纠正它。615决策的小预算、局部模仿偏置、片段价值估计和探索不足是需要消融验证的原因；尚未用实验证明某一项是唯一原因。

下一轮应建立新的训练/验证反例族，比较无模仿/弱模仿、片段长度与探索强度；评估价值估计是否能区分“当前多做一步，后面少做两步”。现有反例作为诊断集保留，另冻结新测试集。不要直接扩展到长GHZ并把执行成功当作性能通过。

## 环境与复现

主解释器已有Torch2.2.2+cpu和NumPy2.5.3存在桥接兼容警告。用独立 `.venv-rl-stage-b`（继承只读系统site-packages）安装本地NumPy1.26.4覆盖，原环境未被卸载/升级。该venv不用于SciPy；继承的SciPy版本要求NumPy2，与此实验venv不兼容。实际训练只使用Torch/Python，已验证，不把此venv推荐为全项目运行环境。

```powershell
C:/python312/python.exe -m venv --system-site-packages .venv-rl-stage-b
.venv-rl-stage-b/Scripts/python.exe -m pip install numpy==1.26.4
.venv-rl-stage-b/Scripts/python.exe -m pytest tests/test_rl_stage_b.py tests/test_rl_stage_a.py tests/test_environment_boundary.py -q
.venv-rl-stage-b/Scripts/python.exe -m neutral_atom_experiments.rl.train --output artifacts/rl-stage-b/new-attempt
.venv-rl-stage-b/Scripts/python.exe -m neutral_atom_experiments.rl.diagnose artifacts/rl-stage-b/new-attempt
.venv-rl-stage-b/Scripts/python.exe -m neutral_atom_experiments.rl.acceptance artifacts/rl-stage-b/new-attempt
```

在没有系统Torch的机器上，将 `configs/rl/requirements-stage-b.txt` 安装到独立venv并按README安装项目。配置在 `configs/rl/stage_b.json`。输出目录存在status文件时拒绝覆盖；保留attempt1原始单位评分结果和attempt2修正结果。

模型文件：`seed-*/untrained.pt`、`imitation.pt`、`last.pt`、`selected.pt`。包含网络结构参数、权重与选择信息；它们是推断权重，不是完整优化器/训练器恢复文件。阶段A的物理checkpoint/RNG续接合同继续保留。

加载后通过原独立adapter执行：

```python
from neutral_atom_strategies.learning.network import NeuralPolicy
policy = NeuralPolicy.load('artifacts/rl-stage-b/attempt2-normalized-validation/seed-29/selected.pt')
# env 是由支持范围内自定义电路建立的 DecisionEnv。
while env.status == 'running':
    fragment = env.collect_fragment(policy, length=4)
assert env.audit()['replay_equal']
```

报告入口 `artifacts/rl-stage-b/attempt2-normalized-validation/index.html`，包含全测试明细与各seed的8原子共用viewer动画。模型每次选择的真实候选与程序在各evaluation子目录；没有手改轨迹或替代物理动画。未做本轮真实GUI交互验收。

## 算法来源

- [PPO原论文](https://arxiv.org/abs/1707.06347)：采用其clipped policy objective，并保存采样旧概率；本实现是小规模定制训练器。
- [GAE原论文](https://arxiv.org/abs/1506.02438)：采用优势估计/价值bootstrap；本项目有限时长目标使用gamma=1，lambda=.95。

隔离审计：本轮开始时157个既有src文件逐字哈希未变，包括所有旧greedy、环境、应用和阶段A源文件。新模块不自动导入Torch或注册到旧工作台；仅显式调用学习模块时使用训练依赖。

最终37项学习/阶段A/环境边界测试通过，153模块架构检查零违规。模型重新加载到独立自定义H/Y/CZ/Z线路，849.324143μs，物理重放、逐门效果与终态通过；证据`custom-circuit-load-test.json`。

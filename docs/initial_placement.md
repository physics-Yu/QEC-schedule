# 初态放置：独立算法、接口与非可视化验收

2026-09-21最新：[给定 layout 后的通用初态优化](compiler_initial_placement.md)新增实际编译反馈搜索，不再只复评固定代理短名单。支持用户原映射、自由交换、显式空位/锁定和共同绝对终态；本页下文描述的快速静态代理保留，不能代替新接口的完整时间目标。

2026-09-21后续：[surface-code GHZ完整对照](surface_initial_placement.md)已完成。两组量子/物理/重放均通过，但靠近EZ的保形候选因空AOD对位反而慢0.1919%，物理复评保留原布局。不能把以下小CZ实例的加速直接外推到QEC。

2026-09-21。此轮只做初态放置与机器验收，不修改工作台、Parking 分享页或共用 viewer。环境与物理硬约束未改。初态放置是 physical qubit ID 到 SLM 的单射，不改变电路、逻辑编码、门 ID 或依赖。

## 模块归属

`src/neutral_atom_strategies/placement/`：

| 文件 | 职责 |
| --- | --- |
| `models.py` | Site、PlacementProblem、SearchConfig、CostEstimate、PlacementCandidate/Result、LandingProposal、PhysicalEvaluation 等统一数据合同 |
| `cost.py` | 从完整 DAG 导出预测层；运动/兼容抓取代理；门对与图案缓存 |
| `initial.py` | 平移种子、有限模拟退火、小规模精确枚举；物理复评候选选择 |
| `dynamic.py` | DynamicPlacementPolicy 接口和 FixedReturnPolicy 固定归还基线 |

动态自适应落点的新算法尚未实现；现有 ZAC 动态 placement 仍是独立适配，未自动替换为这个接口。`LandingProposal` 是目标提案，不是已经验证可达的计划。`FixedReturnPolicy` 不会直接修改状态，也不隐含处理目的地占用。

应用入口 `neutral_atom_app.placement` 负责自定义 JSON 和已有 Platform 适配；实验在 `neutral_atom_experiments.initial_placement`。策略不导入 app/experiments，不向环境塞回优化算法。

## 搜索方法

1. 校验所有 qubit（包括闲置原子）、SLM 单射、锁定位置、支持门集、AOD 容量参数与搜索预算。
2. 使用完整 `DynamicGateDAG` 依赖，包括 1Q、MEASURE、RESET、显式依赖和测量反馈；从中提取含 CZ 的预测层。这里的 ASAP 层只是估计输入，不是最终物理调度。
3. 原映射始终保留。无锁定时补入合法整体平移作为种子，避免单原子迁移把原有共同运输对拆散后难以越过评分障碍。
4. 模拟退火混合单原子换位/移到空位、整行/整列互换；锁定位置不能变化。整行/列是布局搜索操作，不是已经发生的 AOD 运动。
5. 保存前 top_k 个代理候选，加上原映射作为独立保底。有限预算退出；无 CZ 或全部锁定时保留输入。`exact_limit` 非零且整个单射空间不超过限额时，穷举得到此代理的全局最优，而非物理最优。
6. 可调用 `select_physically` 对全部短名单和基线分别完整执行/重放，只在通过的候选中按实际总时间选择；异常、失败与证据路径均返回。全部失败返回 `None`，不会把代理结果冒充可执行。

可复现参数：seed、iterations、top_k、lookahead_layers、decay、objective、exact_limit。默认 iterations=1000、seed=7、top_k=3、lookahead_layers=8、decay=0.8。top_k 之外另保留基线，物理评估最多 top_k+1 份。

## 代价的精确定义与边界

默认 `parking_aware`：

`score = sum(decay^layer × (pair_transport_proxy + capture_batches × (load_us + offload_us)))`。

- `pair_transport_proxy`：每个 CZ 对到最近共同 EZ 参考点的往返代理；同源行取两原子时间最大值，否则求和。正交两段时间按本项目 cubic 的速度、加速度、jerk 上限计算；各 CZ 对的代理求和。
- 因为这里同源行并行的规则针对水平配对参考，且忽略 EZ 站点竞争、2 μm 精确配对端点和共享轴目标冲突，它不是任意几何最短路、完整执行时间或下界。最终门配对与路径由实际编译器决定。
- `capture_batches`：规则源坐标、最多 16 行/列且本次目标所需轴数不超过 AOD 容量时，复用 Parking 全组冲突图，比较按行和按列的最少兼容抓取组。空位 wildcard；闲置原子为固定占据；无目标行列跳过。这里只证明源抓取图案兼容，不证明停车扫掠或目的地运输可行。
- 不符合上述模式时标为 `singleton_proxy`，按目标数估计；不把有限模板不适用说成物理不可行。
- `distance` 是消融对照：相同运动代理、搜索与预算，不把抓取项加入评分；并非原论文逐行复现。
- 每层仍使用初始映射，远期通过 decay 衰减。1Q/测量/复位/反馈的布局成本尚未计入，输出 `unscored_operations`，但不删除这些门或依赖。
- 空载 AOD 定位、精确卸载/再次装载、避障、目的地竞争、终态恢复不在代理中完整计费。因此输出 `status=estimated`、`physical_validation=not_run`；只有外部物理执行能报告实际 μs。
- 当前成本模型要求 `row_column_orthogonal` 后端；不向 rigid 平台输出假装同等有效的代价。坐标唯一/单射校验不能替代物理 clearance 校验。

门对代价按源站点对缓存，兼容分组按三色 mask 缓存。每次布局仍扫描前瞻层、建立受影响图案；当前没有宣称完全增量 delta 评分。整体平移种子最多扫描存储站点数；后续评分次数受迭代预算约束。兼容分组的精确着色在最坏情况下仍有指数复杂度，限于最多16条源轴；小规模映射穷举同样显式限额。没有每次扰动就调用完整 Executor。

## 自定义线路与平台接口

无需打开任何网页，使用 `configs/placement/initial-eight.json` 修改：

- `qubits`：所有原子 ID，含闲置原子。
- `gates`：完整 PhysicalGate 数组，支持 H/X/Y/Z/T/CZ/MEASURE/RESET 的布局输入。
- `storage`：候选站点 ID 和绝对 x/y μm；`interaction_sites` 是 EZ 代价参考点。
- `initial_mapping`：完整基线；`locked`：需要保持的初始位置。
- `aod.rows/columns` 与 `search`：平台容量及优化设置。

```powershell
python examples/compile_initial_layout.py --input configs/placement/initial-eight.json --output artifacts/initial-placement/custom-layout.json
```

输出包含完整原电路、circuit_sha256、候选映射、逐层估计分解、种子和预算、原输入及适用限制。无效输入写结构化失败报告并返回非零退出码。它生成的是布局，不执行电路。

已有 Platform 可直接调用：

```python
from neutral_atom_app.placement import compile_platform_layout
from neutral_atom_strategies.placement import SearchConfig
from neutral_atom_env import NeutralAtomEnv

result = compile_platform_layout(circuit, platform, initial_mapping,
    locked={"Q000": initial_mapping["Q000"]}, config=SearchConfig(seed=7))
env = NeutralAtomEnv.create(circuit, platform, dict(result.selected.mapping))
# 然后交给既有控制程序；物理可执行性仍由环境验证。
```

该适配器只使用平台已有的、初态开启的 SZ SLM，不改变几何和 switches；扩大可选初始站点应显式修改初始平台配置。包含 QEC 时，原有量子态初始化步骤仍由相应应用负责。锁定只约束初态搜索，不代表运行时永不移动。

准备好的不同初态默认不收取组装时间。不得把结果直接安装到已经装载或正在执行的环境；从相同已加载阵列重排必须额外生成真实运输并计时。

## 非可视化验收结果

51 项测试通过：`test_initial_placement.py`、`test_environment_boundary.py`、`test_parking_compatibility.py`、`test_zac_reuse.py`。包括独立小规模穷举评分预期、确定性与锁定、空位与列方向胜出、无 CZ 不移动、预算/非法输入、依赖/反馈保持、代理候选失败回退、已有 Platform 的 H→CZ→T 完整执行与独立重放。依赖方向审计通过，177 个 Python 模块。

以下是10×10 SLM 格点上的**真实 CZ 编译/执行**；同一线路、硬件、作者动态放置算法、运输器和明确的共同终态，reuse 关闭，只改变准备好的初态映射。候选不是动画坐标改写。

| 电路 | 原布局总时间 μs | 选中布局总时间 μs | 减少 | LOAD 批数 | 原子总路程 μm |
| --- | ---: | ---: | ---: | --- | --- |
| 4 原子 / 3 CZ | 4970.426391 | 4494.499962 | 9.575% | 7 → 7 | 1308 → 948 |
| 8 原子 / 12 CZ | 18998.209060 | 16894.475105 | 11.073% | 24 → 22 | 4331 → 3587 |

正式5份执行均通过门效果恰好一次、终态校验和全 snapshot 独立重放；额外审计确认相同电路、硬件、几何、最终 holder、SLM masks 与 AOD 配置。逐原子路程、装卸、门次数、等待时间输出 JSON/CSV，并与总路程交叉核对。

**保留的负收益候选：** 八原子候选1代理分数5650.104小于原布局9995.929，但真实时间20011.736 μs，大于原布局18998.209 μs；LOAD批数26，高于基线24。物理复评选择了更好的候选0，没有将代理排序直接当作胜利。

以上收益以近 EZ 初态平移为主，不能归因于兼容分组评分。为单独检查抓取项，补充满占据10×10、100原子/32当轮目标的布局压力测试：seed 7/19/41，distance 对照抓取组数为9/9/8，parking_aware为8/6/7，原布局为10。1000次搜索耗时0.57–0.66秒左右；**这是图案/代理结果，没有完成100原子物理电路验收**。八原子1000次搜索约0.19–0.34秒；这些时间不包含完整物理编译与重放。

首次物理尝试 `artifacts/initial-placement/four/` 失败于 `AXIS_BOUNDS`：实验把10×10 SLM误当成10×10 AOD，备用轴超出视场。修复实验容量定义，并显式计入备用轴视场空间；没有改变环境的轴间距、碰撞或支撑规则。旧失败目录保留，最终四原子结果在 `four-final/`。

## 复现与证据

```powershell
python -m pytest tests/test_initial_placement.py tests/test_environment_boundary.py tests/test_parking_compatibility.py tests/test_zac_reuse.py -q
python tools/check_architecture.py --output artifacts/initial-placement/architecture.json
python tools/check_initial_placement_algorithm.py
python examples/check_initial_placement.py --input configs/placement/cz-eight.json --output artifacts/initial-placement/eight-new --iterations 1000 --top-k 2
python tools/audit_initial_placement.py
```

物理对照使用此前已下载的固定 ZAC 源码与其可用依赖；安装/来源见 `docs/zac_reuse.md`。纯布局搜索与 JSON API 只依赖项目本身，不需要 ZAC、SciPy 或浏览器。

- `artifacts/initial-placement/pytest.xml`：本轮51项机器结果。
- `artifacts/initial-placement/acceptance.json`：共同终态和物理结果汇总。
- `four-final/`、`eight/`：完整输入、候选、作者前端输出、plans、trace、initial/checkpoint、失败候选及逐原子统计。
- `algorithm/summary.json`：12份规模/seed/目标函数对照；逐份搜索结果同目录。
- `custom-layout.json`：命令行自定义布局交付。

下一步由用户指定可视化形式。未做本轮 GUI 验收、没有替换现有工作台、没有接入新的 RL 或自适应动态落点，也未提交 GitHub。

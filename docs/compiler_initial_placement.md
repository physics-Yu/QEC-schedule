# 给定 layout 后的通用初态分配优化

**2026-09-21 后续纠正：** 用户明确不要求保持原占据几何；本页下述默认排列合同仍为兼容入口，不能代表完整自由排布。新增 `optimize_free_layout`，包含关闭的合法 SZ SLM、改变占据形状、真实编译反馈及可编辑对照工作台，见[自由初态布局验收](free_initial_placement.md)。

2026-09-21。此版本按用户纠正收敛问题：**先固定用户选择的 layout，再优化 qubit→SLM 分配是否能降低整个程序的实际时间**。不将 surface patch 整体平移作为唯一自由度，不重新生成电路，不修改物理环境。界面按要求暂不调整。

## 输入、可变项和目标

- 固定：完整 `PhysicalCircuit`（包括反馈条件和依赖）、SLM 坐标/区域/开关、AOD 能力和初态轴、编译算法及预算、量子初态/随机种子、共同绝对终态。
- 默认可变：原来已经占据的站点上，各物理 qubit 的分配。不是平移几何，也不要求规则方格或给定 patch 形状。
- 可选：`allow_vacancies=True` 时允许使用候选集合内的其他空位；`locked` 固定指定 qubit 的初始站点；`storage_ids` 缩小允许的初始 SLM 集合。这些锁定不限制电路执行中的合法运动。
- 目标：完整编译执行和共同终态恢复后的仿真时间，单位 μs。真实计算耗时另记为 wall seconds。既有数组装配/重排时间未计入，因为研究输入是准备好的初态；不能将结果安装到正在执行的 env。

写成目标即 `min_mapping T(compiler(circuit, platform, mapping, fixed_terminal))`。这不是仅最小化交互距离，也不是寻找适合所有电路的同一张布局。layout 可以作为用户指定的几何、允许站点集合和初始分配；需要保持 patch 内部位置时，可显式锁定，优化器不会按 demo 名偷偷锁定。每个 qubit 各自允许一个不同区域的 domain 约束尚未单独实现。

## 分层实现

| 入口 | 职责 |
| --- | --- |
| `strategies/placement/verified.py::optimize_with_compiler` | 通用有界黑盒搜索；只依赖 mapping 问题和外部 evaluator，不依赖 surface/GHZ/ZAC/demo 或某种路线模板 |
| `app/placement_execution.py::optimize_compiled_layout` | 将同一平台、完整电路和共同终态绑定到普通 `run_ordered`；逐候选创建独立环境、完整执行和独立重放 |
| `scheduling/ordered_controller.py::run_ordered(..., terminal_target=...)` | 新增可选显式终态；未传入时保留原有“返回自身初态”行为 |
| `app/placement.py::platform_placement_problem` | 从平台提取允许且已开启的 SZ SLM；不新增/移动/开启站点 |

旧 `optimize_initial` 的快速退火/停车成本代理保留为独立工具，其 `estimated` 不升级为物理通过。`PlacementProblem` 不再把正交后端作为数据层硬要求；该限制移入实际使用这套运动公式的 `PlacementCostModel`。通用 evaluator 搜索可接其他后端；本次实际执行适配器只接已有 `ordered_greedy` 和 `smt_ordered` 控制器，不能据此宣称 rigid 或任意后端已验收。

## 搜索如何使用编译反馈

1. **先完整评估用户原映射**，记为基线，不用内部生成布局替换它。
2. 小空间在限额内可穷举。较大空间从当前实际最快映射生成单 qubit 交换、可选空位迁移和随机全局置换。
3. 用完整电路中的 CZ 交互次数加权曼哈顿距离为候选排序。这是距离指标，不是时间预测；不声称等价于 AOD 行列兼容性或最短路线。
4. 每隔 `explore_every` 次从候选池探索，不要求代理改善，也没有先取固定 top-K 永久排除其他映射。随机全局置换可跨越所有单交换都更差的局部障碍。
5. 逐候选实际调用固定编译器；校验全部门效果恰好一次、无待执行事件、终态和可选协议判据，再从初始 snapshot 独立重放。只以通过后的总时间更新当前最佳映射，供下一次搜索使用。
6. 缓存本次运行已尝试的完整映射，包括失败，避免重复编译。预算统计包含基线与失败；失败记录保留诊断、已接受 plans 和状态。
7. 默认最多12次实际评估，包含各自重放。未找到加速返回 `baseline_retained`；基线失败但找到可执行解为 `valid_without_baseline`，不报加速比例；全失败为 `no_valid_execution`。

配置：`max_evaluations=12, proposal_pool=64, seed=7, allow_vacancies=False, exhaustive_limit=64, explore_every=3`。停止原因、尝试数、映射空间大小和是否全部枚举均导出。只对实际评估的合法候选作最优选择；有限搜索、编译失败或超时不证明无物理解。

在 n 个可移动原子、m 个可用站点时，完整分配空间为 `m!/(m-n)!`。算法不会默认穷举它；每轮限制候选池与提案尝试，昂贵部分是最多 B 次完整编译和重放。当前还没有增量重编译或学习型时长代理；大电路的单次编译若很慢，优化也不会自动变成秒级。

## Python 与文件入口

```python
from neutral_atom_app.placement_execution import optimize_compiled_layout
from neutral_atom_strategies.placement import CompilerSearchConfig

result = optimize_compiled_layout(
    circuit, platform, initial_mapping,
    config=CompilerSearchConfig(max_evaluations=12, seed=7),
    compiler_options={"strategy": "ordered_greedy", "compile_timeout_s": 90},
    output="artifacts/my-placement-search",
)
if result.selected is not None:
    optimized_mapping = dict(result.selected.mapping)
```

自定义 `PhysicalCircuit` 与已有平台可直接调用，含读出时传入 `quantum_state`；协议正确性由 `verify_protocol(state)` 可选回调独立核验。没有偷偷将含测量电路裁剪成 CZ 电路。工作台自身仍将 MEASURE/RESET UI 限于 QEC 配置，这个历史输入限制没有扩散到算法 API。

导出的工作台 JSON 可无界面运行（原文件必须已选有序贪心或 SMT，不隐式切换）：

```powershell
python examples/optimize_compiled_layout.py --input input.json --output artifacts/custom-placement --evaluations 12
```

`contract.json` 保存完整平台/电路/共同终态和搜索配置；`search.json` 给出基线、所有尝试、选中映射及收益；各 `trial-*/` 保存 `initial.json`、`final.json`、`plans.json`、`result.json`。不会用候选自己的便宜终态与基线比较。

## 非可视化验收

固定4原子，使用行、二维、打乱和不规则交错站点；每例最多8次实际评估。两种交互图分别为 `(0,3),(1,2)` 与 `(0,1),(2,3)`，加上 H/T。三轮电路在相邻 CZ 轮之间加入非对易 H，避免用可直接抵消的重复 CZ 冒充工作负载。对照共14例、112份真实执行和完整独立重放，全部通过。每例固定原电路/硬件/AOD初态/SLM开关/随机种子及绝对终态，审计确认选中时间是已评估候选中的最小值。

| 三轮案例 | 原布局 μs | 选中 μs | 减少 |
| --- | ---: | ---: | ---: |
| 行布局，交叉配对 | 3602.440 | 2611.197 | 27.52% |
| 二维布局，交叉配对 | 4123.286 | 2974.438 | 27.86% |
| 打乱布局，另一配对图 | 4123.286 | 3050.545 | 26.02% |
| 不规则格点，交叉配对 | 4300.759 | 3629.873 | 15.60% |

其余4个三轮案例与6个短电路均返回原布局，未宣称已经全局最优。典型反例：二维短电路候选让 CZ 从2批降为1批，circuit段1067.03→340.86 μs，但共同终态恢复422.37→1823.59 μs，总时间1834.31→2509.37 μs，正确拒绝。三轮相邻配对原布局已经有良好的并行性，预算内候选没有改善。

8次编译和重放的实测墙钟：短例约23–30秒，三轮约56–87秒；并发测试会影响这些墙钟数字，不能与仿真 μs 混用，更不能当作100原子搜索耗时。新优化循环不调用旧ZAC实验、不读取demo预设来决定候选。

测试：初态/边界54项通过，后续新增预算回退分支后 `test_compiler_placement.py` 15项通过；原有 `test_ordered_workbench.py` 14项全部通过。新接口的 H/CZ/T，以及含MEASURE/条件X/RESET的小型Clifford协议，均完整执行和独立重放；后者还检查最终两原子 Z 期望均为+1。180模块依赖方向审计通过。CLI导入真实工作台JSON并保存基线执行成功。新CLI没有进行GUI验收，也未改UI。

证据：`artifacts/initial-placement/general-acceptance.json` 汇总14例和分段时间；各目录 `summary.json` 与 `trial-*/` 是原始证据。54项结果在 `general-unit.xml`，后续15项在 `general-search-final.xml`。`general-ordered-regression.xml` 同时保留了首次测试夹具被旧UI的QEC输入限制拒绝的失败及14项旧工作台通过；修正测试为直接传PhysicalCircuit后，小型读出协议通过，并非修改了环境硬条件。

复现统一算法、多布局和两类交互图：

```powershell
python examples/check_compiler_placement.py --output artifacts/initial-placement/general
python examples/check_compiler_placement.py --rounds 3 --output artifacts/initial-placement/general-three-round
python examples/check_compiler_placement.py --rounds 3 --layouts irregular --output artifacts/initial-placement/general-irregular
python -m pytest -q tests/test_compiler_placement.py tests/test_initial_placement.py tests/test_surface_initial_placement.py tests/test_environment_boundary.py
python tools/check_architecture.py
```

这些是一般物理电路测试，不是新一轮完整 surface-code GHZ 加速结论。原34原子QEC的保形对照仍保留在 `surface_initial_placement.md`；它证明过正确性，没有证明自由分配搜索在该大电路上的收益。

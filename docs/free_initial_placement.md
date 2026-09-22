# 自由初态布局与顺序排布对照

当前版本已按用户要求新增[并行搜索与稳定结束模式](parallel_initial_placement.md)：新草稿256候选池、4进程、不做末尾原layout归还。本文下述结果和共同终态合同属于保留的历史固定终态对照。

后续新增[求解过程与更复杂对照](placement_search_method.md)：12原子84门、16原子96门各6候选全部通过，但当前总时间目标均保留顺序基线；门更早完成的候选受到固定终态归还开销惩罚。不能将下方八原子正结果推广为所有电路都加速。

2026-09-21。此前默认仅交换原来占据站点上的 qubit，没有完成“不限制原子占据几何”的要求。本轮独立补入自由选址入口：每个原子可以选择完整候选域中的不同 SLM，包含原先空闲、关闭的站点；不锁定原有行列、矩形、patch 或整体平移。有限搜索不能保证全局最优。

## 自由度与物理边界

自由的是原子初态占据形状及 qubit→SLM 分配。平台提供合法 SLM 坐标及区域；并非要求原子填满硬件矩形。Python API 可以使用不规则的合法站点集合，工作台用可调行列、间距生成候选硬件域。连续坐标的新 trap 生成、改变区域几何或物理网格尚未实现，不能将本轮描述成连续空间全局最优。

关闭但允许使用的 SZ SLM 在创建候选环境前准备支撑；旧初始占据点关闭，新占据点开启，其余初始开关保留。此步骤属于已准备初态，不在运行中替换 placement，不含初始阵列装配成本。每个候选完整执行同一电路，并恢复顺序基线的共同绝对终态，包括 holder、AOD 和 SLM 开关。物理规则没有放宽。

## 模块与调用

- `strategies/placement/free.py`：电路交互图构造种子，加交换、空位迁移和随机探索；没有 surface/GHZ 名称或专用排布分支。
- `placement/verified.py`：有界完整编译反馈搜索，保留基线和失败，选择通过验证的最短总时间。
- `app/placement_execution.py::optimize_free_layout`：提取完整 SZ 域、准备初态、调用普通有序控制器，检查门效果恰好一次、终态和独立重放。
- `app/placement_workbench.py` 与 `visualization/placement*`：顺序基线、输入校验、真实计划录制、可编辑电路及共用 viewer。

```python
from neutral_atom_app.placement_execution import optimize_free_layout
from neutral_atom_strategies.placement import CompilerSearchConfig

result = optimize_free_layout(
    circuit, platform, sequential_mapping,
    config=CompilerSearchConfig(max_evaluations=12, allow_vacancies=True, seed=7),
    compiler_options={"strategy": "ordered_greedy", "compile_timeout_s": 60},
    output="artifacts/my-free-placement",
)
```

`locked`、`storage_ids` 可显式约束用户指定位置；默认不锁定。传入 `allow_vacancies=False` 会拒绝，避免悄悄回到原占据形状上的排列优化。旧 `optimize_compiled_layout` 默认兼容保留。

```powershell
python examples/compare_free_placement.py --evaluations 12
python examples/placement_workbench.py --port 60054
```

打开 `http://127.0.0.1:60054/?job=default`。先改初始平台，再编辑完整门 JSON，点击线路层编译按钮。可改原子数、SLM 候选域和 AOD 容量；未找到改进时显示并保留基线。不是浏览器内离线编译器，需要本地 Python 服务。既有 `baseline.html`、`optimized.html` 可离线回放。

## 本轮实测

默认实例为 8 原子、25 个物理门，包含 H/T 和三轮四对 CZ；轮间 H 保留真实非对易依赖。它是一般物理电路，**不是两逻辑 surface-code GHZ**。32 个可用 SZ SLM、同一 4×8 AOD、同一编译器和共同终态，12 次评估全部执行及独立重放通过；11 个非基线候选都改变占据形状。

| 指标 | 顺序排布 | 自由优化 |
| --- | ---: | ---: |
| 占据形状 | 1×8 | 2×4 |
| 完整时间（含共同终态恢复）/ μs | 7810.622 | 5104.993 |
| 最后逻辑门完成 / μs | 7278.148 | 1365.506 |
| 装载 / 卸载批次 | 14 / 14 | 9 / 9 |
| 原子累计路程 / μm | 1384 | 952 |
| CZ 光脉冲 | 12 次、每次 1 对 | 3 次、每次 4 对 |

总时间下降 **34.64%**。优化后逻辑完成很早，但共同终态恢复仍占较多时间，因此不能只以最后一个门的时间报告加速。完整搜索、独立重放与两份动画录制墙钟为 **197.53 s**，与几千 μs 的仿真时间不是同一指标。完整映射空间为 424,097,856,000，实际仅尝试 12 个；没有最优性证明，也没有保真度提升结论。

证据：`artifacts/free-placement/default/comparison.json`、`search/` 中逐候选初态/计划/终态/失败文件、两份共用 viewer 录制。源数据来自 Executor，而非界面补画轨迹。

## 验收

- 18 项自由选址与实际编译测试、36 项既有初态及环境边界回归通过；183 模块架构审计通过。
- 两份录制的完整门 ID、15 个 CZ 脉冲实际 2 μm 距离、共同终态、两种播放模式 32× 自动结束及录制不可变性通过离线检查。
- 真实浏览器：显示两种初态；点击门定位到实际四对并行 CZ；两版 32× 自动结束至 25/25；修改为 4 原子 3 门后实际重新编译成功，没有收益时保留基线；非法 qubit 展开失败报告。
- 大规模 surface GHZ 的自由形状搜索尚未在本轮重新验收；此前保形平移的负结果不被本轮八原子成绩覆盖。

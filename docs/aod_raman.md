# 静止 AOD 单比特门与邻距规则

2026-09-11。当前工作台使用同一条 pipeline：初始条件 → 可编辑线路 → 编译 → 独立物理验证 → Executor → recorder/viewer。

## 文献与项目约定

Bluvstein 等的 [Logical quantum processor based on reconfigurable atom arrays](https://arxiv.org/html/2312.03982v1)（Nature 626, 58–65, 2024）在 Methods 的 Dynamical decoupling and local gates 中明确描述在 AOD 和 SLM 承载原子上执行局部单比特门。用于 Raman 寻址的 AOD 是额外光学控制，不等于运输 AOD。

这支持本项目开放静止 AOD 目标；不据此实现运输途中或交接中的门。该实验报告约 ≥6 μm 邻距用于抑制串扰、每行局部旋转约 5–8 μs，并讨论更快约 1 μs 的方案。**本项目 ≥5 μm 和固定 1 μs 是用户确认的研究模型参数，不是该论文对 5 μm / 1 μs 门保真度的实验证明。** 没有模拟光腰、噪声或量子态演化。

## 当前物理契约

- H/X/Y/Z/T：目标存活、未测量，在有效寻址区，由开启的 SLM 或静止 AOD 支撑，并已完成自己的交接。
- 目标与任意其他存活原子的距离 **≥5 μm 允许，<5 μm 拒绝**，不区分目标或邻居的 SLM/AOD holder。空 trap 不作为邻居原子。
- 对移动邻居，校验实际脉冲区间内的最近距离，不能只看整段运动两端；rigid 线性时间进度与 row-column 三次时间进度分别处理。
- AOD 目标的 Raman 使用逐 qubit `RAMAN:Qxxx`、目标 atom 和 `AOD_0` 资源锁，保证目标脉冲期间运输设备不移动、不切换支撑。SLM 目标额外使用相应 trap 资源。单 trap 范围内 SLM 与 AOD 上同类型门可并行。
- 不同门类型仍分时执行；每个单比特门固定 1 μs；CZ 默认 0.3 μs。AOD 活动时间指标保留运输/交接/开关等原操作口径，资源图的 AOD 占用区间另包含 AOD 目标 Raman 的静止锁。

## M4 与可视化

Greedy 为两种 holder 都提供原位单比特候选，不因 AOD holder 自动卸载。近距离 CZ 配对后，尝试把已装载原子沿半格正交通道分离，再执行门；必要时仍比较合法 SLM 安置候选，所有运动、开关、装卸计入成本。CZ 比较左、右、上、下四侧与合法当前姿态复用，不强制左侧。装载与脱离源 trap 的显式步骤保留。

工作台「载入示例 → AOD 单比特验收 · CZ / 分离 / T / CZ」可以编辑、随机替换、导入导出并重新编译。回放脉冲说明和原子详情显示真实 holder；两个 T 的验收例分别在 SLM 与 AOD 上同步作用。可用「查看此门操作」定位短脉冲，播放支持 32×。

有限搜索失败仍生成失败弹窗和实际诊断，不保证任意输入都找到合法计划。M4 填充窗口目前对邻居的完整 MOVE 段作保守筛选；最终 validator 能验证更短的实际重叠区间，但调度器尚未求解所有可用子区间。单 AOD 非抢占服务、多 AOD/批量 CZ/保真度均不在本次范围。

checkpoint **schema 17**，旧 1–16 从原线路输入重新编译；历史回放不修改物理记录。M3/legacy 保留原基线的搬运策略，共用当前物理校验，不承诺使用 M4 的候选自由度。

## 复现

```powershell
python examples/circuit_workbench.py --port 8767 --output artifacts/workbench-aod-raman
python examples/validate_aod_raman.py
python -m pytest -q tests/test_aod_raman.py tests/test_cz_sides_raman_neighbors.py
node tests/aod_raman_controls.cjs artifacts/aod-raman/aod-t-reuse/index.html
```

`configs/workbench/aod_raman.json` 保存验收输入。矩阵生成 input、trace、checkpoint、recording、decisions、failure_report、HTML 和独立 verification；独立 verifier 不调用 compiler。当前实际成绩见 [交接日志](../instruction/logs/2026-09-11-aod-raman.md)。

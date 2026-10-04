# 并行码块的自动 MZ 测量选点

范围提示：下文是旧 rigid/ENV 实现及其历史资格。实际选点排序是候选内完整服务时间优先，不能据 `nearest_mz` 名称声称几何最近。当前[Enola＋MZ 目标](qec_enola_mz_design.md#当前协议入口与生效关系)要求距离优先、等距比较时间、稳定 MZ SLM 支撑；该新适配尚待实现，下述旧结果不替代它。

2026-10-04 用户确认：编译器自动选择 MZ 内最近合法的测量位置。原有有序 QEC 的 `ReadoutPlacementPolicy` 保持；此前 `parallel_patch` 绕过该策略，给 rigid 阵列写死 `translation_um`，是本次修复的入口问题。

## 选点与寻路的职责

`scheduling/rigid_readout_placement.py` 提供设备感知的 `RigidReadoutPlacementPolicy`。它固定此次捕获的原子、AOD、完整行列偏移和源捕获原点；从实际 registry 读取设备，不能把主 AOD 的轴或 envelope 套给右侧资源设备。

对每个 MZ 矩形，先扣除实际载体的最小/最大偏移，得到全部待测原子都能进入 MZ 的阵列原点可行域；再与 world、设备 envelope 扣除**全部配置轴跨度**后的域相交。关闭的备用轴仍检查边界；只有载体需要进入 MZ，不能要求整台空阱阵列都位于测量区域。

将源原点投影到可行矩形，得到最近几何位置；其周围 ±2.5/±5 μm 形成有限候选。端点几何可容纳不表示运输可行。每个尝试的候选都用私有 ProgramBuilder 构造并验证完整服务：

```text
空 AOD 定位 → 实际 LOAD → 标准直达/2.5 μm半格路由
→ 静止 AOD 上的实际 MZ MEASURE/RESET
→ 从效果后状态重新寻路 → 实际 OFFLOAD 回源位
```

默认最多尝试 16 个候选，收集至多 3 个合法完整服务，再按实际完整服务时长、AOD 路程选择。最近位置受旁观原子、活动空 trap 或通道阻挡时，继续试附近候选；失败不修改 live state。没有 MZ、载体无法容纳或有界尝试耗尽时明确失败，不把有限搜索失败解释为连续空间无解。

这是最近几何候选加有界实际服务比较，不证明连续空间或整条线路全局最优。去程最短距离也不能直接推出完整服务最短时间。保留有限 CZ 6 μm、CZ 非伙伴 10 μm、连续运输 clearance 1 μm 和 Raman 5 μm 等既有判据。

两台设备的初始化 RESET 分别选点，再按既有共享时间安排运输与联合 RESET；最终整个并发计划还须通过完整校验。设备独立选点不表示联合调度全局最优。MZ 中没有静态 SLM trap 时使用真实静止 AOD 支撑，不凭空添加测量 trap。

## 默认入口与对照复现

`compile_readout_group`、`compile_dual_reset_prologue`、`run_parallel_patch` 增加 `readout_placement`。标准 routing 默认 `nearest_mz`；显式 `fixed_translation` 保留旧测量端点。历史 `legacy_5um` 路由未指定该参数时仍使用旧固定端点，便于精确复现历史计划。

```powershell
python examples/run_parallel_shor15_prefix.py `
  --source references/qec_pbc_validation/shor15_native_prefix_seed0_2026_10_04 `
  --output artifacts/my-auto-mz-single --patches 1 --layout enola `
  --proposal references/qec_pbc_validation/enola_patch_proposal_2026_10_04.json `
  --intra-patch --intra-services --pair-search `
  --routing-policy standard --readout-placement nearest_mz
```

完整 12 块用 `--patches 12` 和独立新输出目录。完整 Executor 和原初态重放默认开启；编译机器 wall seconds 与模型 μs 分列。

此前标准路由 30055.938183 μs 的表格只隔离 routing，复现时加 `--readout-placement fixed_translation`。既有录制和生产模块指纹保留；不能将它倒填为自动选点验收。

`summary.json` 保存模式和预算；`decisions.json` 的 `readout_placement_decisions` 保存每台设备的生成数、候选位置、拒绝原因、实际成本与选择。共用回放页从这些实际日志显示选点详情，测量书签仍来自提交的物理录制。

## 验收范围

应包含最近位置、全部载体 MZ 边界、关闭备用轴、外国设备已载原子、真实障碍换点、失败纯度、完整服务成本及 Executor/原初态 replay。单块与 12 块另外按原线路/初态进行独立 source、Stim、全局 CZ/MZ/Raman、协议依赖与运输审计。实际运行与浏览器结果完成后追加到本节，不用单块结果代替多块验收。

## 2026-10-04 实际完成验收

两组各自固定初态、platform、source、circuit、phases和原门/effect合批顺序，原始字节独立一致；只在相同标准router下恢复自动测量选点。所有原门与投影保持，不由预期syndrome省略测量。

| 规模 | 原门 / 投影 / 原子 | 固定端点 μs | 自动 MZ μs | 减少 | MOVE |
| --- | --- | --- | --- | --- | --- |
| 1块 | 267 / 50 / 34 | 30055.938183 | 22195.938183 | 26.1512% | 338 → 314 |
| 12块 | 3006 / 413 / 221 | 30055.938183 | 27955.938183 | 6.9870% | 338 → 314 |

两组均161plans、2AOD、7个设备选点覆盖全部50/413原投影；原初态完整replay与独立source/Stim/依赖/全局CZ/MZ/Raman、patch协议和新增选点审计全部通过。算法和magic分别按自己的载体跨度/设备域选点。单块first算法源原点(0,0)，几何nearest(0,-80)，实际选(-2.5,-80)；magic为(170,-70)。实际完整服务cost胜过纯clamp，详情明确记录该有限邻域取舍。

185项不同相关pytest通过，其中policy14、integration9、report11、独立audit15；267模块架构零违规。portable audit篡改用例拒绝缺失/重复投影、日志费用自洽但不同实际成本、假所选位置/可行域等；align tolerance与双lane费用正例保持。旧HEAD9a111846的standard/legacy单服务及双RESET四份canonical UTF8 bytes精确一致。

实际[12块自动MZ回放](http://127.0.0.1:8777/)中“ MZ落点选择与服务成本”可展开候选及载体坐标，定位按钮跳真实提交pulse；12个功能书签、原子同比缩放、X/Z、主统计/默认折叠与390/320px检查通过。原8776固定端点routing回放保留。完整输入、实际生产模块指纹、三层审计和browser录制SHA见[小型证据](../references/qec_pbc_validation/auto_mz_placement_2026_10_04.json)。single运行后CLI仅更名显示contract中的历史translation，编译/执行/选点源码未变，实际producer hash保留；full12使用最终CLI。

本次修复选点接入和决策显示，范围仍首资源T前Clifford；完整工厂/injection/processor按共享v2的S1–S3推进，不由本运行声称已完成。

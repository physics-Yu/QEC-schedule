# ZAC 原生初始化优化与四组对照

在原 ZAC 实验台选择“固定／SA × Reuse 开／关”可以完整比较初始化与复用。结果页展示四组完成状态、固定与 SA 初态同尺度图、五种因素比较、实际阶段时间、作者求解墙钟、失败记录、完整 CZ 电路及原共用物理 viewer。旧固定初态默认值兼容。

## 接入边界

`zac_frontend.py` 的 `initial_placement=sa` 不调用 `set_initial_mapping`，并设置 `trivial_placement=False`。随后正常调用作者 `place_qubit_initial()`，由未修改的 `zac/placer/saplacer.py` 求解；动态 placement、复用筛选、作者路由与 verifier 仍照原流程执行。原始源码包含在作者文件 SHA256 清单中。

作者 SA 固定 `seed(0)`，默认一个 trial，每轮 400 个扰动，退火迭代条件上限由作者原实现控制。`l2=False`。成本为 `SAPlacer.get_cost`：线路前五层权重 1、0.9、0.8、0.7、0.6，之后保持 0.6；配对距离通过架构最近纠缠位置函数及作者 `distance()` 计算。它是代理量，不是本地 μs，也不是最优性证明。本接入不替换作者的目标或优化器。

额外使用作者原 `get_cost()` 核算固定布局及输出布局成本；核算前后保存、恢复 RNG 状态，避免观测改变后续决策。`initial_placement.seconds` 只记录作者初态求解；前端和作者含路由/校验秒数还包含这次代理核算。SA 两个 reuse 设置各自独立求解，检查输出映射一致；两次墙钟分别记录，不能当作单次共享计算。

## 四组合同

| 组别 | 运行开始时的 placement | 跨层复用 |
| --- | --- | --- |
| fixed_no_reuse | 原按编号排列的 SZ 初态 | 关闭 |
| fixed_reuse | 同一固定初态 | 开启 |
| sa_no_reuse | 作者 SA 的 SZ 输出 | 关闭 |
| sa_reuse | 同一 SA 输出，独立求解核对 | 开启 |

每条线路固定 CZ 顺序、Q 身份、架构几何、AOD 能力、运输候选预算及物理验证。两种初态均在创建 `NeutralAtomEnv` 前配置 holder 与支撑，不能在运行中瞬移。所有四组恢复到**原按编号排列初态所定义的同一绝对终态**，包括 holder、SLM masks、AOD axes/masks。`terminal-target.json` 与目标 SHA256 随每组保存。

物理时间从各自已制备初态开始；原子初次装载或从固定布局重排成 SA 布局的制备时间未计入。这是初始 placement 编译实验，不是给定已装载阵列的重排成本实验。SA 计算秒数与仿真物理 μs 分开。末尾共同归还的实际成本计入总物理时间，并单列。

四组比较分别报告固定初态下 reuse 效果、SA 初态下 reuse 效果、reuse 关闭时 SA 效果、reuse 开启时 SA 效果及两项联合效果。只有双方完成整条线路、独立重放、每门恰好一次和共同终态时才计算比值；reuse 对照额外要求完整初态 SHA256 一致。失败项只显示已执行前缀，不能当作较快解。

## 运行与复查

```powershell
python examples/benchmark_zac_initial.py --output artifacts/zac-reuse/benchmark-initial-new --sizes 16 32 --families butterfly random --depth 8 --workers 4 --timeout 600
python tools/audit_zac_initial.py artifacts/zac-reuse/benchmark-initial-new
node tests/zac_reuse_viewer.cjs artifacts/zac-reuse/benchmark-initial-new
python examples/zac_reuse_workbench.py --port 52813
```

入口 `http://127.0.0.1:52813/benchmark-initial-new/index.html`。原编辑器的 `initial_placement` 接受 `fixed`、`sa`、`compare`；前两项为两组开关对照，后一项为四组实验。四组实验的原始输入可从汇总目录内 `case/input.json` 带回原编辑器。

批量 runner 使用独立子进程；每份本地执行软预算默认 600 s，作者前端子进程预算 120 s，整份硬预算默认 1500 s，并至少为两倍本地预算加 180 s。硬超时停止该 worker 的子进程树，保存明确 timeout。单份失败不会中断其他组。已有目录只允许源码、参数、合同完全相同的 `--resume`，不会把已完成失败静默重试。

每组保存原始输入、作者输出/日志、初态优化元数据、完整 initial/checkpoint、plans、trace、recording、终态目标及物理/线路 HTML。总表保存全部 CSV、源码哈希、逐组错误与五种比较。固定版本结果不覆盖原 `benchmark-grid` 或 `benchmark-large`。

## 验证边界

2026-09-22 实测目录为 `artifacts/zac-reuse/benchmark-initial-20260922`，入口 `http://127.0.0.1:52813/benchmark-initial-20260922/index.html`。16/32 原子、8 层、蝶形/固定种子随机线路，四组共16份，14 completed、2 failed，无超时。各规模 AOD 与 SZ/EZ 容量按旧 benchmark 规则扩展；同一条线路的四组平台一致。

| 线路 | 固定 / 关 μs | 固定 / 开 μs | SA / 关 μs | SA / 开 μs |
| --- | ---: | ---: | ---: | ---: |
| 蝶形16，64CZ | 53294.970 | 33799.620 | 52845.155 | 33490.019 |
| 随机16，64CZ | 61434.983 | 44392.072 | 62007.025 | 44858.305 |
| 蝶形32，128CZ | 终态失败 | 41552.119 | 84953.691 | 44332.789 |
| 随机32，128CZ | 128809.089 | 97369.461 | 122360.202 | 48/128 CZ 后运输失败 |

单看 SA 增量，reuse 开启时：蝶形16减少0.92%，随机16增加1.05%，蝶形32增加6.69%；随机32的 SA/reuse 不完整，不计算比值。reuse 关闭时，随机32的完整执行减少5.01%。作者距离代理四例均下降，但不能推导本地总物理时间一定下降。

两条失败：蝶形32固定/关完成128门，末尾为Q016恢复原holder时耗尽候选，85778.265 μs只是前缀；随机32 SA/开完成48门，在第4层入区准备为Q012找路线时耗尽44个有限候选，33669.830 μs只是前缀。候选日志包含 `AOD_OUTSIDE_WORLD`；未扩大世界或放宽碰撞/轴约束，不声明物理无解。

原 SA 初始化子程序的每份墙钟约54–114秒；整批收集1171.89秒，4进程并发且期间有验证负载，不作为专用机器编译基准。随机32的固定代理852.458→SA主循环起点764.294→最终735.093，初始构造与主循环贡献分开可查。蝶形两例主循环起点与最终代理相同，不能把全部改善归因于退火迭代。

189份执行相关本地/作者源码已按运行前哈希保存到 `source-snapshot`。完成后仅更新展示源码，另保存于 `source-snapshot/presentation` 并记录 `render.json`；未重算或替换物理数据。原批次 `benchmark-grid` / `benchmark-large` 保留。GitHub固定版本与Zenodo AE的 `saplacer.py` 字节哈希均为 `8aad423c7891c24ef9a9831754a13217a5b801f9a2e42a5c0735981f60e0aacf`。

`tests/test_zac_initial.py` 检查错误比较不产生收益，以及原 SA 输出真正成为物理初态、完整 CZ 效果、独立重放、最终回到固定绝对终态。保存产物由 `audit_zac_initial.py` 独立核对输入、ASAP 深度、映射、门 trace、阶段时间、驻留覆盖、终态硬件字段及完成项百分比。

这仍是作者算法在本地框架下的 CZ 合成线路实验。不同 N 的平台容量随规模增长；不代表固定设备强扩展、论文完整 AE、混合 1Q、保真度、任意实例可路由或全局最优。

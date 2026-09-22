# ZAC reuse-aware 算法接入与物理复现

2026-09-21：新增 [16–128 原子大实例 benchmark](zac_benchmark.md)、CSV、失败诊断与共用物理回放；下表五例为最初的小规模接入结果。

本实验直接接入作者的 **ASAP 分层 → 相邻层二分匹配 → 动态 gate/storage placement → reuse 筛选**，将输出的每个目标映射交给本项目运输策略，再通过 `NeutralAtomEnv.submit/run`、Executor、VisualRecorder 和共用 viewer 执行与展示。两种开关均运行作者的原始 router 生成 ZAIR，作为单独参考；我们的动画与指标来自本项目实际执行记录。

## 来源与算法含义

- [GitHub ZAC](https://github.com/UCLA-VAST/ZAC/tree/e5083362f99e6915f20c2bd0eaa88b6d1cdcecac)，固定 commit `e5083362f99e6915f20c2bd0eaa88b6d1cdcecac`。
- [Zenodo 14219336](https://zenodo.org/records/14219336)，`ZAC_AE.zip`，MD5 `c1252777c660fc93153e3ae5a38f5c7b`；本次下载核对一致。SHA256 与 GitHub archive 哈希在 `artifacts/zac-reuse/sources/manifest.json`。
- [论文](https://arxiv.org/html/2411.11784v3)，§V-B；AE 的技术消融设置为 `exp_setting/comparison_technique.json` 中 `dynPlace` 与 `dynPlace_reuse`。本实验采用二者的 ASAP、dynamic placement 和 reuse 开关，固定相同初始映射；不混入 SA 初态变化。

`ZAC.collect_reuse_qubit` 的二分图两侧分别是相邻层的 CZ 门，共用原子对应一条边。最大匹配让每个旧站点和每个新门至多承接一个复用原子；连续重复的同一对 CZ 可保留两颗原子。选中的原子在 **EZ 的 SLM** 留驻，不等于跨层一直载在 AOD 上。

`VertexMatchingPlacer` 继续比较带/不带 reuse 的布局；`filter_mapping` 可能撤销匹配候选。我们保存 `matching_reuse` 与 `selected_reuse`，不把匹配候选数量当作实际实现的留驻数量。保留作者的距离/transfer/decoherence 代理评分，未替换为本平台总物理时间最优目标。

GitHub 与 AE 的 `vmplacer.py`、`scheduler.py` 内容相同；`zac.py` 有介绍文本差异，router 的 1Q 时间字段存在差异。本次 **5 条 CZ 线路 × 2 个 reuse 设置**的分层、匹配候选、筛选结果和完整映射序列逐项一致。单独证据：`artifacts/zac-reuse/source-parity/report.json`。这个比较没有覆盖 1Q 分支。

## 本平台的执行适配

| 环节 | 本次实现与边界 |
| --- | --- |
| 输入 | 2–128 原子、1–4096 个物理 CZ；按 qubit 依赖 ASAP，重复 CZ 保留，不做电路重综合；上限是输入能力，不代表所有实例均能在有限预算内编译成功 |
| 作者前端 | 在独立 Python 子进程导入未改动的下载源码；同时运行作者 router/原有 verifier，保存日志与 ZAIR |
| 初态 | 全部原子在 SZ；10 μm 存储间距，EZ 成对 SLM 相隔 2 μm，站点按 20 μm 分隔；1 μm 坐标格用于表达这些固定候选站点 |
| 平台 | 单台 `row_column_orthogonal` AOD；共享行列有序运动，完整活动 Cartesian 交点检查 |
| 物理参数 | 保留项目默认 1 μm 原子/SLM clearance、AOD 间距严格大于 1.01 μm、2 μm CZ 范围、100/100 μs 装卸、0.3 μs CZ、峰值速度/加速度/jerk 约束与四邻规则；不是论文硬件的同参数性能复现 |
| 运输 | 对外部目标映射尝试兼容批次；失败后分批/单原子回退；调用现有 OrderedTransfer/axis-hold，候选与连续扫掠均由原验证器核验 |
| 置换 | 目标存储位置形成置换环时使用显式空 buffer SLM；装卸、绕路、定位全部计时 |
| CZ | 真实一个 `ENTANGLING_PULSE` 完成整层门，整个 EZ 的实际作用对必须严格等于预期门集合 |
| 终态 | 两组均恢复完全相同的初始 holder、SLM masks、AOD 坐标及 masks；逻辑完成与完整清理时间分开 |
| 驻留核验 | 检查两次 pulse 间的实际全部运输 decisions，选中原子不参与搬运，三份相邻映射的 SLM holder 一致 |
| 重放 | 从原始 checkpoint 用新的环境再次提交全部接受的 plans，比较完整最终 snapshot；逐门效果 exactly once |

没有改动物理硬约束或运行时物理代码。共用 viewer 增加可选的显示网格抽样、隐藏未配置候选点；ZAC 页显示 10 μm 辅助网格，录制中的 1 μm 候选几何不变，其余工作台默认行为不变。原子编号仍可切换悬停/选中、全部或隐藏，完整电路与侧栏始终保留Q编号。

本次前端在现有 Python 3.12 环境运行，记录了 NumPy 2.5.3、SciPy 1.18.1、Qiskit 0.45.2、rustworkx 0.13.2；这不等于 AE 的原依赖环境（例如原要求 Qiskit 1.2.4）。我们直接传入 physical CZ，不调用 QASM 解析或 transpile，未声称上述版本对全部作者功能兼容。

## 已执行结果

所有时间为本环境仿真 μs，包含初态出发、开关/装卸、运输、CZ 和相同终态清理；表中原子装载次数为每次装载的原子数之和，不是装载批次数。

| 线路 | 原子 / CZ | 关闭 reuse | 开启 reuse | 总时间变化 | 原子装载次数（关→开） |
| --- | --- | ---: | ---: | ---: | ---: |
| 四原子换伙伴 | 4 / 6 | 9721.635 | 8548.611 | −12.07% | 28→20 |
| 连续重复配对 | 4 / 6 | 8348.821 | 3273.047 | −60.80% | 28→12 |
| 八原子交叉配对 | 8 / 12 | 13929.363 | 11622.378 | −16.56% | 56→40 |
| 含闲置原子 | 6 / 5 | 7145.003 | 6897.363 | −3.47% | 25→20 |
| 三门反例 | 4 / 3 | 4226.381 | 5295.270 | **+25.29%** | 16→14 |

三门反例为 `CZ(0,1), CZ(2,3), CZ(0,2)`，源于真实界面的编辑测试。开启 reuse 后逻辑门完成从 3246.370 降到 3119.312 μs，但总时间变差：装载批数 7→9，AOD 路程 614→717 μm，显式 terminal-return 阶段 387.004→928.928 μs。该结果说明作者选出的 reuse 与本项目运输器/终态条件组合后未必缩短总时间，不能将少装载原子直接换算为物理加速。

十份正式运行均通过独立重放、门效果恰好一次和终态校验；24 个跨层原子驻留区间通过核对。不是量子保真度、硬件实验或论文全套 benchmark 的复现。

## 运行与查看

当前已配置环境中，在仓库根目录运行：

```powershell
python tools/fetch_zac_sources.py
python examples/run_zac_reuse.py --demo eight --output artifacts/zac-reuse/eight
python examples/run_zac_reuse.py --demo tradeoff --output artifacts/zac-reuse/tradeoff
python examples/zac_reuse_workbench.py --port 8769
```

然后访问 `http://127.0.0.1:8769/`。页面可修改 CZ 对，手动编译两组，显示完整线路、gate/Q 编号、跨层留驻 holder、真实物理动画、实际 CZ 脉冲与清理。点击门定位 pulse，点击层按钮查看留驻区间。共用 viewer 支持两种时间模式和最高 32× 播放。

新环境需要可导入的 NumPy、SciPy、Matplotlib、Qiskit、rustworkx；作者的原依赖清单位于下载后的 `sources/zenodo/ZAC_AE/requirements.txt`。当前没有提供或宣称验证过全新依赖安装/跨电脑打包。

离线结果位于各例的 `index.html`、`reuse/index.html`、`no_reuse/index.html`。每组目录还有 `upstream/placement.json`、`author-zair.json`、`initial.json`、`checkpoint.json`、`plans.json`、`trace.jsonl`、`recording.json` 和 `rejections.json`。所有正式页面从生成模块导出，可用 `python tools/render_zac_reports.py` 重新生成。

验证命令：

```powershell
python -m pytest tests/test_zac_reuse.py tests/test_environment_boundary.py tests/test_batch_cz.py -q
python -m pytest tests/test_visualization.py tests/test_zac_reuse.py -q
python tools/check_zac_source_parity.py
python tools/check_architecture.py
python tools/render_zac_reports.py
node tests/zac_reuse_viewer.cjs
```

实际浏览器已验证三门编辑重编译、开/关结果、门定位、留驻 holder、32× 终态和画布显示。Node 检查另覆盖十份当前录制、28 个实际 CZ 脉冲、24 个驻留区间、两种模式 32× 和源录制不变；不把 Node 替身当浏览器验收。

## 实现入口与后续

- `src/neutral_atom_experiments/zac_frontend.py`：作者源码适配、过程日志、源哈希与版本记录。
- `src/neutral_atom_strategies/scheduling/zac_reuse.py`：目标映射的真实运输执行策略，外部环境接口不变。
- `src/neutral_atom_experiments/zac_reuse.py`：平台、五组线路、同初态/终态消融与重放。
- `src/neutral_atom_experiments/zac_reuse_report.py`、`src/neutral_atom_app/visualization/zac_reuse*`：共用 viewer 上的完整线路与可编辑工作台。

待做：用本平台的完整合法物理候选成本重评 reuse 决策；在相同完整电路下处理 1Q 的 ≥5 μm 寻址约束；导入作者 benchmark、原依赖环境与原硬件参数进行完整 AE 数值复现；更广规模与布局、多个 AOD。当前不自动退回 no-reuse 来掩盖作者方案在本环境的负收益。

# QMAP 原生内核与原有实验验收

2026-09-22 大规模尝试：[5,000原子报告](qmap_large_benchmark.md)。高并行graph-state在900s预算内未完成；5000比特GHZ链14998门原生9.28s编译并通过门级/离散端点审计。均为作者平台原生实验，未进行5000原子本地物理执行。

2026-09-22 运动修正：原实现逐个保留作者中间路标造成不必要的阶梯路径，已在本地策略层改为装卸/门边界之间的连续校验缩短，并保持闲置轴位置。下方原有实验表是修正前记录；当前用户9原子12门的路径修复与同输入对照见 [运动修正日志](../instruction/logs/2026-09-22-qmap-motion.md)。

2026-09-21。本轮直接调用作者发布的 C++ `RoutingAwareCompiler`，不是此前 Python `zoned_ids` 的重新命名。原生调度、复用分析、IDS 落点搜索、路由分组和代码生成保持在作者实现中；本地策略适配 NAViz 指令，通过 `NeutralAtomEnv.submit/run` 实际执行，并使用原 Atom Studio 编辑器和共用 viewer。

结论：五组原有普通电路的物理执行、逐门效果、独立重放和终态通过；作者千比特 QFT 的重排指标复现接近，但本机原生编译速度尚未达到论文。**本轮没有证明旧布局上的加速，也没有将带测量/反馈的 surface QEC 迁移到原生内核。**

## 原有实验

复现命令：`python examples/accept_qmap_original_cases.py`。输入来自原来的配置文件，保留门类型、qubit/gate ID、每比特依赖和 AOD 行列容量。结果完整保存在 `artifacts/qmap-native/original-acceptance/summary.json`；每例附原输入 SHA256、native.json、program.naviz、initial/checkpoint、plans、recording、physical.html。

| 原有案例 | 原子 / 门 | AOD 行×列 | 最大并行 CZ | 原生内核 / ms | 适配＋Env 执行录制 / s | 独立重放 / s | 完整物理过程 / ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| grid-16-parallel | 16 / 96 | 4×8 | 8 | 34.315 | 42.871 | 31.088 | 54.707 |
| partners-12-parallel | 12 / 84 | 4×8 | 6 | 6.182 | 11.283 | 9.782 | 24.194 |
| random20_depth4 | 20 / 60 | 8×8 | 10 | 14.446 | 14.397 | 11.075 | 25.299 |
| zoned_sparse20 | 20 / 12 | 8×8 | 3 | 2.924 | 3.845 | 3.027 | 8.338 |
| zoned_repeated16 | 16 / 32 | 4×4 | 8 | 7.939 | 3.309 | 2.499 | 8.007 |

五例均：`completed`、`effects_once=true`、`replay_equal=true`、`terminal_verified=true`。终态检查每原子与作者最后落点一致、全部门完成、AOD 无载荷/无运动、没有活动计划、传递或待处理事件。仿真时间包含作者程序末尾运输，不只取最后一个门的时刻。单比特脉冲仍为 1 μs，同类型才能合批。

输入相同不等于平台相同：此次显式使用 SZ 10 μm、EZ 成对 SLM 2 μm、正交有序 AOD，关闭方格四邻停驻保护。这与旧的方格平台不同，也与论文 SZ 4 μm 平台不同。因此不能拿表中物理时间直接计算相对旧布局的算法加速比。初态及最终落点由作者程序决定，没有再次调用旧初态候选池反复编译。

## 作者 benchmark 复核

来源：[论文 v1](https://arxiv.org/html/2512.13790v1)、[QMAP 仓库](https://github.com/munich-quantum-toolkit/qmap)。固定源码和许可证见 `third_party/qmap/README.md`。运行依赖 QMAP 3.5.0 / Bench 2.1.0；作者参数为 IDS、window、min16、比例1、share0.8、deepening0.01、value0、lookahead0.4、reuse5、trials4、queue100。其余参数与完整 architecture.json/request.json 一并保存。

| 作者算例 | CZ / 层数 | 本地重排 / ms | 论文重排 / ms | 本机内核 / s | 论文内核 / s |
|---|---:|---:|---:|---:|---:|
| graphstate60 strict | 60 / 6 | 12.6166 | 14.8 | 0.3749 | 0.1 |
| QFT1000 strict | 37620 / 3994 | 4937.9106 | 4937.9 | 16.1559 | 6.2 |
| QFT1000 relaxed | 37620 / 3994 | 4855.8249 | 4855.8 | 19.1453 | 未在本表引用 |
| graphstate1000 strict | 1000 / 7 | 339.0492 | 320.5 | 148.9798 | 57.6 |

QFT 重排值与论文舍入结果一致；graphstate1000 慢约 5.79%，不能称完全复现。论文为 Apple M3/16GB，本机为 Windows，strict 大例内核时间约论文的 2.6 倍；不能归因于 HTML，也不能将硬件差异当成已经证实的全部原因。relaxed 运行有并发任务，其计时不能用于严谨 strict/relaxed 速度比较。

作者 `stats.totalTime` 单位是 μs，只覆盖原生编译阶段；QFT1000 strict 加上 Qiskit 前处理和进程启动，进程墙钟约 35.82 s。上表千比特结果没有执行本地 Env 千比特物理重放。作者 Evaluator 的 `u` 过滤只在原指标计算副本中进行，真正执行 NAViz 保留全部单比特门。

## 本地兼容层实际增加了什么

1. 作者原子声明可能按位置排序；逻辑身份按 `atomN → QNNN` 映射，不能按声明顺序重新编号。
2. 将作者轨迹端点转为有序行列。直线直接走；对角位移尝试 XY/YX 或既有 axis-hold 路径，转弯按本地运动合同分段。原子和活动 trap 的连续路径继续检查。
3. 作者运输组超出本地 AOD 轴容量时，按作者抓取顺序拆成子组；每原子轨迹端点和 CZ 层保持。改变并发关系后重新核验碰撞和误捕获。random20 末尾一次拆批、repeated16 两次拆批均有原始组与子组记录。这是保守兼容方法，不是最优分组。
4. 部分卸载使用显式 `selective_transfer_enabled` 能力；仅当剩余共享行列仍支撑所有载荷时允许。卸载后关闭无载荷的轴，避免残留空交点扫过静态原子。未关闭仍有载荷的轴。
5. 作者保留在 2 μm 的 EZ 对若接单比特门，先实际将右侧伙伴移到 5 μm，打光后恢复作者位置。额外运输和装卸计入时间；没有放宽本地 5 μm 光寻址约束。
6. 本地不兼容时保留 source line、异常、执行前缀和原始 NAViz，工作台显示失败。未知指令、测量/反馈不会被删除，也不会静默退回自写算法。

因此“原生求解快”目前只解决了决策阶段。grid-16 原生约 34 ms，而物理适配/执行/录制约 43 s。后续应 profile 计划构建、连续路径验证及重复前缀校验，保持环境判据等价；不能把移植完成当作端到端性能目标完成。

## 使用与验收入口

```powershell
python tools/setup_qmap_native.py
# 网络需要时可明确传 --index-url <PyPI mirror>
python examples/accept_qmap_original_cases.py
python -m neutral_atom_app.visualization.workbench_server --port 0 --timeout 300
```

环境安装在 `artifacts/qmap-native/venv`，也可用 `QEC_QMAP_PYTHON` 指定已有兼容解释器；不修改主项目 Qiskit 0.45.2。Windows/Python3.12 使用提交的锁文件，其余平台重新按作者发布时间截断解析，尚未复验跨平台。

原工作台选择“QMAP 原生 C++ · IDS”，明确使用“QMAP 成对 SLM 平台”，可编辑 H/X/Y/Z/T/CZ、原子数和 AOD 行列容量，手动编译。strict/relaxed 进入原生路由参数。锁定的旧 QEC demo 保持原策略。旧贪心和 SMT 作为独立对照保留，不把 native 的平台需求伪装成可直接替换任意几何。

开发机本轮入口与 GUI 检查结果见 `instruction/logs/2026-09-21-qmap-native-port.md`。离线 `physical.html` 是已编译回放，编辑重编译需要 Python 服务。

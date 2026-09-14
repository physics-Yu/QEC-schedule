# 项目总览与交接快照 · 2026-09-11

截至本次交接，项目已有可编辑量子线路到真实原子操作及动画的完整串行工作台。**M0–M2 的受限基准已实现，M3-A 已验收，M3-B 的参数化单比特串行执行已实现；M3 整体尚未完成。** 本文件是有日期的实现与证据快照，不替代按领域维护的规范；以后开工仍先读 [agent](../agent.md) 与 [最新 handoff](../instruction/handoff.md)。

本次只整理文档、核对代码与历史记录，没有重跑物理测试、刷新浏览器草稿、重启服务、提交或发布。逐项检查见 [本次日志](../instruction/logs/2026-09-11-project-handoff.md)。

## 1. 用户已经确定的工作方式

默认 pipeline 固定为：

```text
01 初始条件（原子数 / layout / seed / CZ 操作数优先次序）
  → 02 可编辑量子线路（放置、编辑、随机载入 gate）
  → 后台物理编译与独立校验
  → Executor 提交真实操作、状态和 trace
  → VisualRecorder
  → 03 共用 viewer 回放及时间统计
```

- 单比特门须有真实物理执行：支持 CZ 与 U3/单比特别名混合线路，不能只绘制 gate 图标。
- 单比特光固定 **1 μs**，包括 I/RZ，无可选时长、无免费虚拟 Z。这是用户确认的项目参数，不是本轮实验标定。
- 初始条件在门设置前面；两种回放时间模式都支持 **0.25、1、2、4、8、16、32×**，倍率仅影响呈现时间。
- “随机载入”保留初始条件，替换为可继续编辑、撤销和编译的新线路；后续可视化功能继续走同一 pipeline。

## 2. 已有能力及实际边界

| 模块 | 已有能力 | 限制 / 对应规范 |
| --- | --- | --- |
| 状态与逻辑 | 统一 Q 身份、不可变值、placement/holder、静态 world、每比特依赖 DAG、稳定事件队列、trace、原子式提交、确定性恢复 | DAG READY 只表示逻辑依赖满足；[状态规范](../instruction/state_circuit.md) |
| M1/M2 | 受限 mobile–static CZ、连续 eager 电路、换伙伴/换源、成功 pulse 释放后继、累计指标、stalled 诊断与恢复 | M1/M2 部分伙伴初始预置 EZ；见 [M1](milestone1.md)、[M2](milestone2.md) |
| 输入与编译 | circuit/platform/placement 分离，可替换 GateCompiler，ProgramBuilder 只读推演，独立重放验证；全 SZ 单 trap 逐颗准备、CZ、归还 | 当前一个 gate 对应一个 plan，有限候选；[管线](circuit_pipeline.md) |
| AOD 后端 | rigid 整体平移；row_column 有序行列伸缩、三次轨迹和受限配对；显式空载定位计时 | 后端/平台能力须预先声明，不代表任意布局可路由；[后端规范](../instruction/aod_backends.md) |
| 动态光阱 M3-A | SLM 逐点 mask、AOD 行列 mask、完整活动交点、目标先支撑再交接、活动空阱扫掠和共享轴关闭检查 | 已验证串行场景；独立 TRAP_SWITCH 默认 1 μs 属未标定工程参数，和固定 Raman 时长是两个概念；[动态光阱](dynamic_traps.md) |
| 参数化 1Q | U/U3、I/X/Y/Z/H/S/Sdg/T/Tdg/RX/RY/RZ，保存原参数及规范 U 参数；RAMAN_ROTATION、独立 Raman 通道/指标、一次门效果及 trace 追溯 | 只在存活、未测量、启用且稳定 SLM 的合法寻址目标执行；仍串行；[工作台规范](circuit_workbench.md) |
| 观察与恢复 | checkpoint schema 11、操作/预约/队列交叉校验；observer 生成 /2 差量记录，共用 Canvas viewer、独立 HTML、静态验收报告 | renderer 不提交物理状态；历史记录与当前契约须区分；[可视化接入](visualization.md) |

物理脉冲的执行表示经校验、计时并提交门效果与逻辑状态，不计算量子态振幅、光场、波包、RF 波形、噪声或保真度。CPHASE 可表示角度但没有物理执行；MEASURE 的基础资格检查不等于测量结果、reset 或反馈。没有实现 QEC 编码/解码或 RL 环境。

### 工作台细节

- 输入预算：1–32 原子、最多 64 门和 64 列。全 SZ 初态，实际 SLM 间距 10 μm、候选网格 5 μm、两处空 EZ SLM。row 为单行；grid 每行 `ceil(sqrt(N))` 个站点；shuffled 对同一网格使用 `random.Random(seed)` 重排 Q→site。
- 可放置/删除 gate，编辑列、操作数和 rad 角度，撤销/重做，载入示例、导入/导出线路 JSON，下载独立回放 HTML。同列独立 gate 无依赖；列号不是时间或 barrier。forward/reverse 是同一 compiler 的 CZ 操作数优先顺序。
- 随机按钮生成 `min(12,max(4,2N))` 门，首门 U3；多原子第二门 CZ，后续混合抽样，单原子仅 1Q，每列一门。保留原子数/layout/布局 seed/搬运次序，沿用撤销和编译链路。按钮使用 `Math.random`，布局 seed 不控制门抽样；保存实际 JSON 才能复现同一随机线路。
- 自动编译防抖 650 ms，可切手动、取消；版本隔离防止旧结果覆盖新输入。服务每次只运行一个编译任务，跨页面新提交也会取消旧任务；服务器 90 s 超时，内存保留最近 8 个 job。独立 CLI 不由该服务器超时管理。
- completed/stalled 产物包含 input、recording、checkpoint（含 trace）、diagnostics；stalled 提供部分执行和失败原因。取消/超时只保留已上报进度，不保证可恢复 checkpoint。产物不会自动清理。
- 浏览器草稿没有自动持久化；刷新前导出 JSON。离线已有记录可继续回放，在线编译需要服务。
- 服务只监听 loopback，限定 Host/Origin 和 JSON 请求大小；API/输入维护详情只在 [工作台规范](circuit_workbench.md) 维护。

### 回放与统计

共用 viewer 通过 holder 和实际运动 profile 计算位置，显示 SLM/AOD trap、行列轴、全部活动交点、目标支撑与交接进度。SLM 用圆、AOD 用菱形；Raman 用单原子弧线，CZ 用实际作用对连线。支持图层、标签、缩放平移、适配视图、原子搜索/分页、操作详情、计划路径和 clearance 显示。

真实比例模式 1× 对应 25 μs/s；关键帧模式延长短 pulse/交接以便观察。两者和 32× 都不修改物理时间、路径或 metrics。统计含装载、运输、回程、卸载、CZ 脉冲、空载、开关、空闲八类，有 Raman 时增加单比特类别；真实 μs 时间轴可跳转。原子累计时间使用 atom·μs 单列，当前 summary 拒绝重叠，不能作为未来并行资源利用率算法。

记录使用 `neutral-atom-view/2`，静态数据一次保存、帧只记录变化原子，配有受限缓存和分页。512 原子/257 帧 WAIT 历史测试只证明该显示数据规模，不证明数百原子实际运输、并发或持续 FPS。

## 3. 维护入口与不可破坏的边界

以下代码路径均相对 `src/neutral_atom_env/`；先按任务查 [规范索引](../instruction/README.md)，不全量加载档案。

| 修改目标 | 主要入口 |
| --- | --- |
| gate 参数 / 操作 / 资源 | [domain/models.py](../src/neutral_atom_env/domain/models.py)、[domain/operations.py](../src/neutral_atom_env/domain/operations.py) |
| 几何 / holder / 逻辑 | [world/world.py](../src/neutral_atom_env/world/world.py)、[circuit](../src/neutral_atom_env/circuit)、[simulation/state.py](../src/neutral_atom_env/simulation/state.py) |
| 编译接口 / 单 trap / program | [simulation/pipeline.py](../src/neutral_atom_env/simulation/pipeline.py)、[planning/compilers.py](../src/neutral_atom_env/planning/compilers.py)、[motion/single_trap.py](../src/neutral_atom_env/motion/single_trap.py)、[motion/program.py](../src/neutral_atom_env/motion/program.py)、[motion/validation.py](../src/neutral_atom_env/motion/validation.py) |
| 动态 mask / AOD / Raman | [hardware](../src/neutral_atom_env/hardware)、[motion/raman.py](../src/neutral_atom_env/motion/raman.py) |
| 唯一实时提交 / 串行调度 / 恢复 | [simulation/executor.py](../src/neutral_atom_env/simulation/executor.py)、[simulation/scheduler.py](../src/neutral_atom_env/simulation/scheduler.py)、[replay/checkpoint.py](../src/neutral_atom_env/replay/checkpoint.py) |
| 交互 / 后台任务 | [visualization/workbench.py](../src/neutral_atom_env/visualization/workbench.py)、[workbench_server.py](../src/neutral_atom_env/visualization/workbench_server.py)、[workbench.html](../src/neutral_atom_env/visualization/workbench.html)、[workbench.js](../src/neutral_atom_env/visualization/workbench.js) |
| 共用观察与呈现 | [visualization/recording.py](../src/neutral_atom_env/visualization/recording.py)、[viewer.py](../src/neutral_atom_env/visualization/viewer.py)、[viewer.js](../src/neutral_atom_env/visualization/viewer.js)、[summary.py](../src/neutral_atom_env/visualization/summary.py) |

只有 Executor 提交实时状态，物理入口为 `Executor.submit(plan)`；compiler/validator/policy/renderer 仅推演或观察。Q 编号同时代表原子与物理比特，placement 是 holder 真值，world 是静态几何真值。不能扩大作用半径、放松间距或静默搬动伙伴来消除失败。

AOD 容量、完整几何、行列启用和占据分别建模；开启的空交点同样参与安全检查。所有完整轴间距严格大于 `max(1.01, min_axis_spacing)` μm，不因容量位置空置或关闭而删除几何约束。交接开始先建立目标支撑，完成前仍由源持有；完成事件才提交 holder 和支撑变化。关闭空阱的定位也必须计时。

旧 checkpoint schema 1–10 明确拒绝。即使是 schema 11，旧 5 μs Raman 硬件参数也不符合当前契约，须重编译，不能改写历史 trace 来“迁移”。旧 editor JSON 的废弃时长字段导入时丢弃，新编译固定 1 μs；旧 viewer 记录仍保留真实历史时间，Raman /2 记录要配当前 bundle。

## 4. 里程碑缺口与后续施工

| 阶段 / 问题 | 当前交接结论 | 下一步验收重点 |
| --- | --- | --- |
| M3-A / GAP-001、002 | 已修复并有串行证据 | 扩展时保留 masks、空阱 sweep、交接与恢复 |
| M3-B / GAP-004 | U3/别名串行部分已修复 | 参数化能力不能代表整个 M3-B 完成 |
| M3-B/C / GAP-003 | OPEN：仍以单 gate plan 为中心 | 零 gate 运输任务；prepare/pulse/cleanup 分开；独立目标、约束、资源、终态与唯一效果追溯 |
| M3-C / GAP-008 | OPEN：可支持布局族及通用持久续接未完成 | EZ SLM/loaded/异位空 AOD 起态、KEEP 后续接、RETURN_ONLY、新站点卸载与显式退出；安置所有附带原子 |
| M3-D / GAP-005 | OPEN：单 active_plan、整计划预约 | 稳定 SLM 1Q 与另一原子运输最小重叠；按资源区间释放、同时间事件及并发恢复 |
| M3-E / GAP-006、007 | OPEN：部分失败可见、协议可替换，完整验收缺失 | 两个实质不同混合 compiler，共用 validator/Executor/viewer；候选拒绝与最终失败分离、有限终止及诊断 |
| M3-F / GAP-009 | OPEN：动态图层已有，通用并发与大规模执行证据不足 | 数百原子声明规模的真实混合运行、并发显示、资源并集统计和独立端到端核验 |
| M4 / M5 / M6 | 未实现 | 按依赖推进优化比较、batch/更广并发、Gym/RL |

历史 BUG-001/002、EXT-001/002 和 META-001 的修复沿用 [审计登记](../instruction/model_audit.md)；本次文档任务没有新关闭任何运行时问题。

必须保留的负例：旧 rigid-parking 四原子六 CZ 在当前动态支撑规则下只完成前四门，G004/G005 因 `SHARED_AXIS_SUPPORT` 被拒绝，不能继续描述为完整六门成功。两原子及支持的整行场景与此区分；受限 KEEP_LOADED 终态示例不代表通用续接已经完成。

**下一条开发任务是 M3-B 独立目标任务/操作 IR。** 先读 [milestones](../instruction/milestones.md)、[compiler_contract](../instruction/compiler_contract.md)、[state_circuit](../instruction/state_circuit.md)，再从 operations/program/validation/Executor 入手。完成条件包括真实零门运输不改变 DAG、拆分前后 pulse 效果恰好一次、目标终态和资源可验证、失败无部分提交、各边界可恢复；保持现有 CZ/Raman 和 M3-A 正负例。之后才接 M3-C、M3-D，不能先用动画假装实现并行。

## 5. 验证证据分层

以下都是 **2026-09-10 历史结果**，本次只核对记录，不能当作当前源码完整回归。dateutil 的 `utcfromtimestamp` 弃用提示是历史已有 warning。

| 历史工作 | 已记录结果 | 证据及限制 |
| --- | --- | --- |
| M3-A | 全套 215 passed / 1 warning；追加两例后动态专项 16 passed；标准 8 原子 12 CZ，336 operations、696 commits、wall 18026.915473838395 μs | [日志](../instruction/logs/2026-09-10-m3-dynamic-traps.md)；追加两例后未再跑全套；有真实浏览器动态 mask/交接检查 |
| 首版线路工作台 | 最终全套 254 passed / 1 warning，397.06 s；混合线路、编辑及 Raman 真实浏览器检查 | [日志](../instruction/logs/2026-09-10-circuit-workbench.md)；当时仍用 5 μs，早于固定时长和随机按钮；HTML 下载/脚本解析通过，file:// 实际打开未验收 |
| 固定 pipeline / 1 μs / 32× | 相关 pytest 90 passed / 1 warning，43.60 s；Node 两种模式倍率、参数/holder/时长及 HTTP 通过 | [日志](../instruction/logs/2026-09-10-workbench-standard-pipeline.md)；6 原子 seed 7，4 门、26 operations、60 commits，wall 1163.2898987322333 μs、Raman 3 μs、3 LOAD/3 OFFLOAD；不是全套重跑 |
| 随机按钮 | 临时 Node VM/DOM 200 组覆盖 1/2/4/16/32 原子、保留初态/撤销/防抖；实际随机输入编译 completed | [日志](../instruction/logs/2026-09-10-random-circuit-button.md)；4 原子 seed 73 reverse，8 门、56 operations、128 commits，wall 2373.1290590000576 μs、Raman 6 μs、CZ 0.6 μs、6 LOAD/6 OFFLOAD |

固定 pipeline 和随机按钮两轮 CUA 均遇到 `nodeRepl.fetch request failed`，未完成那两轮真实浏览器视觉验收；离线替身与 HTTP 不能代替这一项。最近的全套 254 passed 早于后两轮变更，当前最终版本没有新全套结论。本次 HTTP GET 返回 200 且含随机按钮，只证明服务响应，不证明浏览器当前已加载新页面或交互外观正确。

## 6. 启动、复现与跨机器交接

在仓库根目录、Python 3.11+ 环境执行；本机核对的运行服务使用 Python 3.12。前端无 npm 安装要求。

```powershell
python -m pip install -e ".[test]"
python examples/circuit_workbench.py --port 8766
```

访问 `http://127.0.0.1:8766/`。本次只读核对服务可用，未重启；PID 不是跨机器约定。编译标准混合输入、进行相关机器与离线控制验收：

```powershell
python examples/compile_workbench.py --input configs/workbench/mixed.json --output artifacts/circuit-workbench-demo
python -m pytest tests/test_raman.py tests/test_workbench.py tests/test_foundations.py tests/test_visualization.py tests/test_dynamic_traps.py -q --tb=short
node tests/raman_controls.cjs artifacts/circuit-workbench-demo/index.html
node tests/viewer_speeds.cjs artifacts/circuit-workbench-demo/index.html
```

行为变更后按范围运行回归；完整机器回归为 `python -m pytest -q --tb=short`，六组代表性可视化验收为 `python -m pytest --visual`，报告 `artifacts/acceptance/index.html`。本段命令是接手后的操作入口，不是本次运行记录。

`artifacts/` 被 Git 忽略，跨机器不能假设存在。随机按钮的历史临时 VM 检查脚本未固化为仓库测试；下面保存其真实导出输入，以便不依赖随机重抽或本机产物。保存为 UTF-8 JSON 后传给 `examples/compile_workbench.py --input <文件> --output artifacts/random-circuit-check`：

```json
{
  "atom_count": 4, "layout": "shuffled", "seed": 73, "anchor_order": "reverse",
  "gates": [
    {"id":"G000","gate_type":"U3","qubit_ids":["Q001"],"parameters":[-2.5879,0.4856,-1.7432],"column":0},
    {"id":"G001","gate_type":"CZ","qubit_ids":["Q001","Q000"],"parameters":[],"column":1},
    {"id":"G002","gate_type":"H","qubit_ids":["Q003"],"parameters":[],"column":2},
    {"id":"G003","gate_type":"RY","qubit_ids":["Q001"],"parameters":[0.8922],"column":3},
    {"id":"G004","gate_type":"S","qubit_ids":["Q000"],"parameters":[],"column":4},
    {"id":"G005","gate_type":"CZ","qubit_ids":["Q003","Q002"],"parameters":[],"column":5},
    {"id":"G006","gate_type":"S","qubit_ids":["Q000"],"parameters":[],"column":6},
    {"id":"G007","gate_type":"X","qubit_ids":["Q003"],"parameters":[],"column":7}
  ]
}
```

### 本地源码与历史发布

本次 `git status --short` 仍显示项目整体未跟踪，`master` 没有本地提交，不能用空的 `git diff` 证明改动已记录；运行源码指纹见本次日志。

[2026-09-10 GitHub 同步日志](../instruction/logs/2026-09-10-github-sync.md) 记录曾向 `physics-Yu/QEC-schedule` 发布 105 个程序/使用文件，提交 `dcc849f7729bab38d4263b4cd31ea04fd5f4f29b`；内部 instruction、代理导航和参考资料未公开。本次未核验远端现状，不认定那次发布包含后续工作台、1 μs 或随机按钮改动。此次交接文件只写入本地，没有对外发布。

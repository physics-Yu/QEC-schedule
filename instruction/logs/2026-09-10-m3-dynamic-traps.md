# 2026-09-10 · M3 动态光阱与安全交接

- 状态：COMPLETED（本轮 M3-A；M3 整体未完成）
- 用户目标：按 milestone 和 handoff 继续 M3；先执行依赖前置 M3-A。
- 本轮范围：动态 SLM/AOD 启用状态、交接支撑、活动空阱安全、开关计时，贯通执行/恢复/观察端和 single_trap。
- 开始基线：schema 9；M3-A–F 尚未验收；工作区全部项目文件为未跟踪文件，保留原有内容，不提交。
- 相关规范：milestones.md、physics.md、motion_execution.md、workflow.md。

## 完成内容

- `domain/operations.py`：TrapState、TransferRuntime、TRAP_SWITCH、switch_duration_us、plan 起末 masks；`world/world.py`：稳定容量/几何与行列启用分离；`simulation/state.py`：SLM masks、holder 支撑检查、schema 10。
- `hardware/dynamic_traps.py`：纯 begin/finish 状态机、全活动交点 enable/sweep、共享行列关闭拒绝。rigid/row_column 沿用各自全段轨迹和严格完整轴间距，原子/SLM clearance 未降低。
- `physical_executor.py`、`runtime_validation.py`、`checkpoint.py`、`operation_codec.py`：Executor 在开始建立目标支撑、完成统一提交 holder/源撤去；恢复从起态重放支撑阶段；损坏 masks/transfer/时序原子性拒绝。
- `motion/program.py`、独立 validation 和三个旧 compiler：显式起末支撑与逐操作推演。single_trap 空载移动前检查并关闭活动 AOD；装卸本身记录实际光阱开关。空闲 SLM 候选允许由交接开启，不再将初始 enabled 当成永久可用性。
- `visualization`、静态 renderer：viewer /2 读取真实 masks/transfer；SLM 初帧及变化时记录，保持 512 原子静态帧的紧凑性；八类 schedule 新增独立开关，视图高度跟随类别数量。
- `examples/run_dynamic_traps.py`：一个 CZ 加两个独立开关，输出边界 checkpoint 并验证续跑、trace、回放与静态关键帧。标准十二 CZ 仍用原 JSON 输入单独运行。
- 更新当前 instruction、API 文档、日志索引和 handoff；保留所有历史日志与历史结果的原始含义。

## 验证

| 命令/检查 | 本轮结果 | 证据或关键数字 |
| --- | --- | --- |
| `python -m pytest -q --tb=short` | 215 passed, 1 warning；362.05 秒 | `artifacts/m3-final-tests.txt`；警告为 dateutil 的既有 utcfromtimestamp 弃用提示 |
| `python -m pytest -q tests/test_dynamic_traps.py --tb=short`（增加两个专项后） | 16 passed；19.24 秒 | `artifacts/m3-dynamic-final.txt`；没有把此后全套重跑写成事实 |
| 首轮全套 | 13 failed, 188 passed | `artifacts/m3-full-tests.txt`；已逐项修正初态夹具、enabled 真值迁移和旧物理预期，后续全套通过 |
| 中间基础/路径/观察端/M3-A 定向回归 | 99 passed, 1 warning | `artifacts/m3-targeted-tests.txt` |
| 标准 `compile_circuit.py`，single_trap，原八原子十二 CZ 输入 | completed | 336 operations，696 commits，18026.915473838395 μs；逻辑完成 17163.26724323606 μs；AOD/atom 路程 5411.657736919199/3502 μm |
| `python examples/run_dynamic_traps.py` | completed | 29 operations，1125.7213562373095 μs，独立开关 2 μs；`artifacts/m3-dynamic-traps` |
| `node tests/single_trap_controls.cjs artifacts/m3-single-trap/index.html` | PASS | 12 CZ；逐装卸真实双支撑、所有空载 MOVE 的活动数为 0、数据只读 |
| `node tests/viewer_component.cjs artifacts/m3-viewer-serial/index.html artifacts/m3-viewer-row-column/index.html` | PASS | 512 原子/257帧，分页、两组件隔离、cleanup；row_column 实际轨迹；120 次替身重绘 609 ms，不是 FPS |
| `node tests/schedule_controls.cjs artifacts/m3-viewer-serial/index.html` | PASS | 实际区间几何、三次短 pulse、鼠标/键盘跳转、游标同步 |
| 真实浏览器 CUA localhost | PASS（有界视觉验收） | 1 μs 开启数量 1/1；2 μs 关灯定位 0/1；12 μs 双支撑装载 holder=SLM；112 μs holder=AOD；八类表独立开关累计 2 μs |
| 静态 PNG 查看 | PASS | 查看 `aod_offload-supported.png`：源 SLM 关闭标记、EZ 支撑重叠、完成前仍为 mobile 菱形；没有为美观移动原子 |
| 当前维护文档本地链接与源码 UTF-8 检查 | PASS | 检查本轮 18 份维护文档的本地链接目标；src/tests/examples 的 Python/JS/HTML 均可按 UTF-8 读取 |

三门/row_column Node 数据用 `make_circuit_state()` / `make_row_column_state('incidental')`，`EagerScheduler.run(VisualRecorder.observe)` 执行，再经 recorder.write/write_json 生成 `artifacts/m3-viewer-serial` / `artifacts/m3-viewer-row-column`。512 帧输入由 `tests/test_visualization.py` 真实 WAIT 执行生成。源码 viewer 改动后，用 `visualization.viewer.write_html` 从本轮 recording.json 重建标准十二门 HTML；没有手改生成 HTML。

## 决策、旧预期迁移与物理范围

- 默认 AOD masks 全关是显式新初始启用语义，保持原位置、容量、间距及原子布局；旧 schema 1–9 不静默迁移。
- 独立开关默认 1 μs 是项目参数、可配置、未设备标定。交接开关包含在原 100 μs load/offload 中，所以标准十二 CZ 时间与旧基线相同，不能由相同时间推断未执行开关。
- world StaticTrap.enabled 只提供初值。旧测试通过改 world 关闭 occupied trap 已迁移到改运行时 SLM mask；新增/重建 world 的初始化夹具显式重建初始 mask，真实运行不自动重置。
- 旧 rigid-parking 六门四原子案例只能合法完成 G000–G003；G004/G005 对角捕获四颗后单颗 PARK 被 `SHARED_AXIS_SUPPORT` 拒绝。保留原输入，后续重复 run 不再推进/提交；不把原成功截图冒充新模型证据。双原子停车、四阱整行交接有正例。
- row_column 独立双 mobile 中途碰撞负例原来的对角 LOAD 在 4.3 μm 静态排斥半径下应被新交点校验拒绝；测试先验证该拒绝，再单独构造合法 loaded 起态验证整段双原子碰撞。此后半段不作为前述禁止 LOAD 的证据。
- 已声明 depart/approach 的清出端点契约保守保留；源 SLM 已关闭时普通 backend 运动不再假称撞上活动源 SLM，独立计划仍校验边界声明。
- 未引入光场/波包/保真度仿真或低层 ramp。transfer 的 target_supported→完成状态为包含稳定余量的粗粒度协议。

## 未完成与下一步

GAP-001、GAP-002、A-004 本轮 FIXED。GAP-003–009 仍 OPEN；GAP-009 仅动态 masks/交接/开关类别部分已完成。仍只有 CZ 物理计划、串行整计划资源预约，无通用 gateless/loaded 续接、U3/Raman、操作级并行、通用目标终态与两种混合电路 compiler 验收。没有多 AOD、数百原子真实混合电路、浏览器长时间 FPS/全尺寸验收。

下一步按 M3-B：扩展 PhysicalGate 参数和目标任务 IR，串行先验证无 gate 的 prepare/cleanup、独立 pulse 唯一门效果和显式终态，再接 M3-C/D 持久状态与最小并行。不能因 M3-A 已通过直接进入 M4 优化。

## 可复现信息

Windows PowerShell，Python 3.12，默认 seed=0，配置文件未改；物理阈值/时间除新增 switch_duration_us 外未修改。完整命令及产物入口见 [dynamic_traps](../../docs/dynamic_traps.md)；测试输出/HTML/PNG 在 ignored artifacts，可由源码重建。工作区项目文件原本均未跟踪，未创建提交或发布。

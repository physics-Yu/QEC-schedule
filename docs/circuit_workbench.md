# 可编辑线路工作台

2026-09-13 当前界面与API：见 [配置分层合同](workbench_configurations.md)。主界面为线路与回放，平台/编译配置独立管理；仅手动编译。`circuit_profile` 与 `compilation` 分离，调度选择含推荐/基线及按类别组织的九个重要内置预设；旧 `compiler` 实现继续兼容。

单台 AOD 多格点更新：初始条件可设置 AOD 行×列，总容量不超过 128；支持固定非均匀行列偏移，旧输入字段 `aod_traps` 继续表示 1×N（普通布局省略时为 1）；多格点须用 M4、行实验或二维 patch 策略 + adaptive EZ。新预设及联合运输定位见 [多 trap 说明](multi_trap.md)，不改变线路编辑与真实编译管线。

**当前门规则（2026-09-11 最新）**：仅 H/X/Y/Z/T/CZ 可执行；仅同类型门可并行，异类型门（含 CZ/1Q）不得重叠。内部 U 参数仅记录固定门效果。checkpoint 当前 schema 19，QEC 专用协议额外支持 MEASURE/RESET；旧快照应从输入重新编译。详见 [门规范](gate_contract.md)。本页旧门集和任意类型并行描述以该规范为准。

```powershell
python examples/circuit_workbench.py --port 8766
```

打开 `http://127.0.0.1:8766`。服务只监听 loopback，前端无外部依赖，不需要 npm。关掉服务后已有记录仍可回放，在线编译需要重新启动 Python 服务。

## 独立验收与连接排查

主服务每次只运行一个编译任务；验收脚本使用独立端口和产物目录，避免取消用户编译。先检查监听，再在单独终端运行：

```powershell
Get-NetTCPConnection -LocalPort 8766,8767 -State Listen -ErrorAction SilentlyContinue
python examples/circuit_workbench.py --port 8767 --output artifacts/workbench-http-check
```

保留服务终端，在另一终端运行 `node tests/m4_workbench_controls.cjs http://127.0.0.1:8767`。浏览器验收新开 `http://127.0.0.1:8767`；HTTP 脚本与浏览器的编译动作顺序执行，避免同一测试服务互相取消任务。进程启动后仍需 HTTP/浏览器检查。

工具仅返回 `blocked by policy` 时，不能据此判断具体审批原因或服务代码故障；保留原始错误与被拒绝动作。本轮正常命令已启动成功，未修改审批规则。浏览器若在枚举时返回 `nodeRepl.fetch request failed`，本轮通过重置 CUA 会话、随后用 `cua.getBrowser({url: 'http://127.0.0.1:8767'})` 选定内置浏览器并新开测试页恢复。此路径不保证解决所有连接原因；不要刷新持有未导出草稿的主页面。证据见 [连接恢复日志](../instruction/logs/2026-09-11-local-service-browser-recovery.md)。

## 固定维护 pipeline

本工作台是用户确认的默认可视化入口，后续修改应沿用“初始条件 → 量子线路 → 物理编译 → Executor → VisualRecorder → viewer”。维护源码位于 visualization/workbench.py、workbench_server.py、workbench.html/workbench.js 与共用 viewer；不另建跳过物理校验的动画路径。回放倍率为 0.25×、1×、2×、4×、8×、16×、32×，两种时间模式均支持，默认仍 1×。

## 使用

1. 先在“01 / 初始条件”展开选择原子数、layout、seed。AOD 与 EZ 保护在「配置管理 / 平台配置」，调度与预算在「编译配置」。新草稿使用 greedy + adaptive EZ，候选网格初始关闭，按门需求建立支撑和更换伙伴。单比特光操作固定 1 μs，无时长输入项。
2. 在“02 / 量子线路”选门工具后点击空位；CZ 在同一列选择两个不同 Q。点击已有 gate 编辑或定位执行。门工具仅 H/X/Y/Z/T/CZ；可编辑列与操作数，无可编辑角度。
3. 减少原子数前，先删除或重定向引用被移除原子的 gate。旧线路 JSON 中的 raman_duration_us 已废弃，导入时丢弃，重新编译统一采用 1 μs；新导出不再包含此字段。
4. 编辑只更新草稿和初态预览；仅点击量子线路卡片内的编译按钮运行，自动编译功能已删除。旧任务可取消，默认 90 s 超时后终止；输入 `compile_timeout_s` 可显式设置 1–86400 s，省略时采用服务 `--timeout` 设置；旧结果不能覆盖新输入。期间旧回放灰显并标明版本。
5. 支持撤销/重做、示例、线路 JSON 导入/导出、独立回放 HTML 下载。**浏览器草稿不自动持久化，刷新前请导出。** 回放下载对应页面标注的版本和完成/部分执行状态。
6. 配置管理中编译配置的“高级搜索预算”设置最大服务决策次数（包含归还）。编译停滞/失败会弹出原因摘要，正常停滞保留已执行片段，可下载失败记录 JSON、返回编辑后重试。进程超时/异常只保证保存输入和最后进度，不保证最终 checkpoint。

JSON 新字段：`ez_policy` 为 `adaptive` 或 `pair`，缺少字段仍采用旧双站点平台；`max_decisions` 为 1–10000 整数，默认 10000，legacy 不使用。新网格与旧 M3 平台族证明分开；精确候选验证和共享 Executor 保持。决策表显示具体 EZ 开/关及 Raman 时隙，细节见 [M4](milestone4_greedy.md)。

“02 / 量子线路”右上角的 **随机载入** 按当前原子数生成 4–12 门的新线路（min(12,max(4,2N))），保留原子数、layout、布局 seed 和搬运次序。单原子仅生成单比特门，多原子至少包含 H 与 CZ；其余从 H/X/Y/Z/T/CZ 抽样，每列一门，无角度参数。可继续编辑、撤销/重做或导出 JSON 保存实际线路。每次点击重新随机，布局 seed 不控制 gate 抽样；随机载入后等待手动编译；编译任务保留取消和版本隔离机制。随机 gate 合法不代表任意布局的有限物理路由必然成功。

列表示每条线上的逻辑先后，同列无共享原子的 gate 没有依赖。greedy 在实际 MOVE 窗口填充连续 READY Raman；legacy eager 对照仍串行。列号不是时间或 barrier。

## 物理执行与参数

`visualization/workbench.py` 建立确定性 platform/placement/PhysicalCircuit，按 compiler 选择 M4/M3/legacy，再走 `ProgramBuilder/独立 validator → Executor → VisualRecorder`。浏览器不写 holder、不生成替代路线。

- CZ 运输使用配置的 AOD 行列交点，受已有策略能力族限制；greedy/resident 可持续驻留并复用，returning/legacy 提供往返对照。各策略保留 clearance、作用距离、动态 masks、交接、活动空阱 sweep 与有限候选限制。
- `PhysicalGate.parameters` 保存原参数，`u_parameters` 返回规范 U(theta,phi,lambda)。domain 保留旧门的数学表示用于历史解析与诊断；当前 UI/物理执行只开放 H/X/Y/Z/T/CZ。CZ 无参数；CPHASE 需一个角度但仍拒绝物理执行，MEASURE/RESET 在专用 QEC profile 下具有真实量子读出与复位实现。
- `RAMAN_ROTATION` 是独立计时操作，只允许存活、未测量、已启用且稳定 SLM / 静止 AOD 承载的目标，且与任意其他存活原子间距 ≥5 μm（含 5）；未完成交接或不在寻址区域时拒绝。hardware 的 `raman_zone_types` 默认 storage、entanglement。
- 每个 qubit 独立的 `RAMAN:Qxxx` 资源，预约目标 atom 和 SLM site；M4 同时安排不同 qubit 的同类型单比特门，并与无冲突运输/交接重叠，M3/legacy 保留原基线策略。单比特光操作按用户确认固定 `raman_duration_us=1` μs；该字段仅保留在硬件序列化中用于审核，HardwareConfig 拒绝其他值，不是可选配置。H/X/Y/Z/T 均使用固定时长，没有免费虚拟 Z；不同门类型的作用区间不可重叠。
- 实际操作开始才 RUNNING，完成时提交一次 COMPLETED。trace 保存原门、规范 U 参数和 gate/plan/op 追溯；普通模式研究调度/运动学；QEC 模式跟踪 Clifford 量子态与声明的测量/噪声事件，仍不模拟光场。别名整体相位约定见 [state_circuit](../instruction/state_circuit.md)。
- `raman_busy_time_us` 不加入 AOD busy 或 CZ laser busy。回放实际出现 Raman 时新增一行，旧 CZ 记录保持八类；legacy 串行 summary 拒绝重叠；M3/M4 scheduled 记录按每资源区间并集汇总。

checkpoint 当前为 **schema 19**，包含并发操作、量子读出、逐 qubit Raman 资源和恢复字段。旧 schema 的 checkpoint 需重新编译，不能篡改历史 trace 时长来恢复；已有旧 viewer 记录仍如实播放原时间。viewer 保持 `neutral-atom-view/2` 并新增参数元数据；Raman 记录须用本轮或更新的 bundle。1Q 弧线表示真实操作进度，坐标/holder 不变，不绘制虚构的 CZ 连线。

## 布局、规模与里程碑边界

SLM 站点间隔 10 μm、候选网格 5 μm，全体原子初始在 SZ。单行沿 x 递增；网格每行 `ceil(sqrt(N))` 个站点；随机映射使用同一网格和 `random.Random(seed)` 打乱 Q→site。两处空 EZ SLM 是局部作用位候选。layout 改变是显式输入，不在失败后偷挪原子。

输入上限 128 原子、4096 门、4096 列是可编辑容量，不保证该规模任意电路成功或在时限内完成。编辑器每页最多渲染 64 列，支持前后翻页与绝对列跳转；导入/导出保留整条线路，HTTP JSON 上限为 2 MiB。证据覆盖三种四原子 CZ、六原子混合电路和一原子/空线路；有限路由不证明完备或全局最优。forward/reverse 是同一 compiler 的优先次序，不能关闭 M3-E 的两个实质不同实现要求。

空线路成功只表示没有任何任务。M3-B 已有独立 TaskIntent/TaskProgram 的零门运输和拆分执行，见 [任务 API 与复现](task_program.md)；工作台新草稿默认 M4 greedy，旧 resident / returning / legacy 可经历史 JSON 精确导入；旧无 compiler 字段导入保留 legacy。M3-C–F 已实现，支持范围与返修点见 [M3](milestone3.md)。

## API、产物与复现

- 前端：`visualization/workbench.html`、`workbench.js`；共用 viewer。
- `workbench.py`：`validate_input` 返回规范输入，`build_inputs` 返回 input/circuit/platform/placement，`compile_input` 返回 `(result, final_state)`。
- `workbench_server.py`：`POST /api/preview`、`POST /api/compile`、`GET /api/jobs/{id}`、`GET /api/jobs/{id}/result`、`POST /api/jobs/{id}/cancel`。限定 JSON 大小和 Host/Origin，没有任意文件读写路由。
- 每服务一个活动编译，后提交任务取消前一个，包括从其他页面提交的任务。内存保留最近八个任务，所有任务使用 UUID 标识。
- 正常完成与 stalled 保存 `artifacts/workbench/{job_id}/input.json`、`recording.json`、`checkpoint.json`（包含 trace）、`diagnostics.json`。取消/超时只保留已上报进度，未保证可恢复 checkpoint；完成产物不会自动删除。
- `stalled` 显示已执行片段及结构化诊断，不能视为完成。失败/旧记录均明确标记。

```powershell
python examples/compile_workbench.py --input configs/workbench/mixed.json --output artifacts/circuit-workbench-demo
python -m pytest tests/test_raman.py tests/test_workbench.py -q
node tests/raman_controls.cjs artifacts/circuit-workbench-demo/index.html
```

六原子随机映射，seed 7，H(Q000)、CZ(Q000,Q001)、U3(Q001)、H(Q005)：4 门、26 operations、60 commits、wall **1163.2898987322333 μs**、Raman **3 μs**、3 LOAD/3 OFFLOAD。此执行次序来自当前 gate ID 和 DAG，不是操作级并行。

当前固定 pipeline 与时长/倍率证据见 [日志](../instruction/logs/2026-09-10-workbench-standard-pipeline.md)；原工作台浏览器证据保留在 [历史日志](../instruction/logs/2026-09-10-circuit-workbench.md)。


## M4 贪心入口

默认示例为「贪心验收 · 连续 Raman / CZ 复用」。`compiler=greedy` 调用 `run_m4`，result 增加 `decision_log`；服务器保存 `decisions.json`，页面在回放上方显示可展开决策表。候选、预算、完成数据及浏览器工具限制见 [M4 文档](milestone4_greedy.md)。旧草稿编辑后仍保留旧动画并标记版本过期，只有对应版本编译成功才替换。

2026-09-11 纠正验收：工作台新增“四门 / 1 μs”并行预设；资源图逐 qubit 分行，同刻脉冲分别显示。M4 所有移动采用 2.5+5k μm 的正交通道及不超过 2.5 μm 的端点接入段。checkpoint 已升为 14；旧回放可读，旧 checkpoint 从输入重新编译。见 [本轮日志](../instruction/logs/2026-09-11-m4-parallel-orthogonal.md)。


## M4 新增输入与诊断

可选字段 `ready_limit`（1–128，默认16）、`site_limit`（1–128，默认4）、`lookahead_depth`（1–8，默认2）、`beam_width`（1–32，默认3）、`rollout_budget`（1–4096，默认12）；所有值须为整数，导入/导出保留。`compile_seconds` 为编译 wall time，真实总完成时间仍来自recording。前瞻表显示实际使用节点、实际截断和端点评分；原始决策详情保留actual_depth、terminal_cleanup、remaining_lower_bound、候选拒绝原因。达到数值预算不一定表示有搜索遗漏，`limit_reached` 与 `budget_exhausted` 分开。


## 大规模行实验入口（2026-09-11）

“4 逻辑比特 GHZ”按钮从 `GET /api/examples/surface-ghz` 载入可编辑的 36 原子、194 个 H/CZ 门输入；只有点击才替换当前草稿，可撤销。2026-09-12 该模板改为下方二维 patch 平台，旧行实验保留为对照。`row_symmetric` 与 `row_greedy` 分派到 `simulation.row_greedy.run_row`，分别使用对称逐门服务和下界剪枝行服务；不替换原 M4 四策略。两者要求整行 SZ 初态、10 μm 占据间距、覆盖整行的单台 rigid AOD 与足够 EZ 行空间，世界候选格点仍为 5 μm。平台不符返回结构化失败，不能静默换布局。

行实验可配置 `row_candidate_budget`（1–65536，默认4096）与 `route_expansions`（1–1000000，默认100000）。结果及 `run_options.json` 保存实际调用预算；页面兼容行服务的构造数、下界剪枝数和本步候选覆盖声明。时限每任务独立，持续上报进度也不能绕过时限；超时报告保留实际时限和最后进度。例子的长时限不改变常规服务默认。

交付链接 `/?example=surface-ghz` 从真实 API 载入实验，并等待用户点击编译。`/?job=<32位任务ID>` 从同一服务读取已完成或 stalled 的输入与实际回放，仍可继续编辑和重新编译；载入不会重新执行物理任务。过期、缺失或无结果的任务会显示失败并保留当前草稿。任务链接采用服务现有最近八项结果保留规则，服务重启后不能依靠此链接恢复内存结果，持久复现使用导出的输入与记录文件。

本轮接口验证：`tests/test_workbench_large.py` 覆盖容量、4096 门完整往返、大于旧 64 KiB 的真实 HTTP 预览、行平台失败与实际子进程时限覆盖；`node tests/workbench_large_controls.cjs` 验证真实编辑事件处理器的分页和大线路修改、行日志与预算，使用 DOM/HTTP 替身，不等于浏览器或完整表面码物理验收。完整实验结果以本轮实验报告为准。


## 二维 patch 和固定非均匀 AOD（2026-09-12）

`layout=surface_patches` 要求36原子：每块9个编号连续原子，块号 `b=q//9`，块内编号 `i=q%9`，坐标为 `(40*(b%2)+10*(i%3), 40*(b//2)+10*(i//3)) μm`。四个3×3块按2×2排列，块内10μm间距、相邻块边缘相隔20μm，保持真实二维排列。EZ有5μm候选格点，可容纳完整布局平移 `y−100μm`；不通过展开成单行规避二维运输。

新输入 `aod_rows`、`aod_columns` 必须同时给出，总乘积≤128；若同时保留旧 `aod_traps`，必须等于该乘积。`aod_row_offsets_um` / `aod_column_offsets_um` 为从0开始的有限严格递增坐标，数量分别等于行/列数；仍须通过硬件最小trap间距校验。surface默认6×6，每轴 `(0,10,20,40,50,60)`，36个交点匹配四块原子。可通过非均匀固定间距隔点捕获；开启的行和列产生全部笛卡尔交点，不能忽略附带原子或活动空交点。

界面可直接编辑行列数与两组坐标；改旧“总容量”输入会显式回到1×N并清除原二维偏移。本轮使用固定几何的rigid平移，不声称在移动中改变间距。`patch_symmetric` / `patch_greedy` 调用 `simulation.patch_greedy.run_patch`；具体并行与完成结果须以实际Executor记录和独立验收为准。

四邻格停车保护字段 `ez_neighbor_guard_enabled` 默认True，surface实验模板显式False，可在初始条件勾选切换。该选择随输入、硬件、checkpoint保存；关闭只影响离散四邻格停车策略，所有碰撞、支撑、光照和门作用条件保留。新测试 `tests/test_workbench_patch.py` 验证二维坐标、EZ可容纳性、非均匀几何、旧输入兼容和开关恢复/热缓存边界；不把接口测试称为完整并行物理实验完成。

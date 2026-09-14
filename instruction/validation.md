# 验证、诊断与产物规范

用途：设计测试、运行验收、修改快照/报告/指标时读取。视觉编码另见 [visualization](visualization.md)。

## 1. 按行为验证，而不是按文件复制图片

先写清输入、要验证的因果关系和独立预期，再选择工具。机器断言负责正确性，少量真实场景负责空间/时间人工理解，trace/snapshot 负责复现。旧 architecture §65–79 中“每条测试都必须配图”已被用户后续决策替代。

纯逻辑 DAG、序列化、不可变性可以只运行机器检查。物理行为通过有区别的场景呈现；KEEP 终态已有受限测试，不能据此声称通用跨计划 KEEP 或测量动力学已实现。静态图不伪装成完整动画验收。

## 2. 当前命令

```powershell
python -m pytest -q
python -m pytest tests/test_milestone1.py -q
python -m pytest --visual -q
python examples/run_single_gate.py
python examples/run_circuit.py
python examples/build_acceptance_report.py
# 先生成 M1 报告，再用 Node.js 验证回放控制（DOM/Canvas 替身）
node tests/replay_controls.cjs
python examples/run_reconfigurable_aod.py --backend row_column
python examples/run_reconfigurable_aod.py --backend rigid
node tests/replay_row_column.cjs
```

`pytest --visual` 生成 M0 六组报告；M1/M2 报告用 `run_single_gate.py` / `run_circuit.py` 独立生成。普通 pytest 更新 `artifacts/acceptance/machine-tests.json`，不代表同轮已重建所有回放。

## 3. 当前覆盖与未覆盖

| 范围 | 已有证据 | 不应推导的结论 |
| --- | --- | --- |
| M0 状态/DAG | 不可变更新、依赖、错误、hashseed/跨进程恢复 | 所有物理事件入口都安全 |
| M1 物理流程 | 单静态伙伴、附带原子、实际 pair、全段路径、卸载、计划过期/篡改 | 任意布局或全 storage 路由 |
| checkpoint | 每个合法 M1/M2 边界恢复一致，损坏事件、游标、预约、位置等负例拒绝 | 协同伪造全部 checkpoint 字段也能检测 |
| 静态渲染 | 共享 scene、主题、关键帧人工查看 | 浏览器响应式排版已验证 |
| 回放控制 | Node 中 DOM/Canvas 替身检查 | 真实浏览器鼠标/触控/字体/布局都通过 |

当前新增复现见 [审计日志](logs/2026-09-10-audit.md)。已存在测试全绿不能否定已证实的缺口。

## 4. 物理测试的独立预期

- 刚性：移动前后同阵列原子相对距离不变；静态伙伴全程不动。
- 连续：非 SLM pulse 坐标真实显示；独立时间点的插值与段速度一致。
- 捕获：requested/captured/incidental 分别核对；不能依据输出计划自行计算“期望”来循环证明正确。
- 安全：负例在段中途碰撞但端点安全；额外 pair 来自未请求原子；卸载目标冲突/禁用/未对齐。
- 原子式提交：失败前后的 snapshot/queue/trace 一致。
- 时间：duration 与硬件模型一致；门开始/完成、逻辑后继释放、返回结束分别核算。
- 恢复：每种合法 runtime 边界及相应缺失/错序/错属事件的损坏变体。

参数不合理与 planner 能力不足必须分开诊断。不能改半径、速度或初始伙伴位置来维持原测试数字。

## 5. 失败与报告

`ConstraintViolation` 当前字段是 code/message/atom_ids/holder_id/position，不是旧示例中的任意 resource_ids/metadata。新增字段需更新序列化和 UI。

失败报告包含触发输入、错误码、对象与可定位的几何/阶段。overlay 来自验证器，不能手绘一个与异常无关的位置。编译拒绝不改变运行 state，不应伪造 operation trace；其诊断与执行 trace 分开保存。

报告开始时先替换旧 PASS 页面；失败后不能继续展示旧成功图为本轮证据。现有 M1 生成器若中途失败停留“生成中”，仍需查看命令退出状态；未来应完善通用失败总览，不声称所有失败都已有图形详情。

## 6. 回归与证据留存

2026-09-11 M4 性能升级：scheduled runtime 使用有界的独立期望前缀缓存，避免每个事件从计划起点重新重演。缓存键包含完整计划和物理环境，每次仍校验 trace、当前状态和 pending；不是跳过验证或缓存通过标志。精确 trace 文本只读解析缓存、内部状态 fork 的隔离与热缓存损坏负例见 `tests/test_runtime_prefix_cache.py` / `tests/test_search_state_fork.py`。外部 checkpoint 恢复仍保留完整计划审核。证据与范围见 [升级日志](logs/2026-09-11-m4-compiler-upgrade.md)。

优先比较结构化状态、scene、trace、metrics 与轨迹几何；像素差异仅作为字体/绘图库环境允许容差的辅助。代码变化后运行对应测试；文档变化检查链接、锚点、归档哈希与来源覆盖即可。

产物放 `artifacts/`，它在 `.gitignore` 中，不作为跨机器唯一交接证据。日志保留关键命令、数字和可重建路径；用户已有产物不批量删除。

运行环境版本与配置会影响数值或像素结果。基准参数、seed、场景 ID 和源码指纹应随实质验收记录；缺少证据的项目标为未验收。

## 7. 一次改动的停止条件

相关检查通过且没有新增风险后，继续交付与日志更新，不无限重复全套测试。若失败，先定位本次变更还是既有问题，再记录或修复；不能把修改 expected output 当作默认修复办法。

## 8. M3 新契约验收矩阵（M3-A 已验收，其余待实施）

正式范围见 [milestones](milestones.md)、[compiler_contract](compiler_contract.md) 与 [physics](physics.md)。分四类独立核对：逻辑门及参数/依赖，物理状态/动作，时间/资源，以及程序终止条件。动画只观察上述结果，不能代替验证。

| 验收 | 必须具有的独立预期/负例 | 对应缺口 |
| --- | --- | --- |
| 活动集合 | 2 行×2 列产生 4 trap；关闭共享列影响整列；零活动不删除容量/重编号 | GAP-001 |
| 交接 | 格点对齐；完成前源 holder、完成后目标；无无支撑区间；轴上残余原子时拒绝关闭；时长含稳定不双计 | GAP-002 |
| 空阱安全 | 活动空阱两端安全但途中穿过静态原子必须拒绝；显式关闭后的合法定位通过；重新开启产生交点冲突拒绝 | GAP-002 |
| 非 gate 任务 | 仅移动/停车/归还不改变 DAG；拆分 CZ 的 pulse 只完成一次；附带原子全量记账 | GAP-003 |
| 持久起态 | EZ SLM、loaded、空 AOD 异位继续；KEEP 后下一门与显式退出；不同卸载目标，拒绝无法安全启用或占位冲突的目标 | GAP-003 |
| 混合门集 | 参数非有限/缺失/arity 错误拒绝；U3/别名矩阵等价按声明整体相位独立核对；参数在 trace/恢复中保留；CPHASE 不冒充 CZ | GAP-004 |
| 最小并行 | compiler_contract 示意区间的独立总时间；SLM 1Q/他原子运输可重叠，同原子交接/运输不可重叠；Raman 容量限制 | GAP-005 |
| 时间与恢复 | 同时间完成/开始顺序确定；并行轨迹相遇拒绝；所有新增开关/交接/并行边界可恢复，缺失/重复 completion 拒绝 | GAP-001/005 |
| 终态与成本 | 门已全完成但必需归还未完不得成功；busy 取每资源区间并集，类别重叠不冒充 wall；相同终态公平对比 | GAP-005 |
| 失败出口 | 内部候选拒绝可继续；最终耗尽/已选计划非法终止、非成功退出、可见诊断；保留原状态与证据 | GAP-006 |
| 替换与构造 | 同一支持输入和终态经两个实质不同 compiler 共用校验/执行/回放；声明布局族内逐门恢复构造 | GAP-007/008 |
| 可视化规模 | 真正 masks/交接/并行从 trace 回放；固定资源/类别行保留先后与重叠；数百原子编译耗时、产物大小、交互测试分开报告 | GAP-009 |

共享 validator 必须独立推演实际操作图，不能调用默认 compiler 重新生成同一答案来证明正确。比较两个 compiler 时不能一个暗中使用不同初态、平台能力或终止要求。当前 legacy_eager 与 single_trap 注册名同时存在不自动满足同一混合电路替换验收。

失败报告新增任务/操作/资源、候选预算等字段时同步错误类型、序列化和 UI；当前 ConstraintViolation 字段并未自动扩展。计划被选中后校验失败不得吞掉后继续执行；候选生成期间的正常拒绝不伪造为已执行操作失败。

此前调度契约文档轮仅检查文档，不代表运行时验收；M3-A 当前运行证据另列如下。


M3-A 已按上述动态光阱条目验收：全量 215 passed，后补两个专项后的 M3-A 16 passed；另有 Node、静态图和真实浏览器支撑切换检查。恢复/完整受影响集/关灯计时证据见 [本轮日志](logs/2026-09-10-m3-dynamic-traps.md)。其他 M3 条目仍待验收，不把 CZ 串行基线外推为混合电路或并发完成。

## M3-C–F 当前验收入口

`tests/test_m3.py` 覆盖持久终态/置换、不同 compiler、真实重叠与资源释放、每事件边界恢复及继续、同时间确定性、未来操作篡改和有限失败出口。`examples/run_m3.py` 生成 mixed / 256 原子输入与全部证据，`examples/verify_m3.py` 不调用 compiler，重放实际 plans 并独立检查门覆盖、时序/资源冲突和最终归还。Node `tests/m3_controls.cjs` / `viewer_speeds.cjs` 检查并行动画及 32×；浏览器视觉验收单列，工具中止不记 PASS。具体命令与结果见 [M3 日志](logs/2026-09-11-m3-completion.md)。

# QEC 在完整计划边界续编译的只读预案

后续状态：该预案已在第二次完整尝试timeout后实现为显式 `run_qec_joint(..., resume=True, terminal=原始完整终态)`，四块wrapper透传。77项相关检查通过，实际1588槽检查点已成功续至1868槽；独立全轨迹重放及可编辑UI均已通过。当前合同见 [续编译验收](qec_temporal_four_resume_attempt3.md)。以下保留当时的只读设计与限制，不表示当前仍未实现。

2026-09-12。当前四patch完整编译运行期间的只读设计：未修改src、未执行测试、未终止或暂停父任务51159。目标是在明确持久化的完整计划边界继续生成后缀，避免超时后从1868槽初态重新开始；不是任意中途操作恢复、策略热切换或更换原电路。

## 最小接口

建议 `run_qec_joint(..., resume=False, terminal=None)` 增加严格bool显式选项，由 `run_qec_temporal_four(..., **options)` 原样转发。resume默认False，旧初态行为不变。resume=True必须提供从**原初态**派生并留存/从同一input重建的完整 `TaskTarget`，包含所有原子原SLM holder、原始AOD configuration和trap masks；缺失时拒绝，绝不能调用 `initial_terminal(resumed_state)` 把工作区误当终态。

原input、circuit/world/hardware指纹与terminal应由恢复manifest绑定，恢复到同一compiler实现、候选顺序、candidate_budget、route_expansions。manifest记录checkpoint指纹、完成计划数/决策序号、前缀日志路径、原尝试wall time与新后缀预算。只需创建原input的初态来验证这些静态合同，不需要先运行原前缀。`SimulationState.restore` 的既有校验保持，不能改成直接反序列化绕过；它会审查trace一致性及最后计划，不等于从第一份计划重新执行完整编译。

## 可接收的严格边界

- 最新持久化trace事件必须是 `PLAN_COMPLETED`，event time与当前time一致；version、trace和checkpoint通过现有restore/runtime校验。拒绝初始空trace被冒充续编译。
- event_queue为空（**保留next_sequence**）、active_plan=None、transfer=None、reservations为空、AOD不在运动中；无READY以外的悬挂RESERVED/RUNNING门。拒绝任何部分MZ服务、装卸或MOVE边界，不尝试在此入口drain未完成计划。
- quantum_state存在，68原子身份及alive状态、DAG、RNG、true/reported trace与测量状态保持原样。未完成普通门编辑、噪声元数据、axis、hardware等不能在恢复入口悄悄替换。
- 对本策略，除明确已完成原终态的幂等返回外，全部原子必须处于此前完整stage得到的EZ工作布局：STATIC在对应工作SLM，MOBILE在其关闭的工作SLM上方且静止。仅“在EZ内”不足以证明是同一初始stage位置，建议从首次成功stage计划的 `predicted_placement`/manifest保存的working map核对；不要对当前布局重新调用 `patch_assignment`，它会将当前占据视作障碍而寻找另一个布局。
- 原终态已经全部达到且DAG完成，可验证后直接返回。DAG完成但仍在EZ或仍loaded则是合法的待cleanup边界，必须继续执行release/restore，而不是沿用当前函数顶部 `if dag.completed: validate_target(); return` 导致误拒绝。

最窄适用范围是由当前qec_joint/PartitionedCohortCompiler自己产生、留有同一input来源的checkpoint。新入口不应宣称可从任意合法但不同策略产生的EZ排列续跑并复现同一路径。

## 无状态修改地恢复 retained cohort

当mobile_occupancy为空时，局部变量cohort=None。否则：

1. 从真实 `mobile_occupancy` 获取所有移动原子与**现有**cell；按atom_id排序，保持 `PatchArrayCompiler.bindings` 的原始顺序。不能按cell重新分配或仅取下一个CZ的部分原子。
2. 对每个原子用当前AOD配置计算cell位置；在world中寻找这个位置对应的唯一静态SLM。该SLM必须是该原子的工作位置、未占据且关闭，位置比较沿用backend既有容差，不能移位/舍入坐标来强行匹配。没有或多于一个候选、支撑开启、目标被占据均拒绝。
3. 构造 `CaptureBinding(atom_id, existing_cell, source_slm_id)` 与 `RetainedCohort(tuple(bindings), state.aod.pose)`；调用现有 `validate_cohort(state, cohort)`。再用工作map核对每个来源。该方法本身只检查pose/complete mobile set/source SLM off，不能替代前两步的唯一坐标、区域和来源检查。
4. 不新增LOAD、OFFLOAD或RNG事件，不开启/关闭trap，不修改placement、DAG或trace。后继真正release或CZ仍经原ProgramBuilder、backend及Executor。

`pulse` 每次完整服务都回到捕获坐标，`release` 真正卸载，readout服务完整返回EZ，因此上述恢复有明确构造基础。回调发生在PLAN_COMPLETED而局部 `cohort=new_cohort` 赋值尚未执行时也可从已提交state恢复；无需把Python闭包局部变量塞入checkpoint。

## 128位历史检查的恢复边界

四patchwrapper的局部checked标志不应持久化为可信真值。resume时若所有128项reported均存在，立即重新调用 `validate_history`；后续每次TEMP4_CORR_ READY仍保留原guard。若尚未齐则等待完整提交，任何提前READY纠正仍拒绝。

当前wrapper只在新事件观察和READY纠正时检查。若全部纠正已经完成，仅剩terminal甚至终态已完成，新启动的checked=False可能从未置True并错误抛出 `INCOMPLETE_SYNDROME_HISTORY`；启动检查解决这一特例，也防止把已完成但不受支持的历史悄悄接受。只读state的reported；不得用真值或fault元数据补位。

## 与不中断执行是否完全一致

有条件可复现下一计划及物理/量子后缀。现有策略的路径选择依赖state、READY顺序、固定候选预算与本地cohort；compiler对象只携带固定planner配置，没有跨门隐藏优化状态。cohort按相同sorted atom绑定顺序恢复后，版本/time/queue序号/RNG/trace均保留，ProgramBuilder的fingerprint、task id和计划id应与不中断执行一致。候选缓存只影响wall time，不应改变操作序列。

在cohort释放后、下一个pulse前或readout前的PLAN_COMPLETED边界重新进入主循环，也应选中同组：释放不改变DAG或几何工作坐标，原reference正是这个卸载视图。但这是需要测试的判断，不能仅据静态阅读宣称所有字节已等价。

决策日志的 `decision`、retained/reuse/flush/readout_saved统计和compile_wall_time不在SimulationState内。它们不能凭重新初始化的零计数冒充整次运行。保留前缀日志；后缀log可用manifest offset统一编号，summary由完整合并条目重算。仅checkpoint和计划trace已有时，可以重建部分执行统计，但失败候选诊断及实际编译wall time无法从trace完整恢复，必须明确缺失，不能编造。前后两段wall time、预算和中断原因分别公开，总编译时间合计，不能称为仍在原3600秒内一次完成。

## 最小验收集合

使用短真实物理线路分别做不中断执行及断点恢复，至少包括：stage完成；CZ保留cohort完成；loaded同型Raman完成后下一CZ复用；cohort真实release完成后下一不同组CZ；一次带报告翻转的MEASURE+RESET返回；128位完整且最终条件尚未做；最终条件已完但仍loaded/EZ；终态已完成幂等返回。

逐例比较恢复时snapshot完全相等、下一份plan的完整canonical内容相同，以及最终snapshot/trace/RNG/true&reported/实际条件门/物理时间与原始terminal相同。再在独立进程和冷缓存运行至少一个例子，证明不是借用内存中的cohort；callbacks/recorder不应影响物理计划。测试在PLAN_COMPLETED回调保存checkpoint，不需要先重放该前缀才能调用resume。

预声明负例：resume缺terminal或错误input/terminal；非bool选项；空trace/末事件不是PLAN_COMPLETED；非空queue或reservations、active_plan/transfer、moving AOD；原子在MZ/SZ或错误工作SLM；source SLM无匹配/多匹配/开启/被占据；cell缺失或cohort不完整；损坏DAG/量子/RNG/checkpoint；缺128历史且纠正提前READY；完整未知历史。失败前后state snapshot必须完全一致，不能借失败路径执行offload清理。

## 录像与缓存

可以在已经要求执行的完整compiler-free trace验证中生成从最初态到最终态的VisualRecorder，避免继续规划前专门重放前缀。恢复编译仅记录后缀的新PLAN_STARTED/操作到已有trace，原前缀不截断、不重新append；验证器逐份执行保存计划并对最终snapshot逐字比较，录像与所有阶段由这一条真实重放产生。

本次只读时，磁盘 `snapshot_encoding.py` 缺省已是16384 records/768MiB；正在运行进程采用何值取决于它启动时导入的版本，不能据磁盘新值推断该进程。无论8192或16384，cache容量是性能限制，不是trace正确性或checkpoint长度限制：超出的后缀仍编码，只是反复工作可能变慢。恢复也不会缩短真实trace，冷启动首轮会重新填缓存。不要以删历史、改version、修改snapshot结构或关闭校验来规避开销。

本预案未实施。若现有full run按预算完成，无需为这个备用能力打断它；若确需续编译，应在新的显式尝试中实现最小入口并先通过上述边界对照，再续接已落盘的最后完整checkpoint。

后续按主任务指令仅新增未来 `tests/test_qec_resume.py`，未执行：普通两原子row/adaptive/1×2 AOD，显式量子态，H0/H1/CZ/H1/CZ；模块fixture拟一次不中断执行捕获stage、retainedCZ、retained后H、DAG完成待归还、已归还五种边界，恢复时比较完整最终snapshot及每份后缀plan。另有缺terminal、活动queue/transfer、非EZ和保留来源未对齐/仍开启的原子式拒绝。该文件需要未来显式resume实现，当前源码不支持，不能把未运行测试说成PASS。

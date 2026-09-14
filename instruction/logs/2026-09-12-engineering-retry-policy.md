# 工程修复自主推进与4A界面续验

状态：IN PROGRESS。

用户原文：我觉得这种你就不用喊我来审批了，你要审批的是物理层面可能出错或者大框架上需要修改的地方才找我

2026-09-12 最新用户审批边界：测试脚本、界面交互、序列化和一般工程缺陷可自主修复、记录并重新验收；不再因这类失败请求审批。只有物理模型/物理事实可能出错、需要改动物理硬约束，或整体架构需要调整时才暂停相关方向，给出事实与方案并请求用户批准。不得放宽物理条件、掩盖失败或以改断言冒充通过；保留每次尝试证据。此规则取代此前“任何正式失败都需审批”的规定。

attempt2失败及三个导出保留；记录用户授权，新建attempt3。仅改脚本事件为自然失焦提交，强断言保留。使用8785保存481结果，不重复矩阵编译。前三步和矩阵证据沿用已通过结果，本轮待真实UI重验。

4A attempt3全部PASS：自然Tab提交后一次undo精确恢复，完整481保存结果双32×归还全部原holder/坐标，真实编辑六门编译1307.6μs，各效果一次，page_errors=[]，源码运行期间未变。证据step4-attempt3-ui/browser-acceptance.json。4A完成，按原合同开始4B受限时域纠错实现；4C未开始。

4B新增readout_flip真实投影/报告分离及历史guard，接入qec_temporal可编辑profile。核心57项PASS4.62s，root26接口/联合策略回归PASS3.28s，协议222项PASS82.62s（211事件）。看板恢复后自动关闭旧弹窗单项真实浏览器PASS2.07s。完整物理首次代表已启动session79679，916槽，round2_X0_0报告翻转/seed7，1800秒编译+独立重放分别预算，源码冻结。4C只读设计不作为通过证据。

4B完整首次物理编译PASS：916/916，46463.3μs，88装卸，256plans/3658events，80MEASURE/RESET，Raman72μs。round2_X0_0真0/报告1；global history支持且decoded=[]，只有prepare实际Z(Q011)，末端无多余纠正。GHZ/协议/原SLM终态/checkpoint恢复PASS。compile1235.164s，末checkpoint132.9MB/trace106.7MB；独立verify正在session79679子流程执行。4B整体尚待verify/UI。4C前需关注重复全量snapshot指纹计算的工程性能，不放宽物理规则。

4B独立256计划重放PASS，checkpoint逐字一致、history_guard及最终逻辑态/原SLM终态通过。verification_seconds=641.3704812999931。正式父脚本session79679 exit0，已通知acceptance启动8786保存结果UI验收；仍不将4B整体标PASS。

4B真实UI首次PASS，session14658 exit0；8786/PID19856/job62f802cad9766946821a0523418c45f3。完整916槽两种32×播放59.187/53.25秒，全34原子精确原holder/坐标；报告翻转中点无预读、终点真0报告1。另编辑六门实际编译2586.6μs，effects exactly once、Q018复位Z+1，短线路明确不冒充完整GHZ。page_errors=[]、运行期间源码不变。4B现已整体PASS；证据step4b-ui-attempt1/browser-acceptance.json。

4C开始实施：四patch默认原点(0,0)/(40,0)/(0,40)/(40,40)，36data+32ancilla、同98个AOD交点；1868门与控制槽，160MEASURE/RESET、507CZ、128位报告历史。421单事件量子矩阵运行中，接口/分批运输检查同步推进，尚未完整物理编译。没有新增审批要求或放宽物理条件。

独立工程性能优化已通过：trace不可变字符串的有界编码缓存与完整流式状态散列；64项测试含两个真实旧checkpoint逐字/哈希对照。132.9MB正式4B快照参考1.1823秒、预热0.1126秒，完整流式hash0.5554秒；缓存持久记录上限256MiB，不含当前state及临时完整字符串。证据snapshot-cache-benchmark/result.json及[专用说明](../../docs/snapshot_encoding_cache.md)。此为序列化微基准，不声称完整编译十倍加速。

4C工作台Python新旧51项PASS4.90s；四个128位历史guard新增检查PASS0.31s。新profile严格配对68原子/四块布局，真实GET/preview/零门编译及保存恢复正确；历史缺失、提前纠正、未知完整历史拒绝，短线路可正常进入物理runner。独立四布局自定义AOD容量与读出区域6项、joint既有3项共9PASS5.04s。修复新布局忽略legacy aod_traps配置的工程问题，禁止映射到MZ外的读出SLM；默认68/98平台完全不变。没有改旧两块平台。

完整4C首次合同已写`docs/qec_temporal_four_attempt1.md`，脚本准备并py_compile通过；分别3600秒编译/重放上限，局部决策/路径预算保持。完整代表尚未启动，先等量子与真实几何前置检查通过。几何探针已经实际通过68原子stage和18对全CZ脉冲，完整归还/独立重放仍在进行。观察到stage实际Executor花72.45秒而编译约2秒，栈证据为每事件重放整个串行计划的扫掠审计，不是路径搜索失败。

4C量子首次正式矩阵437PASS1438.13s：全部421事件（324data、96报告翻转、1无事件）与373种历史；32码稳定子、XXXX/ABBC CD ZZ、32anc复位、真实条件纠正与仅报告decoder一致。源码未变，零失败/零重试。证据step4C-quantum-tests/result.json，日志four-patch-temporal-quantum。几何探针中发生测试字段误用、主动停止定位耗时、周期faulthandler触发的Windows原生异常；工程记录由physics_research保留，物理stage/18CZ/terminal均已通过，移除调试钩子后重放检查继续。尚不把4C整体标PASS。

几何attempt4完整PASS380.08秒：68原子两次34/98stage，18对CZ真实pulse，完整terminal，5装5卸，序列化plan独立重放逐字一致，4个交接中checkpoint续跑一致。禁用周期faulthandler后未再现进程崩溃，不改变backend。9AB(-38,0)另纯候选构建与exact_validate PASS2.24秒，明确不是重复Executor演示。两项证据分别step4C-geometry-attempt4/test_all68_stage_parallel18_cz0/verification.json及step4C-geometry-nine-ab。

所有前置通过，完整4C首次实际执行已启动，root session67961；输入1868槽、seed7、round2_X0_0报告翻转、同98AOD，产物step4C-attempt1。源码冻结。编译与独立重放分别3600秒预声明，完成前不启动8787正式UI验收，不将4C或第四步标PASS。

4C首次实际跑到744槽/899.3秒，最近保存740槽/881.19秒，未发生物理拒绝。调研复制checkpoint确认顺序LRU工作集越容量会循环全miss：1784记录缩放512容量第二遍零命中，4096容量全命中；事件plan记录占解析存量主要部分。按已观察2680 records/736slots，完整代表极可能超过旧4096。为避免盲等耗尽1小时，核实worker13156命令后受控停止；父session67961 exit1，原exit/failure保留，加engineering-stop.json明确不是物理失败或timeout。该工程停止及修复依最新长期授权，不再请用户审批。

第二次仅调内部解析cache8192条、编码cache768MiB上限；源码解冻做缓存专项，协议/硬件/布局/搜索预算不改。新合同qec_temporal_four_attempt2.md与输出step4C-attempt2；脚本补即时源码指纹、trace_records进度、结束工作集<8192断言，计划核对旧740槽trace逐字前缀。专项通过后才能重启完整尝试。4A/4B及4C量子/几何仍保持已通过证据，不重跑这些昂贵实验。

缓存修复67PASS12.61s；4097记录顺序扫描3轮不再循环miss，深不可变/精确rawkey/懒分配、原读出与snapshot回归均通过。复制4C132556536-byte checkpoint完整restore、原canonical、冷暖snapshot/hash一致，实际cache236222246bytes未预分配768MiB；warm snapshot0.108s/fullhash0.394s。证据cache-limits-benchmark/result.json。第二次完整尝试已启动root session51159，源码重新冻结；不得把尚在运行写成完成。

第二次到740槽时抓取完整checkpoint SHA256对照PASS：两次同为13aa303d457376525a84fef228147d86027b71f3bd3768eff8841b52b142531e，含2858条trace及全部状态，不仅是量子观测值。相同边界墙钟881.19→798.42秒，单次观测；不能推广统计加速比。证据step4C-attempt2/retry-prefix-verification.json。734槽时worker实际RSS802869248 bytes、观测峰值1168707584 bytes，记录memory-observations.jsonl；完整执行仍在进行。


## 4C 第二次预算结束及续编译
第二次parent session51159已退出：3600秒timeout code124，最后1604槽/7568事件；完整已提交checkpoint1588槽/7564事件/94372.5μs/3579.865s。未报告物理错误，旧证据原样保留。应用显式resume入口及16384解析/1536MiB惰性编码缓存，77项20.96s通过。新合同docs/qec_temporal_four_resume_attempt3.md；下一步从此checkpoint继续，不重编译前缀。


## 4C 全物理执行通过，独立重放启动
新session56748的resume阶段通过：原1588槽/468计划/7564事件前缀snapshot SHA51d51d321d600940c64642e2f53fdbab5c7acda17b027690cea9609425f36674逐字保留。后缀47计划，631.276秒（仅后缀，不能当完整编译耗时）。全1868槽、515计划、8360事件、105285.6μs，其中逻辑104115.6μs、最终恢复1170μs；231装载/231卸载。160MEASURE及160RESET各20批8原子，实际H最大52、CZ最大18。32稳定子/XXXX/三ZZ为+1；报告历史128位受支持，唯一指定报告翻转；原68SLM归还检查通过。完整编码缓存保留1,053,951,112bytes；进程峰值4,176,789,504bytes。全部515计划现从原初态独立Executor重放并逐事件匹配，完成后才验UI。


## 4C 全轨迹重放PASS与界面口径修复
parent56748 exit0。515计划/8360事件逐事件匹配、最终checkpoint逐字一致，history guard/restore/prefix一致性全部PASS，独立重放2393.463秒。完整recording98,150,221bytes、index41,039,129bytes、checkpoint587,296,415bytes已生成。研究agent交叉核对通过，并收紧效果统计：352个X/Z条件槽仅5实际施加、347跳光；唯一真实0/报告1，decoder接受该报告历史并返回空数据纠正，不冒称显式错误分类。
发现saved restore界面丢弃suffix_only时间口径；现由acceptance agent修复显示元数据与JS，物理模块不动，再验收8787完整可编辑界面。四步仍等待UI通过。


## 最终交付：四步全部PASS
8787/PID28532，http://127.0.0.1:8787/?job=87eef4dc58e467e0e6b423bfda158c43 。UI session57088 exit0，一次正式通过：physical32×132.062秒/keyframe32×124.484秒完整原位归还68原子；160真值/报告、128历史与GHZ4见证正确，测量无预读。实际编辑六门job82d8c92a2d474ddc81c2e68238e8f622，4006.6μs，真0/报1、Q036 reset Z+1、六项各完成一次、全部原位归还；该短线路非GHZ与协议false为合同预期。page_errors=[]，source.changed_during_run=false。
展示修复仅workbench_server.py/workbench.js，19项1.91秒及3Node PASS，post-replay-ui-source-delta记录与物理验收源码的精确差异，未触及物理模块。四步ledger经validate_status通过后将step4/attempt3/4C置passed；历史失败及其授权不被覆盖。全部验收进程结束，仅保留服务。没有提交或发布代码。
已更新agent、handoff、state_circuit、physics、milestones、QEC工作台/缓存/恢复/验收文档，并核对10个当前文档的本地链接无缺失。未重跑全量suite：相应物理/量子矩阵、77续编译缓存回归、19展示回归、Node与完整实际重放/UI证据分别记录，不将其简单相加为统一套件。大型电路仍慢，固定轴/启发式/单事件噪声限制见最终报告。

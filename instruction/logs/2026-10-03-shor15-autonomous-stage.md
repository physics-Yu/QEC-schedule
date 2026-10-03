# 2026-10-03 · d=3编码Shor自主推进与阶段发布

- 状态：IN_PROGRESS
- 用户授权：沿最终愿景自主继续；阶段成果提交GitHub。阶段算法已确认N=15，每个logical wire使用3×3 data的d=3 patch。
- 本轮目标：完整N15 logical reference、encoded ZZ/XX协议、resource-aware PPR测量桥与物理集成；每项按真实验收范围发布，不以reference替代Executor。
- 初始基线：canonical memory已有物理证据；完整PBC/encoded T桥缺失；远端main实时核对为5f3286defd95a269b94b2211960984319c797817，本地HEAD与大量dirty保持。
- 路由：architecture、workflow；各子任务按研究/物理需要读取相应合同。

## 进行中的分工

- N15完整逻辑Shor（modexp+inverse QFT+measurement+continued fractions+gcd/retry）；不使用已知周期或因子构造。
- 3patch encoded ancilla/transversal parity协议：完整rounds/detectors/decoded parity与native fault检查。
- root：PPR→measurement/resource bridge、物理平台/执行集成、测试与发布。
- 发布审计：以远端clean snapshot和allowlist保护用户其他dirty；保持pushurl=DISABLED，使用GitHub connector或隔离发布分支。

## 验证与发布

新增资源或布局仅为实验输入，不放宽原物理距离/支撑/碰撞/AOD/CZ/测量硬约束。未完成项不得声明完成。

## 已完成逻辑与协议

- `shor15.py` / `run_shor15.py`：完整N15,a2，12 wires、72酉门、8测量与经典周期验证/分解/retry。全部256指数、16work值/两control和正逆映射验证；全部4096最终复振幅独立FFT误差3.06e-16，通用work-entangled QFT输入也验证。seed7真实测128失败后测192恢复r4、因子3/5。
- `adaptive_pbc.py`：真正resource-aware测量程序与理想instrument executor；signed PZ、resource X、条件Clifford/Pauli、resource consume与residual/global phase均执行。35magic前缀+reference误差4.05e-17，未包含inverse QFT CP综合。联合89测试通过。
- `encoded_ppm.py`：三完整d3patch、前后各3轮canonical、18 transversal CZ、136detectors、保留AB，默认ZZ/XX均1860native（1062H/450CZ/195RESET/153MEASURE）。两Choi分支独立确认完整理想instrument；calibration parity模型分别10230/10338 nativefault机制，singlefault decoder/独立传播/terminal 3report witness通过。29专项通过，不将classicalparity模型外推为保留quantumoutput的完整噪声FT。
- `run_shor15_stage.py --fault-audit` 实际完整导出参考、资源测量桥与ZZ/XX两类audit，passed=true，输出原workspace `artifacts/qec-shor15-2026-10-03/stage-reference`。

## 物理尝试与常规修复

1. 本地Enola默认ZZ首轮在65plans、37pulse/max3处停滞；唯一candidate violation为AOD_OUTSIDE_WORLD，independent plan replay=true；390.979s含失败导出与重放。远端clean主线同位失败65plans、334.157s。失败目录完整保留。
2. 根因是PatchArrayCompiler.bindings固定选第一个匹配column，source fullarray合法但目标平移后越界；新增required_shifts并同时选择source/target完整axes在原bounds内的embedding，transfer/pulse/preflight一致。未扩world、interaction radius或放宽任何validator。这是上层策略选列缺陷，非物理模型变更。
3. 两个新边界tests通过；首轮负fixture尝试构造窄world被INVALID_TRAP正确拒绝，随后改用原合法world+超出bounds的requiredshift测试真正待验行为。
4. 失败prefix导出保护：当wallbudget在accepted plan内到期，先保存checkpoint/trace/recording，再捕获完整schedule导出失败，不覆盖原Timeout、不伪报pulse统计；2真实/注入failure tests通过。
5. 本地旧patch_greedy三fixture失败来自未发布Enola半径/offset与其legacy预期不同；不改变断言或上传hardware整组。远端clean上包括旧patch tests、plannerfix、adaptive、failure与相关input的70项通过。
6. clean基线510个不同相关tests通过，加入PPM/physical input后543项；RAG跨平台sha256 text_lf、真实文本stale/unknownnorm/非UTF8检查通过，15/15旧检索；architecture0违规。最终完整统计待汇总。

## 尚在验收

- 远端clean ZZ/XX完整Executor及独立plan replay已重新开始；等待最终实际结果。
- 第一阶段GitHub branch/PR发布与blob核对待完成；本地HEAD、pushurl与其他dirty保持。
- 完整Shor inverseQFT CP综合、encoded mixed/Y、Clifford反馈、magic制备/注入和整体物理算法保持后续。

## 第一阶段清洁发布验收

- 远端main工作树最终30个test文件一次联合：589 passed、0skip，119.25s，唯一pytest9未来parametrize warning；`artifacts/shor15-publication-validation/final-test-files.json`与`pytest-final-clean.txt`。
- RAG最终37chunks、29sources（11外部、18本地组/46路径），18/18检索、11项归一化新鲜度/跨平台检查；247模块architecture零违规。Git文本LF sha256显式规范，保留历史raw hash，不把WindowsCRLF误报作代码更改。
- clean `run_shor15_stage.py --fault-audit` 实际passed，完整理想Shor因子3/5，算术35resources测量桥与ZZ/XX独立instrument/fault校验；full_shor_physical_executed=false。
- 原29tracked dirty指纹保持（此前独占RAG/test fixture常规修复除外）；远端env/hardware/config不复制本地未发布Enola整组，两planner diff逐段仅本次bounds选列修复。
- 当前ZZ/XX两个完整物理重跑已跨首轮失效点，尚不预报最终通过。

## 第一阶段已提交 GitHub

- 独立干净发布分支 `codex/d3-shor15-stages`，commit `4ee266936949717565e233b74542e0eaff5f6417`，draft PR [#3](https://github.com/physics-Yu/QEC-schedule/pull/3)。90 个相关文件，父提交为前述远端 main；独立 fetch 后完整 tree 与 staged tree 一致，逐个 blob 核对。原 workspace HEAD `9e28b2e`、pushurl=DISABLED 和其他未提交工作保持。

## 第二阶段完整逻辑 PBC 与连续编码接口

- 全部 28 个逆 QFT CP 展开成 84 Rz，使用固定官方 pygridsynth 1.2.0 核心与全局相位合同综合。默认 ε=1e-3/seed7：8993 Clifford+T gates、3500 T/Tdg resources；独立 256 列完整 QFT 算子误差 6.78e-5，小于预算；一般与 work/reference 纠缠输入另验。
- 完整算法实际执行 3500 ideal-resource 消耗和 7000 projection/feedback，逐分支全局相位与 residual Clifford 实际应用；zero 和一般 data-reference 输入的 instrument 复振幅误差约 1.05e-13。整体对精确 Shor L2 误差 3.57e-5/2.53e-5。未以 arithmetic-only 或理想酉替代全部 PBC 测量。
- `shor15_pbc_run.py` 在实际 PBC 输出态上执行 8 次终端 Z 投影，再周期验证/gcd/retry；seed7 第一次 128 未给出因子，第二次 192 恢复 r4 与 3/5。两 shot 共 7000 fresh resources、14000 resource measurements、16 terminal measurements；使用不同 resource instance namespace，保留失败 shot。
- clean 新增 QFT 14 项、终端测量 3 项真实通过，连同第一批为 606 个不同相关测试。`--complete-pbc` CLI 在正确 isolated Stim/pygridsynth PYTHONPATH 下通过；第一次缺 Stim 的依赖失败证据保留。RAG 当时 38 chunks/30 sources/53 本地路径，20/20 检索、11 新鲜度检查；249 modules 架构零违规。
- `encoded_composition.py` 接受 prefix 和全部 incoming sectors，无 A/B data RESET；fresh C 或显式已消耗 C 的 epoch reuse。原 prefix 保留，连接真实 native gates 与依赖。ZZ→XX 使用同 C 为 53 roles 含两个 reference、4081 native；seed0/7/19 两阶段分别验证全部 256 个逻辑/reference Pauli 期望、144 detectors 和 16 closing sectors。25 项专项通过；clean 复验与 RAG 新增记录待汇总。这里未包含组合 physical 或 magic factory。
- clean ZZ/XX 完整物理重跑分别在 1605/1596 个已完成门附近因 2400s wall budget 超时。物理最后一轮执行仍有效，未发生新的物理约束失败；checkpoint、accepted plans 与 pending future 导出/重放进行中。新增严格 resume 只接续原 quantum/RNG/time/trace，不能重做输入制备。性能问题另定位，不跳过任何历史校验。
- 第二阶段 clean 组合 25 项通过（5.99s），累计 **631 个不同相关测试**。signed-prefix、两外部 references 的同 C ZZ→XX 实际 audit 通过：53 roles/4081 native，seed0/7 两边界各256 Pauli expectations、144 detectors 和16 closing sectors全部满足。RAG 加 K39/L20 后39 chunks/31 sources/56 本地路径，21/21 检索、新鲜度与11跨平台检查通过；250 modules 架构零违规。第二阶段发布包括这些稳定内容，resume/performance 仍在单独验收。
- 第二阶段已提交 `6ddfbf8cc165b4068293a074680603e098eb33eb`（parent `4ee2669`），19 个增量文件；远端 tree `1c04c29bab4e3ca91936560fc8dcd009efcb4189` 与独立 fetch 后 staged tree 完全一致，PR #3 更新范围。clean HEAD 使用 expected-old ref 前移；原 workspace HEAD/dirty保持。
- 新增只读 `audit_shor15_encoding_requirements.py` 从实际完整导出计算3500项joint observable：2325含Y、3138mixed、weight2–9；data weights1–8计数为1240/552/716/162/260/143/241/186。仅356项形状为两patch homogeneous Z，仍不提供magic制备。基础204算法原子与未知magic/physicalpeak分别保存，文档明确Clifford stabilizer物理量子跟踪不能直接执行tracked T。这是下一阶段实际需求，不是新完成的encoded能力。

## 第三阶段恢复与性能验收进行中

- `execute_encoded_parity(..., resume_from=...)` / CLI `--resume-from` 增加严格输入与完整 accepted-plan 内容核对：同 ID 改操作也在续跑前拒绝；未开始的 pending PLAN_STARTED 必须匹配最后 accepted plan。先 drain 已提交尾计划，无重 submit、无重新 A/B preparation、无物理时间折扣。全程 quantum/RNG/history 保留，末尾全部 plans 从 original initial 独立重放，VisualRecorder 重建完整动画。fast 最新7新resume与2旧failure检查通过；真实 round1 mid-plan→完整 snapshot baseline 对照仍在运行。
- 新 cache 修复在 `trace.py` 与 `runtime_validation.py`：稳定 exact-string prefix admission、16384 entries/3GiB lazy conservative retained-byte 上限，不修改任何 validator predicate、snapshot bytes/schema、量子效果或物理规则。全部 history 每次仍读取，篡改与 checkpoint 恢复 fail-closed。超过容量的 suffix 仍 cold decode，不能称通用长线路已优化。
- 原始专项44通过，含12新增cache tests。16385合法WAIT事件 synthetic warm全扫描：旧LRU每轮16385 decode/0hit，新稳定prefix为1decode/16384hit；完整真实2572records首失败prefix占cache339.13MiB，warm全扫0.000816s。性能只指解码；完整physical/重放计时另待实际。原始扩大suite的4旧M3 geometry failures已在原LRU单独复现，来自本地未发布Enola配置；不改断言/硬约束，clean远端复验待记录。
- 2026-10-04 clean新cache12项通过（0.67s），旧9文件回归125通过/3缺历史artifact跳过（30.91s），包括原始4个legacyM3失败nodeids均通过。nodeid差集明确650项在clean通过（631＋7fastresume＋12cache）；另一真实正例在原workspace通过1977.07s，合计651不同相关tests，不能写成651全在clean一次联合通过。
- 实际round1正例为初始98个native门（未完成codespace preparation）处中断，恢复后完整708门/177plans/6918events、102 CZ pulses/max3；全部16个boolean audit通过，checkpoint/plans streaming SHA256与无中断执行字节相同，metrics也相同。原workspace含terminal时间137021.641625us，不能混用于远端legacy默认三轮结果。该长进程加载较早cache/helper，latestguards由7fasttests检查，新三轮strictresume加载新cache；来源边界已在衍生comparison.json声明。
- 两个远端legacy三轮旧run真正exit1并保留全部失败证据。ZZ prefix为1605门/390plans/16422events、226532.6us；旧helper将accepted末计划完整跑完的replay与中途Timeout前缀不等，schedule不完整也是失败事实。新helper必须按原checkpoint version逐事件独立重放，不能用旧错误填为true。XX旧prefix为1596门/391plans/226827.6us。
- 新ZZ strictresume已启动（loaded runner6AD0F4FC...、新cache）；实际继续到1651/1860门，未重做准备。后续runner只释放验证临时checkpoint字符串/full-plan JSON等GB对象，fast7项再通过（5.90s）；新XX将加载释放版316519E025...。`loaded_runtime_provenance.json`明确区分启动时已加载代码与run_metadata写时磁盘hash。两新重放按ZZ→XX串行，控制host内存，不改变物理时序。
- 固定canonical X/Z3、Y5代表元对完整3500词实际展开，最大joint support为37原子；tool与需求doc更新。此37和原logical weight9都是固定导出的统计，不能作为运行时Cliffordframe后端的通用上界。
- 真实三轮旧prefix16422已越过16k；新ZZ已加载的16k版本在继续增长的cold后缀仍有成本。后续default entry调为32768，**3GiB retained-byte界不变**；原16k边界回归显式构造16384缓存，新增default20k三轮全history扫描0decode/60000hit且retainedbytes不增长。原focused45通过，clean复验待汇总；新default不会影响已经运行的ZZ，XX新process将使用它。相关测试总计652（651 clean＋1 original），不能把源测试45再次加入总数。
- mixed/Y设计与portable `tools/audit_mixed_pauli_design.py` 已发布准备；clean实际复建144 Clifford纠正branches＋64 noncommuting T injection branches，误差最大5.98e-16。独立复算actual inventory 1683odd-Y、642非零even-Y、max37。新文档一手依据包括Shor quant-ph/9605011v2、twist surgery、Game of Surface Codes、BSS和官方Stim；强调native/track S、non-Clifford表示与真正parity controller的能力缺口，均为设计/数学，不计新的backend/test/FT/physical通过。
- clean 32k focused45通过（3.77s），13新增cache与32旧检查；当前RAG41 chunks/34 sources/66本地路径、25检索cases，最后新鲜度检查按发布清单固定。source Shor quant-ph/9605011v2核对为5Mar1997版本，保留v1/v2年份区别，不更新历史10-03资料日期为新日期。
- 新ZZ resume1在2394.22s到1767/1860门、436plans、242174.3us；仍可能再次Timeout，不能把pending写成完成。后续精确preimage摘要memo只针对重新序列化完整nontrace字段＋immutable trace全部值的相等输入，仍在实现/独立验收，本阶段发布先排除未验的snapshot修改。
- 第三阶段18个稳定增量路径已提交 `f389f705080a4d120fdc08bafb946a4e47b5a48f`（parent `6ddfbf8`），远端 tree `fec568ae49da7c283e6539b65f53d0e478b0b203` 与本地暂存、独立fetch完全一致，cached diff为零；EOF空白检查已修，RAG关联指纹同步刷新。clean branch用expected-old前移，原workspace HEAD/dirty/defaults保持。PR #3按最终已验证范围更新，仍为draft；新digest memo及未完成物理run不在此commit。

## 第四阶段完整前像摘要与Clifford frame推进

- `snapshot_encoding.py`新增单entry exact-preimage memo，1536MiB保守收费，nontrace全部新canonical fragments＋完整exact tuple[str]值构成certificate；hash miss使用同一份captured fragments，不以state/version/部分digest代替前像比较。自定义cache、替换default encoder、伪造`__func__` callable、wrong-self method、非exact keys/strings、零/超字节预算走原计算路径。独立只读review发现的customencoder伪装边界已实际修复与补cold/warm反例。
- 新增21项memo检查，原workspace相关56通过/3显式排除；clean同56项通过10.96s，21新nodeids差集明确，另35为已计数旧检查。合计673不同相关项=672clean＋1original长正例；2历史saved-artifact和1已完成1977s长恢复对照不重复跑。250modules架构零违规。source SHA256 `93c9a1a44e950517abc191c4fec14f3e5f4604d8bd7d0ba763ab0859a5d32995`，test `51f1f766e7ff594e333bfe0a1078e945782913d143028abc022dbe1afd158d2e`。
- 原实际低roundprefix纯编译profile保持：19ops/3CZ、plan9d5c...、完整SHA e53dbc...、compile/validate期间不submit，state/trace/version/time不变。旧3次hash42.49/41.30/41.00ms总124.79ms，新42.27/19.22/19.29ms总80.79ms，1miss/2hits收费34.19MB；只说明此小profile的hash成本约35%下降。旧`low-round-fingerprint-profile.json`与新`low-round-fingerprint-profile-memo.json`分开保存；不推断完整r3倍率/不计physical通过。新ZZresume2和XX进程再加载此源，已运行resume1保持16k/旧helper。
- 下一logical reference独立推进`conditional_clifford_frame.py`：signed inverse-frame全部2n generators、真实测量结果改变后续标签、完整correction/global-phase/dependency ledger及终端residual pullback。此时仍在实现，未计入上述673或encoded/physical能力。

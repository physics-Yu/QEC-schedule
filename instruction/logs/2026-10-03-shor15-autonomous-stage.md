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

# 2026-09-14 · demo电路与横向CNOT审计

- 状态：COMPLETED
- 用户报告：两逻辑GHZ线路出现连续X/Z，无法识别transversal CNOT；要求检查全部demo生成。
- 范围：核查五份配置demo与生成器一致性、条件反馈语义、编码/稳定子与横向CNOT；修复误导显示，保留物理约束与环境/策略边界。
- 初步发现：surface_qec._corrections枚举非零syndrome条件分支，界面却将条件X/Z绘制成普通门；logical-cnot阶段存在9对对应数据CNOT，原生展开H(target)-CZ-H(target)。仍须独立核验全部实际配置，不能以函数名证明正确。
- 物理模型/整体框架不作未获批准的变更；运行态条件跳过仍按既有1μs控制槽合同，不能直接删除互斥分支或当作无条件XX抵消。

## 验证与交付

- 用户随后要求不新增可读展示，只需明确定位；本轮未修改UI、门生成器、demo JSON或物理执行。
- 定位：两逻辑两种QEC demo的39列为Q009–Q017上的9H，40列为QEC0302–QEC0310的9CZ，Q000→Q009直到Q008→Q017。末尾9H与后续同wire H成对消去；不能将阶段内剩余18门单独当成完整CNOT。
- 全五demo通过`tools/audit_demo_circuits.py`：保存门列表与生成器一致、完整Pauli作用横向CNOT检查、删除CZ负例、HH消去证明、条件分支互斥。三种QEC在seed0/7/29的raw/optimized报告位与完整量子态逐项一致；具体报告在artifacts/demo-circuit-audit-2026-09-14/report.json。
- 初次审计脚本按JSON数组顺序比较，遇到surface-ghz文件按column/id排序而生成器按生成顺序排列；确认按ID全部字段相同后按实际执行排序比较。未改生产数据或降低语义比较要求。
- 电路槽数4/194/480/916/1868；条件槽0/0/184/176/352。单轮两逻辑seed0为184条件槽中3个真实Pauli、181跳过；它们不是无条件连续XZ。
- 研究核对：Nature s41586-023-06927-3 Methods同向surface-code横向CNOT；区别项目静态物理纠正槽与论文的软件跟踪，不冒充完整实验复制。
- [定位与详细结果](../../docs/demo_circuit_audit.md)。未重新编译物理运输、未跑完整动画/全部噪声域；本轮无物理或大框架变更，无需新审批。

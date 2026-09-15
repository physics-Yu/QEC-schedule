# 2026-09-15 完整 QEC GHZ 接入 ROUTES V2 与 SMT 对照

用户要求：在2.5μm离散占据障碍、直线合并、拐弯停下、有序AOD行列的新移动逻辑上重构QEC GHZ及SMT比较。

## 实现

- 新 `strategies/scheduling/smt_ordered.py`：SMT自己选择READY CZ、移动/静止角色和四向2μm端点；约束共享轴、序关系、容量、笛卡尔捕获闭包、实际端点作用对。max当前批次优先，max Manhattan位移次级；共同完整物理校验后执行。保留unknown/模型/路线失败原因与符号目标上下界。未用greedy候选包装SMT。
- `strategies/motion/ordered_transfer.py`：已有有序行列路线的SLM组间交接，提供SZ/EZ/MZ运输；原子支撑开关仍由真实LOAD/OFFLOAD提交。修正了关闭目的SLM的直达运输被策略人为要求折返的问题，现有backend原本就允许，无物理核修改。
- `experiments/qec_ordered_comparison.py`：34原子、483槽、105CZ、129H、184条件X/Z、Y(Q013)、32测量与32复位；保持现有协议与完整经典依赖。共用控制服务，只交换CZ批次策略。每个策略新环境、新进程；全部66计划独立重放。新CLI、分析器及可编辑QEC专页复用普通viewer，支持阶段跳转与失败弹窗。观测器带data/ancilla角色。
- 修正 `OrderedAxisGreedy` 的单比特识别：仅实际Raman门，不能把MEASURE/RESET纳入1Q分支。原物理核未改；已有工作区builder ULP修正属于上轮。
- 新界面地址 http://127.0.0.1:8796/ ，服务器PID14996，目录 `artifacts/qec-ordered/attempt2-direct-transfer`。首轮8795/PID23164保留。

## 结果

完整对照见 `artifacts/qec-ordered/attempt2-direct-transfer/qec_ghz2/comparison.json`、`analysis.json` 与[报告](../../docs/qec_ordered_smt_comparison.md)。

| | 贪心 | SMT |
|---|---:|---:|
| 物理总时间μs | 32017.275973471107 | 32322.57652842953 |
| CZ批次/最大并行 | 17/9 | 17/9 |
| 移动段 | 260 | 265 |
| 原子路程μm | 16550 | 16562 |
| 原子次装载/卸载 | 237/237 | 237/237 |
| 编译执行秒 | 382.200243 | 116.964094 |
| 独立重放秒 | 79.219665 | 89.196147 |

两者完整初态SHA相同、483槽恰好一次、终态归还与全部开关复原、独立checkpoint逐字一致。最终逻辑XX/ZZ与16码稳定子全部+1，真实测量/复位协议完整。实际transversal的9CZ在同一脉冲。非正交段与冗余同向停点均0。

本例并行结构相同；SMT更慢0.95355%，差305.300555μs全部在运输。SMT构建2.24267秒/求解0.23599秒，主要墙钟在共同计划/校验/执行记录；不据此称SMT暴力求解是主要瓶颈。主机上存在上一轮重放与验收的重叠，不能用382/117推出隔离条件下加速倍数。

## 尝试与工程修正记录

1. `attempt1` 双策略全协议/独立重放已通过：32102.560656/32445.015183μs。发现关闭目标SLM的人工折返，保留原数据并修复策略，随后完整重新运行双方；不调整物理规则。
2. 首次新测试1失败5通过：`simulate_ideal`返回 `(state,report)`，测试误作dict；修正测试取值，专项重验通过。不是协议错误。
3. UI阶段跳转监听和进度文字在文本编辑时丢失了JS选择器；真实GUI发现，修复后阶段跳转显示232–255槽，包含9个CZ。不是物理编译错误。
4. 1秒预算负对照 `interactive/440ce81fa7034bf2bd7ef157d73964d6` 双方明确COMPILE_TIMEOUT，停止在实际SZ→EZ前缀389.73666μs；保留前缀和独立重放，GUI弹窗。该测试有意失败，不是完整实验失败。
5. 实际GUI手动清空/追加H(Q000)、CZ(Q000,Q001)：最终版本 `interactive/94b80d6dac8641178df75d310edbf8c1`，双方真实完成1804.133272/1859.164919μs、同初态、回归终态、独立重放；界面正确显示此编辑线路不通过完整GHZ协议。早期版本同类UI试验678f9577b43e4c109ea1c2b4cd8b27c9保留于attempt1。
6. 未知依赖输入真实GUI提交，立刻显示 `Explicit gate dependencies must reference earlier gates`；未创建物理编译作业。

## 检查

- `pytest tests/test_qec_ordered_comparison.py -q` 首次5PASS/1测试取值FAIL；修正后失败项PASS，交接路径变更后两项PASS，SMT目标日志变更后三项PASS。最终6个独立新测试全部覆盖当前代码，包括完整理想协议、SMT三/四CZ并行、原子支撑转移、unknown原子性、真实MZ测量复位/条件控制和重放。
- `pytest tests/test_ordered_axis_greedy.py tests/test_ordered_routes.py tests/test_environment_boundary.py -q`：24PASS。
- `python tools/check_architecture.py`：137模块，0 violations；`node --check`新UI通过。
- 真实CUA：完整贪心关键帧/真实时间比例均32×自然到终点；完整SMT动画同样验证，两策略完整结果均在界面显示GHZ/协议PASS。编辑、错误依赖、预算失败与阶段跳转已验收。详见 `artifacts/qec-ordered/attempt2-direct-transfer/ui_acceptance.json`。
- 最终线路图按qubit次序/显式依赖/测量条件计算DAG逻辑层，避免输入列表把transversal九对画成串行阶梯；真实DOM确认横向段18个CZ端点同列x=204，实际物理9对同脉冲另由trace验证。CNOT以目标H–CZ–H实现，优化可抵消相邻H；图不伪造被消除的门。
- 未运行全仓测试套件；没有新Git提交/推送，main保留前两轮未提交改动。

## 下一步与限制

本轮仅是完整两逻辑QEC上的**当前frontier SMT最大批次**对照，不是全电路多阶段SMT、完整电路噪声容错、所有配置空间的完备路由。每批归还、固定空轴延伸、有限2.5μm通道候选仍限制空间。原生产工作台默认策略未换。

下一条可执行任务：在不改变当前物理/序列化合同下，给共同计划校验与执行记录补细分计时和等价缓存；之后把空载定位、全部轴轨迹和往返时间加入SMT的候选评分，保持此483槽同初态/终态作为固定回归基准。跨批次驻留/全局阶段求解另立对照，不能以本轮17批结果宣称全局最优。

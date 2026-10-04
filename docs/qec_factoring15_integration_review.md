# Factoring 15 对照：完整编码 Shor 的可实现范围与复用路线

2026-10-04 用户后续要求已固化为 [QEC 工厂供应与逐周期质量协议](../instruction/qec_factory_pipeline.md)。本文保留源码与历史验收快照；其 Shor-first 实施顺序由新协议的 factory-first 主线覆盖，不能作为当前任务优先级。

2026-10-04；本轮为跨项目只读审查与设计记录，不是新的物理执行验收。QEC 基线为 `7301daf`，Factoring 15 的 Git HEAD 为 `580a7e1`，其 G1.1 正由另一任务继续修改。观察来源、旧运行包指纹及本轮测试范围见[证据摘要](../references/qec_pbc_validation/factoring15_review_2026_10_04.json)。

**已有算法和协议足以开始完成理想编码的端到端原生线路原型。当前代码尚不能直接执行完整编码物理 Shor。** 应将完整线路生成、带物理约束的排程、执行器真实量子投影与反馈、含噪容错分别验收；无需先等待完整容错证明才集成理想原型。

## 1. 两项目实际提供什么

| 功能 | 当前 QEC/PBC | Factoring 15 已验收 G1 |
| --- | --- | --- |
| 完整阶寻找 | N=15/a=2；12逻辑wire；完整逆QFT；实际PBC测量、失败shot和因子恢复 | G2/G3 后续目标，G1只有T†消费者 |
| 编码测量与反馈 | signed XYZ cat、完整Clifford frame；单算法patch编码消费参考；ZZ/XX完整Executor | 横向CNOT、Z-product旋转、encoded-Y纠正和局部编码通道参考 |
| 魔态来源 | 真实17q裸T/T†制备及编码；没有蒸馏工厂 | 15 raw A、15-to-1蒸馏、四项X检查、拒收/补产、载态库存、T†消费 |
| 平台 | SLM/AOD支撑、共享行列、实际CZ作用集合、运输与普通Executor校验 | 串行代表性几何模型；独立路线/覆盖/账本检查，不是完整AOD控制 |
| 分支来源 | 逻辑/编码参考与ENV committed报告明确分开 | 先运行理想reference，再按reference选择物理计划；物理读出仍null |

Factoring 的 `src/factoring15/quantum.py` 中 `protocol_spec()` 先调用 `run_reference()`；`platform.py::_reference_bit()` 从该reference取结果。`platform.py::_Planner.add()` 将物理测量保存为 `source=not_simulated,result=null`。因此其完整G1计划不能冒充当前Executor的实际反馈桥。

冻结 G1 三包的计划指标：ideal 1接受/1消费、29,997事件、3,267 CZ、881.262 ms；retry 拒绝后接受、53,871事件、5,841 CZ、1,600.039 ms；exhausted 两次拒绝、52,364事件、5,652 CZ、1,563.587 ms。三者均属 `physical_plan_with_ideal_logical_reference`，平台通过范围是 `pass_reduced_model`。这些时间不能与本项目ZZ/XX直接比较，更不能外推完整Shor或实际yield。其fidelity proxy超出自身适用域，值保持null。

## 2. 需要纠正的能力表述

**普通物理调度已经支持原生T。** `hardware/raman.py` 接受H/X/Y/Z/T；`simulation/quantum_effects.py:27` 的未跟踪路径能记录T物理效果；`tests/test_gate_contract.py:32` 已有同型T并行和1μs校验。不能笼统说“后端不能生成或排程T”。

实际限制是：MEASURE/RESET要求非空量子态（`quantum_effects.py:40`），状态构造仅接受 `StabilizerState`（`simulation/state.py:42`），tracked gate校验拒绝T（`quantum_effects.py:21`）。所以目前不能把真正T资源制备、实际Born投影和反馈同时放进该执行器。关闭量子跟踪不能绕过测量合同。

现有编码消费还能返回真正 `PhysicalCircuit`，但它是参考实际采样分支的线路。`encoded_injection_reference.py:377` 明确只接受 `wires=('A',)`，并使用18-data向量；wide cat的raw枚举为指数规模，`mixed_pauli_cat.py:482` 的all-raw资格审计限16 cat原子，encoded exhaustive channel审计限6个logical/reference qubit。完整12wire并非调用该API两三次就已实现。

静态、已确定分支的完整线路生成不需要修改live DAG。有限prepare/verify/accept-or-abort控制器也可预声明整条Clifford线路、只提交准备前缀，并在读取 `NeutralAtomEnv.observe()` 的真实committed报告后选择继续或终止。一般在线frame改变下一gadget的接口仍要实现；不能把live circuit append当作所有原型不可避免的先决条件，也不能直接写live state或伪造XOR测量键。

## 3. 最值得复用的内容

1. **实际工厂协议。** 复用15 raw输入唯一来源、四项蒸馏检查及接受/拒绝合同，将当前裸T producer扩为有来源和成本的工厂。先采用已冻结的五工作逻辑比特协议，保留已有QEC XYZ cat与signed frame；一般混合Pauli不能退回Factoring的Z-only入口。
2. **库存与载体。** `runtime.py::validate_inventory()` 独立重放 available/store/handoff/consume/discard：接受前不可用，raw输入不可复制，同一输出不可消费两次，固定9data载体不可用改名代替移动。该设计应由ENV committed报告驱动后接入当前资源epoch合同。
3. **有界拒收补产。** `runtime.py::_merge_plans()` 检查上一批末位置等于下一批初位置、原子/config一致，显式cleanup、retry等待和availability时间平移。移植这些约束，不能仅拼两份不连续trace。
4. **代价明确的纠正。** Factoring通过新的编码Y辅助态执行条件S/S†；这是可参考的eager方案。当前QEC已实现完整Clifford frame，可继续延迟纠正，但必须正确改变后续测量轴/符号、工厂终端checks及经典依赖。不要同时计免费frame纠正和另一条未执行的物理纠正。
5. **独立验收和统一运行包。** 学习独立GF(2)/相干oracle、15单错与105双错拒绝、35接受三错的相位错误反例、删门/错目标/伪物理报告/重复库存反例；input、native circuit、plan、trace、库存、预算和demo绑定同一运行版本。不能只以最后输出3和5验收所有中间模块。

## 4. 不能直接复制的接口

- 两项目使用相同X/Z稳定子支持集与逻辑代表 `X0X3X6`、`Z0Z1Z2`，但各bank的顺序不同：QEC check编号0/1/2/3对应Factoring编号1/2/0/3。必须显式映射semantic IDs、aux身份和syndrome数组。
- Factoring statevector little endian，当前QEC独立native向量的wire顺序对应big endian。按wire置换实际复振幅，不仅改显示标签。
- Factoring工厂输出 `A_minus=(|0>+exp(-iπ/4)|1>)/sqrt(2)`，消费者为T†；匹配QEC负资源合同。算法需要T时，不能把A− token改名成A+；应执行并验证实际资源转换或选择相应生产协议，保留全局相位ledger。
- Factoring的RZ(±π/4、±π/2)、S/S†、CX不能直接提交当前原生门菜单。明确综合为实际H/CZ/T序列，统计真实T/7T/TT成本；tracked-T限制仍需独立解决。
- 两边raw unitary encoder均未证明容错。三轮syndrome和静态d=3不自动证明hook、时空码距或decoder。
- G1.1的RM16候选四层各8对CNOT，用16 work＋15 magic slots＋1 consumer共32patch/544原子换并行。这是实施中的候选；不能由旧136原子串行包证明新平台或等资源加速。合并Shor后另需算法patch、cat和库存预算，数字不可直接相加后当已验证峰值。

## 5. 下一批可验收成果

本节 A→B→C 是本次历史审查的建议顺序。当前应按 [共享协议的实施顺序与验收门槛](../instruction/qec_factory_pipeline.md) 先完成工厂→库存→同一资源的单 T 消费闭环；第3节“五工作块优先”亦属当时候选，具体标准模板须显式选择，不能混用五工作块与 RM16 资源计数。以下原方案保留供追溯。

**A：完整12wire编码原生线路与分解语义参考。** 保留现有完整Shor/PBC及4096维逻辑态；使用独立验证的编码等距映射、小型17q实际资源producer和native kernels。扩展单patch接口，使用有证明的GHZ/parity表示与顺序raw Born采样替代宽cat的全字符串枚举。输出每个真实native gate/measurement ID、signed sectors、resource epoch、frame ledger、终端读出及因子后处理。独立检查任意输入/小型纠缠probe与source circuit、全部资源一次消费和未参与patch状态保持。这里不构造204+原子的全局dense态，也不宣称ENV已执行。

**B：一份生产资源到一个PBC旋转的实际反馈小闭环。** 先用预声明Clifford X/Z cat完成准备/核验→读取committed报告→accept继续或abort且未触碰data→破坏性读出/RESET→一次消费账本。随后明确非Clifford结构化状态/Born、checkpoint/RNG及重放合同，接实际T资源和工厂。不得以reference bit填进物理measurement_results。

**C：完整平台排程和demo。** A/B合同成立后，在声明的有限布局上将12算法patch、工厂、辅助和缓存映射到物理原子；所有门/运输/测量/RESET经过当前validator/Executor，统计实际峰值、总时长、拒收成本和独立original-initial重放。demo从同一提交trace显示算法、工厂和库存。非Clifford态接口属于另一个具体实施设计，本轮没有改变环境、硬约束或架构。

本轮重新执行Factoring旧G1的四套测试：quantum15、runtime17、platform18、artifacts8，共58个不同测试通过；不加入QEC历史913计数。活跃G1.1源码在审查期间变化，旧运行包的hash和新实现不能混为一份验收。没有新QEC物理运行、完整编码Shor、含噪FT或浏览器验收。

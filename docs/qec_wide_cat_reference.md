# 完整编码线路使用的宽Pauli cat参考核

`wide_cat_reference.py`提供实验层的理想原生cat片段与可扩展精确仪器证明。它支持最多63个物理Pauli因子，覆盖12个算法patch全部为Y、另加Z资源patch的最宽联合测量。旧的16cat全raw审计保持原限制；本模块使用独立的算符分解证明。

## 生成的具体操作

`build_wide_cat(PauliProduct(...), namespace=...)`返回`WideCatInstrument`。其`program.operations`是有真实ID、目标和依赖的完整原生序列：

1. 将本轮cat与verifier资源显式RESET为零。
2. 首cat作用H，再以相邻`H_target CZ H_target`展开的CX建立GHZ。
3. 两遍测量每对相邻cat的ZZ：verifier RESET、两个原生CX、MEASURE、RESET释放。
4. 每个cat只耦合一个物理数据因子。X使用原生CX，Z使用CZ，Y使用实际顺序`CZ → H_data CZ H_data → T_cat T_cat`。最后两门的S相位必须保留，完整矩阵等于CY。
5. 每个cat依次H、MEASURE、RESET，保留每一个raw report。

片段不RESET算法数据、不修改syndrome辅助位。完整线路生成器负责在它前后组成实际canonical syndrome banks。输入资源须新鲜为零或经上一轮真实MEASURE/RESET释放；资源池生命周期由生成器审计。静态片段自身没有生产Executor的接受／拒绝控制器。

## 仪器证明和编码边界

`certify_wide_cat(item)`首先核对整个片段的门、目标、顺序、DAG边、角色、measurement sidecar、signed observable以及资源释放。然后从实际发出的门构造局部复矩阵：

- 首H和每个相邻CX通过归纳建立两臂GHZ，复杂度与cat长度成正比。
- 逐个实际三比特核验电路收缩得到`K0=diag(1,0,0,1)`、`K1=diag(0,1,1,0)`，故理想GHZ上的两遍核验均为零，且不改变两臂相位。
- 每个实际controlled-P片段精确等于`diag(I,P)`，实际读出H给出X基bra。

对全部raw字符串b，完整数据Kraus算符为：

`K_b = 2^(-(L+1)/2) [I + (-1)^m P_signed]`。

其中`m = XOR(b) XOR int(physical_product.sign == -1)`。这给出每个raw分支及整体完备性`sum_b K_b†K_b = I`，不枚举`2^L`字符串。算符恒等式在任意外部纠缠态上成立，不仅比较单比特边缘概率。

编码资格使用现有实际136门H/CZ CSS encoder，在512维本地物理空间核对X/Y/Z逻辑intertwining以及八个稳定子。带符号sector采用明确约定`V_s=E_s V`：对所有256种syndrome，GF(2)求出与两个逻辑X/Z均对易的物理Pauli `E_s`，检查原始十个约束，rank为10。由对易关系，逻辑轴在这些sector保持同一方向。若调用方选择会反对易逻辑轴的其他sector correction，必须自行将其逻辑frame符号计入测量期望，不能把本核的约定直接套用。

证书缓存以冻结的完整native对象为键，并执行完整对象相等比较；返回值为独立副本。局部矩阵缓存以实际门类型和局部目标位置的完整序列为键。变更phase、顺序、依赖、读出翻转或释放门不能借助缓存通过资格。

## 真正逐raw记录的Born采样

`sample_wide_cat(item, signed_expectation, rng, forced_raw=None, certificate=None)`要求调用方当前归一化逻辑／资源／参考态上`P_signed`的期望值。其返回`WideCatSample`：

- `raw_results`：每个真实MEASURE gate ID对应的报告位。
- `reset_results`：每个真实RESET的投影位；已测量目标使用其实际上一报告，随后输出为零。
- `projection_records`：按实际native顺序包含全部M和RESET，给出条件零概率、选中概率及具体目标。
- `semantic_branch`、逻辑分支概率、完整raw分支概率／对数概率。
- `coefficient_phase=1`：资格矩阵已保留CY的复相位，Kraus前系数为正实数。

核验报告的条件概率为1。前L−1个cat raw位条件概率各为1/2；最后一位的条件概率由实际前缀XOR及signed Born期望得到。将raw suffix求和可严格推出这些前缀概率。完整raw概率是逻辑分支概率除以`2^(L-1)`。

`forced_raw`只允许真实原生MEASURE ID及整数0／1，是离线资格审计的postselection。零概率分支被拒绝；不存在虚构的XOR测量键或向生产执行器注入强制测量值。生成器随后必须用同一个m施加归一化逻辑投影，并保留资源读出和frame反馈。

## 本轮验证

2026-10-04：`tests/test_qec_wide_cat_reference.py`最终 **29项通过，0.58秒**。初版28项0.76秒、加入精确对象证书缓存后28项0.50秒均为先前同套验收，不能额外累计。测试包含：

- X/Y/Z、正负符号的所有小raw分支，独立完整native稠密执行，保留随机外部纠缠输入；逐分支复L2、不剥离global phase、raw概率和全分布均核对。
- 63cat完整符号仪器及真实M／RESET记录、逐前缀Born规则、确定性分支。
- 八类native／sidecar／核验合同篡改、非法期望、虚假强制ID、零概率核验／cat分支的拒绝。
- 全部256 signed sectors：独立固定CSS orbit、每半边穷举512个候选Pauli mask，不复用资格器GF(2)求解器；独立原生encoder执行与稳定子符号、完整复数X/Y/Z矩阵均核对。缓存结果不能由调用方修改。

命令使用bundled Python，`PYTHONPATH=artifacts/shor15-publication-deps;C:\Users\yuyqp\Documents\ChatGPT\QEC-schedule 2\artifacts\qec-pbc-test-deps;src`，执行`python -m pytest tests/test_qec_wide_cat_reference.py -q`。第一次仅配置src时缺少pytest依赖、未收集测试；补充已有只读依赖后完成上述验收。

本核的证据是理想原生线路语义。没有真实中性原子运输／计时、生产非Clifford态跟踪、含噪容错、魔态蒸馏工厂或故障阈值证明。

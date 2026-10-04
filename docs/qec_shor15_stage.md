# d=3 surface-code Shor：阶段实现与验收

目标是把完整 N=15、a=2 Shor 通过 Pauli-based computation 和 d=3 rotated surface code 接到中性原子的 PhysicalCircuit、真实调度与 Executor。每个算法逻辑比特使用9个data与8个syndrome原子。

**2026-10-04新增完整12wire编码原生分支生成与理想参考验收。** 最终seed0实测phase128失败→12patch实际读出复位→phase64验证order4、得到3/5；两shot保存11,243,634个native门、2,402,810条投影和7000次资源消费，独立完整流／复幅／终端Born审计通过。215个本轮不同测试（65新＋150旧）通过，259modules架构零违规，逐功能浏览器验收通过。入口为[完整生成器](qec_encoded_shor_native.md)、[逐操作视图](qec_encoded_native_visuals.md)、[可移植摘要](../references/qec_pbc_validation/full_encoded_shor15_native_2026_10_04.json)和[本轮日志](../instruction/logs/2026-10-04-full-encoded-shor15-native.md)。这是裸T／7T资源与qualified native kernels的完整编码参考；完整physical Executor、工厂和带噪容错仍未实现。按最新用户协议，下一主线先做工厂到同一资源的单T闭环。

以下保留此前组件验收与物理ZZ/XX的历史范围，不能将旧组件“未接完整算法”误读为新增生成器未完成。历史 **913个不同测试** 为912clean＋1original；本轮215含已有回归，不与913直接相加。此前RAG51/44/36、256modules与真实三轮ZZ／XX证据见[旧日志](../instruction/logs/2026-10-03-shor15-autonomous-stage.md)，旧访问冲突现场保持。

| 层 | 本阶段行为 | 限制 |
| --- | --- | --- |
| 完整编码 native（10-04新增） | 12算法patch、全72源门／28CP、3500资源/shot、63cat宽核、24-image frame、8终端读出与真实失败重试；逐功能只读回放 | 285声明身份池不是物理peak；kernel分解理想参考，无工厂／运动排程／Executor／FT |
| Shor 算法 | 12 wires、72 酉门、8 测量；模幂、完整逆 QFT、周期验证、gcd、失败重试 | 精确理想逻辑参考；原始72门源保持 |
| 完整 Clifford+T | 全部28 CP保留并综合；默认8993门、3500次T/Tdg消耗 | ε=1e-3预算，独立完整QFT算子误差6.78e-5 |
| 算术 PPR | 5 个 CCX 精确分解为 35 个 T/Tdg，带 signed Pauli 与 residual Clifford | 不包括逆 QFT |
| 资源测量桥 | 显式 magic resource、联合 Pauli 测量、资源 X 读出和条件 Clifford/Pauli 反馈；完整Shor已执行3500资源/7000测量 | 完整算法仍是理想逻辑 instrument；单patch编码消费参考另列 |
| 完整 Clifford frame | 24个signed generator、真实m/r改变后续测量标签、保留完整纠正ledger与residual；终端在未兑现frame的向量上实际投影 | 理想逻辑controller；已完整恢复3/5，尚未接committed native measurements与encoded资源 |
| 编码 ZZ/XX | 完整辅助 d=3 patch；前后各三轮 checks、18 个 transversal CZ、保留两个输出 patch | 51 原子协议；理想完整 instrument，native-fault parity audit 范围另列 |
| 编码连续组合 | 接收既有 A/B 编码态与 syndrome 历史，显式消耗并重新制备 C；同 C 连续 ZZ→XX | 53 roles 含两个外部 reference、4081 native；理想 native-channel 验证，尚未物理组合执行 |
| 编码 mixed X/Z | 已准备的两patch signed product，cat制备与两遍核验、完整耦合、真实读出/RESET，同辅助原子连续非对易测量 | 41 roles（Choi另2ref），默认新增1295native/106detectors；核验边界仅参考审计拒绝，尚无生产abort/retry、Y/FT或物理执行 |
| 编码 mixed X/Y/Z | 独立native envelope，CY明确CZ→CX→cat上两T，保留prefix/真实signed sectors/ref；连续非对易复用，并接收已验证native prefix | 35原检查保持；参考只严格合并相邻隔离TT=S，未扩生产PBC IR或tracked ENV；无FT/physical，资源消费另列 |
| 编码资源制备参考 | 17个原子全部RESET、原生H/T/CZ编码isometry，最后一轮8个真实syndrome投影；正负资源均实际dense执行 | 251/257native、23新增检查；从裸T制备，无FT/factory，tracked ENV仍拒绝T，未物理执行 |
| 编码资源消费参考 | 实际17q资源输出→qualified signed联合测量→9data H/M/RESET→逻辑X读出→frame/consumed；两个非对易资源同R重制备 | 单算法patch与至多一reference；3641native/51declared/666投影，36新检查；分解参考，未接ENV或全12patch算法 |
| 物理执行 | ZZ/XX各51原子、1860native，294真实模拟CZ脉冲/max3；全部运输、RESET/M/CZ经过普通Executor，14＋4审计和完整初态重放通过 | legacy终态268091.2/268092.2μs；不含初态布局准备、transport/idle/loss 噪声或整体 Shor |

## 核心入口

```sh
python -m pip install -r requirements-shor15.txt
python examples/run_shor15.py --seed 7 --output artifacts/shor15/logical
python examples/run_shor15_stage.py --seed 7 --fault-audit --output artifacts/shor15/stage
python examples/run_encoded_parity.py --basis Z --rounds 3 --seed 0 --output artifacts/shor15/zz
python examples/run_encoded_parity.py --basis X --rounds 3 --seed 7 --output artifacts/shor15/xx
python tools/query_qec_pbc_rag.py --check
python tools/query_qec_pbc_rag.py --self-test
```

完整QFT综合使用独立、固定的纯Python核心，详见[依赖与误差合同](qec_qft_synthesis.md)：

```sh
python -m pip install --no-deps --target artifacts/qft-synthesis-deps -r requirements-qft-synthesis.txt
# Set PYTHONPATH=artifacts/qft-synthesis-deps;src on Windows (colon on Unix).
python examples/run_shor15_stage.py --complete-pbc --epsilon 1e-3 --seed 7 --output artifacts/shor15/complete-pbc
```

完整测量执行分别检查算法零输入和一般data-reference纠缠输入，每次全部3500资源consumed；instrument复振幅误差约1.05e-13，整体算法对原精确Shor的L2误差分别3.57e-5/2.53e-5，均在预算内。来源bit order、residual Clifford、整数相位和外部整体相位明确保存且实际执行。14新增综合测试通过，发布副本复验另记。

完整PBC的输出继续执行8项phase Z投影与经典后处理：seed7实测128失败，下一shot实测192恢复周期4并分解成3和5；两shot共7000资源、14000资源测量和16终端测量。它使用实际PBC态的分布，各shot fresh资源与测量生命周期明确，3新增投影/retry测试通过。

执行证据保存在新的输出目录。已有目录会自动追加 attempt 编号，失败前缀也保留。`animation.html` 来自真实 `VisualRecorder`；`plans.json`、`trace.jsonl`、`schedule.json`、初态和终态 checkpoint 可核对效果、物理时间及独立重放。离线生成动画不等于真实浏览器交互验收。

发生 wall-budget 超时后，用相同协议和 seed 续接已经导出的前缀：

```sh
python examples/run_encoded_parity.py --basis Z --rounds 3 --seed 0 --resume-from artifacts/shor15/zz --wall-budget 2400 --output artifacts/shor15/zz-resumed
```

恢复入口在创建新输出前核对协议、编译结果、平台、初始 placement、seed 与 original initial；accepted plan 的完整内容须与 checkpoint trace 或未开始的 pending plan 相同。它先完成已接受的尾计划，再编译新计划，保留原量子态、RNG、测量历史和绝对物理时间。新的 wall budget 只覆盖续跑；最终独立重放与完整动画仍从最初 initial 开始。部分计划无法导出完整 schedule 时保持原失败与 `null` 统计，不伪报已完成。

历史事件解码默认使用32768条/3GiB的稳定前缀缓存，每次仍审核所有历史与最新状态；超出任一预算的后缀仍解析。旧 LRU 越过16384条会循环淘汰，最初稳定前缀版保留16384条后又在真实16422-event续跑中暴露后缀解析成本，所以仅将entry上限调到32768，3GiB字节界保持。20k条独立回归验证完整热扫描0次JSON重新解析，不把小记录测试外推为任意大trace都拟合预算。已运行的16k进程保留原行为，新进程加载32k；缓存命中只复用不可变字符串的解码，不构成验收通过。snapshot/schema及物理条件不变。

快照摘要另有至多1项、1536MiB保守引用预算的复用。每次重新canonicalize全部非trace字段，完整比较immutable trace值；只有完整序列化前像相等才复用SHA。同version嵌套编辑、history首尾分叉、自定义encoder、非exact字符串/keys及超预算均由独立canonical JSON/SHA预期验收，21项新增检查在干净发布副本通过。小型实际候选编译的三次同摘要成本由124.79ms降至80.79ms，仅是该只读profile；不能推断整段物理运行倍率。缓存不省略任何物理或历史校验。

物理场景在执行前声明全部 EZ/MZ sites，三块以 70 μm 横向偏移放置，data 间距 20 μm。AOD 为同一台 7×14、98 交点，沿用原硬件默认、容量、碰撞、空阱扫掠、光照和全 EZ CZ pair 校验。场景的有限区域更宽以容纳三块；没有在策略内部新增 trap 或放宽 validator。两块原平台保持原样。初态是已排好的 EZ holder，量子态仍从物理零态开始，所有编码制备在真实 circuit 内完成。

远端 main 与本地未发布的 Enola 默认参数不同。本阶段发布验证从远端 main 的独立工作树进行，其实际硬件记录在 `platform.json`，不能混用本地历史计时。

## 验收边界与下一步

完整 Shor 的理想态向量对照独立 FFT；一般复数且与 work 纠缠的 QFT 输入也单独测试。编码 ZZ/XX 通过两个分支的 Choi 对照确认保留外部纠缠；零/单 native fault 的 classical parity decoder、独立传播及三报告位距离 witness 另验。它们不构成完整噪声条件下保留量子输出的容错证明。

独立 `encoded_parity_program` 包含输入 patch 的制备/RESET。连续线路使用新的 [`append_encoded_parity`](qec_encoded_composition.md)，保留 prefix、A/B data、全部测量记录与 syndrome sector 历史。默认分配 fresh C；`resource_reuse=True` 只在完整 C 的 9 data 明确 MEASURE/RESET、8 syndrome RESET/released 后允许使用同一组原子，下一 epoch 仍真实执行 C RESET/reprepare。ZZ→XX 同 C 实跑 53 roles/4081 native，两个外部 reference 保留；逐阶段全部 256 个逻辑/reference Pauli 期望、144 detectors、16 closing sectors 验证通过，25 项组合测试通过。这里的复用是联合测量辅助 patch 生命周期，不代表 magic factory 已实现。

12个算法patch基础为204原子，完整新生成器声明285身份池，实际硬件峰值未定。CP综合、完整PBC／frame、XYZ编码测量和全12patch编码native参考已完成。生产主线按最新工厂供应协议先固定15-to-1及d=3模板，完成接受／拒收／清理／补产→唯一库存和同一载态资源交付→单T消费／frame的参考闭环；再处理受限非Clifford Born、ENV committed控制和original initial重放，之后逐周期带噪、MSC backend、连续T和完整物理Shor。控制器只能提交／推进，不写live state、伪造XOR测量键或替换live DAG。新增generator不能替代工厂验收。

[实际后端需求审计](qec_shor15_encoding_requirements.md) 从完整导出逐项统计：3500 项 joint measurements 中2325含Y、3138混合basis，最大weight9。这给下一阶段的协议范围提供具体输入，避免以双patch ZZ/XX覆盖整个算法的假设。

[mixed/Y 后端设计](qec_mixed_pauli_backend_design.md) 给出保留9+8 patch结构的分布式cat测量、signed Clifford frame、显式 Clifford-resource 纠正和原生报告位的控制接口。可发布公式审计工具复建144纠正分支与64非对易注入分支，误差小于6e-16；这是数学/reference验算，没有把后端、FT或physical能力改成已实现。

[完整frame实现](qec_conditional_clifford_frame.md)每次只投影真实`F†PF`，纠正留在24-generator frame与完整复相位ledger中；最终测量`F†C_res†Z_jC_resF`而不重采样eager结果。完整3500-resource零输入与纠缠reference对照通过，兑现frame后对eager L2误差约1.26e-14，对原CT约1.05e-13。fresh framed Shor seed7/8/9实际读出128/0/192，失败保留，第三次验证周期4与因子3/5；共10500资源、21000注入测量与24终端投影。该seed7实际标签含Y2168项、mixed2437项，data最大12/joint13；固定3/5代表的cat模板最大45（18项），仅为template shape，资源峰值未定。分批终端读出仍保存完整namespace/history/dependencies。27项新增独立检查已在干净发布副本验收，native S/encoded/FT/physical均保持false。

[mixed X/Z native参考](qec_mixed_xz_cat.md)已实现signed `X_A Z_B`的完整cat线路，保留原prefix/data/sectors与外部纠缠。全部64个raw cat-X报告组合逐分支Choi验证，正/负号和两semantic分支正确；连续非对易`X_A Z_B→Z_A Z_B`同7cat/verifier原子真实再RESET，两个边界均核对256个logical/reference Pauli与16 stabilizers。默认3+3轮新增1295native（735H/319CZ/129RESET/112M），106detectors；41项新增检查与54项旧PPM/组合回归在clean联合95通过。它将核验结果/边界显式导出，静态compile不会主动abort/retry，未来物理controller须在数据耦合前等待真实核验并拒绝异常。没有Y、magic factory、噪声FT或完整Executor声明。

[编码资源制备参考](qec_encoded_resource_reference.md)独立生成真正PhysicalCircuit，GF(2)可逆编码网络为44个CNOT（全部H–CZ–H展开），把任意logical input等距映射到标准[[9,1,3]] codespace。正资源用1个T，负资源用7个T，实际成本全部保留；完整17原子RESET与最后8次syndrome测量由131072维dense reference逐门执行，正负复振幅L2误差1.11e-16/2.22e-16，全部stabilizer/aux残差0。23新增与9相关旧检查在clean联合32通过，静态码距3另验；这尚未接入PBC GateTask或tracked ENV，也未证明制备线路FT。

三轮 ZZ 的真实物理模拟验收已完成：51原子、1860native、456plans、19212committed events、294CZ脉冲（最大同时3对），136detectors全0。logical completion为267201.2μs，包含归还的terminal为268091.2μs，采用远端legacy默认。量子reference、保留输出coherence/18约束、效果各一次、依赖/资源/终态和从original initial的完整plan replay均通过；续跑及核验wall1370.254s、进程exit0。首轮失败与两个Timeout前缀保持，布局准备时间不计且为null。

XX两次Windows访问冲突0xc0000005的原档保持失败记录。verification-only attempt2在新目录实际exit0：保存state全审计、全部457plans/1860native从original initial重新submit/run，最终完整canonical snapshot字节及EOF一致，full recording/animation/schedule/evidence均实际导出。actual19214events、294CZ pulses/max3、136detectors全0，logical267202.2μs、terminal268092.2μs；14个topboolean与4个quantumboolean全部true，包括16signed output sectors/18coherence约束。wall1454.117s只计本次审计/重放/导出，原crashed总wall保持null，未重新forward或准备输入。原checkpoint/plans/trace/initial及十个关键原文件bytes/SHA全同。见[XX摘要](../references/qec_pbc_validation/encoded_xx_physical_r3.json)与[两基汇总](../references/qec_pbc_validation/encoded_parity_physical_r3.json)。3原未捕获来源、缺decisions/candidatehistory仍unknown/null；没有新浏览器/噪声FT/完整Shor声明。

详细协议见 [完整 Shor 参考](qec_shor15.md)、[编码联合测量](qec_encoded_ppm.md)、[资源测量桥](qec_adaptive_pbc.md)；事实与实现快照见 [RAG](qec_pbc_rag.md)。


[含Y的原生cat参考](qec_mixed_pauli_cat.md)已在clean通过35新＋41旧XZ联合76检查。单±Y全部32raw编码Choi分支，±XYZ全部2048raw、±YY全部1024raw的完整受控因子/GHZ/真实读出bras逐项核对；真实三reference probes各检查4096个Pauli期望。非对易−Y_A X_B→Y_A Z_B全部四分支同9辅助原子真实MEASURE/RESET复用，保留signed incoming与外部纠缠。public allraw审计先严格核对完整native tail/sidecar/DAG，六种突变均拒绝；旧未资格产物保留且排除当期证据。最大qualified Kraus误差2.39e-16。13patch/12Y+资源Z的63cat/285roles/24T仅结构编译例，不是完整channel或物理peak。原生T没有被删除，参考TT=S资格不允许单T、中间fault、竞争后继或wire绕过；core仍拒绝tracked T。

XX中断事实与已有checkpoint检查见[原样保留的事故摘要](../references/qec_pbc_validation/encoded_xx_physical_export_interruption.json)。独立export recovery只重新审核与重放，不能伪补原始completed文件、重做输入制备或由缺失decision log推断成功。已实现的逻辑frame和native XYZ reference仍需生产committed-report控制、非Clifford状态表示与资源消费执行才能连接成完整physical Shor。


[导出恢复入口](qec_encoded_export_recovery.md)只接受native DAG已完成、pending为空的冻结checkpoint，先核对所有输入、seed、11个原文件指纹、launch source与父级plan/trace完整内容，再复用原completed quantum/effect/timing/resources/retained-output审计。最后必须从original initial逐个真实submit/run所有plans，比较完整canonical字节与EOF，重新生成完整VisualRecorder。逐record/plan导出不改schema或任何physical predicate，原档案及其子目录禁止写入。缺scheduler decision log明确unavailable、candidate history为null；三个原未捕获的实验依赖原SHA保持null，不能声称全部原源码一致。

新43项与13既有fast检查在clean联合56通过（18.24s），原1977s完整恢复对照已完成而未重复；不同nodeids总842=841clean＋1original，255modules0违规。轻量fixture只有三个真实RESET/H/M物理门，并显式替换encoded-output检查，只验证恢复机制。实际152个captured source依赖匹配，已复核shared runner316519→eb580仅提取原predicate与compact audit。三轮XX verification-only重放进程再次访问冲突exit1，最后落盘321/457plans、1310重放门，尚未通过完整初态重放或导出。真实faulthandler定位runtime prefix cache插入的深dataclass hash路径，Python机制仍未知；现采用局部cache certificate修复并独立验收，保留完整原值相等检查和每一物理predicate。原保存1860门完整state及两次失败档案不改。

cache certificate已冻结，只以exactstr plan.id作hash bucket，用完整旧13-field tuple判等；保留32项LRU、cursor/fork、全部origin/transition与物理predicate，exclusive/non-reentrant context正常或异常finally恢复原function/cache对象。35新增检查包含强碰撞、每个旧静态字段变动、同ID不同body、poison CompiledPlan/PhysicalCircuit hash零调用、冻结证书拒绝修改和真实短恢复。clean43旧recovery＋35new＋13oldfast联合91通过23.36s，该阶段总877=876clean＋1original，255modules0违规。第二事故与stream指纹见[恢复重放事故摘要](../references/qec_pbc_validation/encoded_xx_recovery_export_interruption.json)；随后启用此adapter的XX完整重放与导出已实际通过，Python崩溃底层机制仍未知。

[编码资源消费参考](qec_encoded_injection_reference.md)从caller提供的未知A.d0/reference开始，真实16RESET与136gate CSS encoder保留该输入；实际17q producer的输出进入18data＋reference向量，joint cat和canonical banks逐资格native边界收缩，资源9H/9M/9RESET真实投影。完整三轮双非对易注入导出3641native（H2062/CZ903/T10/M288/RESET378）、666投影记录和51declaredroles；旧cat角色已释放但仍列于线路，不当作物理峰值。正负资源、signed X/Y/Z的48单分支与16双分支独立复矩阵/Choi/相位核验，修正后最大L2约1.77e-15；独立512 raw Fourier bras/32nonzero及grouped Choi误差1.39e-16。最终36new＋35oldY clean71通过119.86s，36差集与877无交集，总913=912clean＋1original，256modules0违规。

receipt在任何frame或生命周期修改前校验真实native prefix/资格/hash、完整raw history、27门有序资源suffix和固定X0/X3/X6逻辑读出。此理想instrument的两个logical conditional概率必须为0.5±2e-11，0.75与越界mutation拒绝且不部分消费；正常/容差边界独立核验。它接收本参考真实投影的结果，尚未接ENV committed reports；没有全44/51角色逐门dense或完整12patch Shor声明。可复现入口为`python -m neutral_atom_experiments.qec_pbc.encoded_injection_reference --rounds 3 --seed 7 --output NEW_JSON`，更多参数与实际输入boundary见该文档。

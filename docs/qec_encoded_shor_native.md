# 完整12逻辑比特的编码原生线路生成

`encoded_shor_native.py` 将完整 N=15、a=2 的 Clifford+T／PBC 程序展开为一个实际采样分支的 d=3 编码原生门序列。8个phase和4个work逻辑patch共204个算法原子；一个可复用17原子资源patch和63个cat槽＋1个verifier使声明池为285个原子。池大小是声明的可复用身份数量，不能当硬件峰值或工厂成本。

用户于2026-10-04批准实施完整生成器，并要求每项功能的操作可视化。本模块输出同一次运行的原生门、真实参考投影、功能范围、frame、资源epoch和证书；可视化读取这些数据，不能另外编造物理运输或时间。

本成果是已批准的完整编码线路独立参考，不代替工厂主线验收。后续按用户最新共享协议先完成工厂生产→同一载态资源的库存／交付→单T消费闭环，包含拒收、清理、补产和唯一消费，再接入连续T与完整物理Shor。本版raw producer不等于MSD或MSC。

## 输入如何核验

CLI读取旧完整参考包的三个文件，重新构造并检查源72个门、全部28个逆QFT CP、84个Rz、完整CT跨度及全局相位。每个非CP源门必须与固定Clifford+T分解完全一致；每个CP必须包含正确轴／角度／顺序的三个Rz及两个CX。84个实际2×2 Rz矩阵逐个做复相位敏感核对。原来额外三个外部相位／位序wrapper字段单独核对；未知扩展或同步篡改CT与PBC不会因二者互相吻合而获准。随后从实际CT重新编译PBC，与经过dataclass验证的缓存逐项相等。

完整线路不输入周期或因子，不删除基于已知阶的CP。经典后处理在终端八个真实参考投影之后运行，失败样例保留，下一shot重新制备算法寄存器与独立资源epoch。

## 因子化的编码执行

- 算法patch执行真实H/CZ CSS encoder，两个完整复幅列与独立CSS投影码字一致。未知输入d0和外部reference保留，其余16个角色显式RESET；完整Shor零输入可以RESET全部17个角色。
- 正／负资源模板各实际执行一次完整17比特H/CZ/T/MEASURE/RESET稠密参考，检查资源码字、相位和八个syndrome释放。之后每个新epoch展开完整原生模板，并复用已经核验的零输入boundary kernel，明确记录这种复用。没有宣称3500次重新做17比特稠密模拟，也没有直接用预置理想魔态向量冒充制备。
- 稳定子bank使用实际18比特编码Bell／reference Choi执行得到的完整原生恒等channel证书。所有M／RESET行都绑定原始核投影记录；任意保留逻辑纠缠由channel等式保证。
- 宽Pauli联合测量使用`wide_cat_reference.py`：native GHZ、两轮相邻ZZ核验、正确的受控X/Y/Z、H／M／RESET全部展开；逐个实际local矩阵及完整GHZ结构核验后，依当前逻辑态期望值顺序采样raw cat位。它不枚举指数数量的raw组合。
- 资源9data读出通过实际九个H作用于两个CSS码字，得到全部512个完整复幅bra。仅32个可能模式用于缩小中间数组，零模式仍保留在完整资格检查中。raw位按条件Born概率顺序投影；逻辑X固定为d0、d3、d6的XOR；九次实际RESET随后释放载体。
- 完整signed Clifford frame保留24个生成元及修正ledger。联合Pauli始终是当前frame拉回的有符号轴，实际raw报告的XOR决定m／r，资源只能消费一次。资源身份包含shot和epoch，复用的是全部释放后的物理角色。
- 最终输出测量实际展开为native cat测量 `F† C_res† Z_i C_res F`；未把残余Clifford丢弃。语义校验另外实现frame及残余Clifford，完整复幅与独立CT输出比较，并保留PBC和外部合成全局相位。
- 需要重试时，每个算法patch先做全部9data的真实编码Z-bra投影，再逐个RESET，之后的known-zero输入核才可用于下一shot。

算法patch名称`resource`是保留物理资源角色，入口在创建输出目录前拒绝别名。失败shot的门／投影数量包含它自己的全部cleanup，另列cleanup数量；所有shot成本之和等于完整native流，界面也可从实际function范围重算。

运行期保留4096维算法逻辑态，资源读出中间数组只使用32个有效bra；没有构造204或285个原子的全局稠密态。所有“真实投影”均指这个明确声明的理想参考instrument，`environment_committed_reports=false`、`physical_executed=false`。裸T制备、受控Y的两个T以及cat verifier理想核不构成容错证明；没有蒸馏工厂、运动调度、硬件微秒或噪声／保真度结果。

## 运行与输出

新clone可从已发布源码重建缓存；不依赖本机忽略目录。使用Python 3.12或更新版本与隔离依赖：

```powershell
python -m pip install --target artifacts/shor15-deps -r requirements-shor15.txt
python -m pip install --no-deps --target artifacts/qft-synthesis-deps -r requirements-qft-synthesis.txt
$env:PYTHONPATH='artifacts/shor15-deps;artifacts/qft-synthesis-deps;src'
python examples/run_shor15_stage.py --complete-pbc --epsilon 1e-3 --seed 7 --output artifacts/shor15/complete-source
python examples/run_encoded_shor15.py --cached-source artifacts/shor15/complete-source --output artifacts/shor15/encoded-native-seed0 --rounds 1 --seed 0 --max-attempts 4
python tools/audit_encoded_shor15_run.py --run-dir artifacts/shor15/encoded-native-seed0 --output artifacts/shor15/independent-audit.json
python examples/serve_encoded_shor15.py --run-dir artifacts/shor15/encoded-native-seed0 --port 8769
```

打开`http://127.0.0.1:8769/`逐功能查看。当前本机最终验收页为`http://127.0.0.1:8772/`。完整流为GB级，需预留磁盘；生成器流式写入，查看器有界读取。独立审计使用NumPy及标准库，不导入项目量子模块；SQLite旁文件用于核对全部原生ID唯一性。

输出目录必须不存在；失败和成功都保存manifest。完整缓存来自已核验旧阶段包，CLI无需重新下载合成器或修改ENV。`--rounds`选择每个显式bank的syndrome轮数；d=3是码距，理想一轮和三轮都不能据此报含噪容错。

| 文件 | 内容 |
|---|---|
| `summary.json`、`shots.json`、`terminal.json` | 所有shot及失败、资源数量、终端raw来源、阶寻找和因子 |
| `native_gates.jsonl` | 实際原生门、唯一ID、物理角色绑定、完整串行依赖和epoch |
| `native_projections.jsonl` | 每个MEASURE／RESET恰好一个核或条件Born记录 |
| `functions.jsonl` | 功能、来源、gate／projection字节范围、数量及SHA、核证书、frame和生命周期 |
| `frames.jsonl` | 可显示的24个有符号生成元、ledger长度和此次修正；SHA可定位 |
| `roles.json` | 固定原子池、patch角色、实际check与逻辑X／Z支持 |
| `certificates.json` | producer、CSS、canonical、widecat、raw读出kernel及精确原生模板hash |
| `shotN_unrealized_state.json`、`shotN_semantic_state.json` | 终端M前复幅、完整frame及语义实现后的输出 |
| `complete_clifford_t.json`、`shor15_circuit.json` | 核验后原字节复制的便携独立对照源 |
| `input.json`、`manifest.json` | 完整PBC输入、原始来源hash、全部运行artifact字节数／SHA |

功能span的hash绑定实际输出流；核证书hash绑定局部原生role模板。全局生成器把局部依赖序列化并绑定Q身份，因此两种hash有不同含义，不能直接声称它们相等。独立审计应反向映射role并检查template signature，再检查完整流ID／投影／依赖／反馈及语义。

普通测试验证小型任意纠缠输入、非对易正负轴、reference保持、完整复相位、每个原生投影的一一对应及字节范围hash。完整12wire运行与独立artifact审计是另一步验收，结果在当次日志和阶段入口记录；这里不把历史通过计为新运行。

## 2026-10-04实际验收

最终seed0运行完整保留失败和重试：phase128未恢复阶，12个算法patch执行216个实际读出／RESET后，phase64验证order4并得到3与5。两shot共7000次资源消费、11,243,634个native门、2,402,810条投影、94,352个功能；wall222.731s是参考生成耗时，不是量子硬件时间。独立整流审计80.924s通过，两个完整复幅对CT的L2误差为2.3734e-12／2.4040e-12，对精确Shor为3.5688e-5，两个实际终端分支Born概率误差均小于1.04e-12。输入保留全部28CP，没有提供阶或因子。

seed7单shot另有5,951,556个门／1,269,619条投影，phase64成功，独立整流审计通过；seed8单shot6,704,145门／1,445,781投影同样成功，但未再独立整流审计。不同raw分支改变实际轴和辅助门数，不能只选最小门数代表完整成本。最终seed0使用保留角色别名／失败cleanup计成本两项工程修复后的源码；更早seed7/8保持其原始证据，不伪称重新生成。

本轮215个不同测试通过，其中65新增（生成10、wide cat29、视图26）和150已有回归。独立12logical＋1reference、63cat的一般复幅三资源探针误差2.46e-15；全部4096模幂基态和完整256维逆QFT源算子另核对通过。六种同步修改CT／PBC的真实缓存反例均拒绝。真实浏览器八类功能、子阶段定位、门／报告分页、frame下一轴、重试与390px布局已验收。可移植数字和artifact指纹见[公开验收摘要](../references/qec_pbc_validation/full_encoded_shor15_native_2026_10_04.json)，详细环境／失败修复见[本轮日志](../instruction/logs/2026-10-04-full-encoded-shor15-native.md)。

重试单元测试使用12wire、单T、零输出的明确合成CT探针，让两次真实参考读出都得到0，从而核对全部cleanup／成本／释放；它不作为完整Shor证据。完整Shor CLI须先通过上述72源门和28CP输入核验。六个真实缓存副本的人工篡改验证还同步重新生成了下游CT／PBC：非CP门、CP轴、CP的CX、外部相位、误差预算和PBC wrapper相位均被相应源核验拒绝，这组验收单独记账。

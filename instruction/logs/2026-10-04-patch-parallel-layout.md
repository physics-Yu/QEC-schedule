# 2026-10-04 · Canonical patch parallel layout

- 状态：COMPLETED，能力已验收发布，回执单独追加
- 用户目标：单 d=3 patch 码内并行，10 μm 驻留/非作用间距，评估 Enola 单块优化并复制多块，接入真实 physical pipeline 与共用可视化。
- 基线：f36c772，既有3006门12patch真实前缀68 CZ pulses（每pulse最多12pairs），6 μm有限全局CZ判据。
- 范围：保留canonical phase/hook/native身份，研究合法placement与批次；不改变物理核，不宣称工厂/带噪FT/完整physical Shor。
- 相关规范：qec_factory_pipeline、physics、compiler_contract、research、aod_backends。

## 实现与决定

所有变更在 attached managed checkout、`codex/d3-shor15-stages`；原工作区已有其他任务dirty，不编辑其tracked文件。固定同源 `shor15_native_prefix_seed0_2026_10_04` packet，保持母源/原生门/投影身份，canonical四层H-CZ-H/hook与CSS依赖链未变。固定5μm候选SLM，实际homes/nonpair-at-CZ≥10μm、finite CZ6μm；伙伴3或4.243μm。运输仍用既有连续1μm碰撞/SLM判据，不宣称整段≥10μm。

- 标准interleaved平台：canonical坐标×10μm，局部rigid3×3/20μm相对offset按80μm复制；12块9列×12行108cell，右侧资源仍同源未编码17RESET/H并独立AOD。initial world/envelope显式声明全部备用轴空间。
- CZ选择当前READY、同真实刚性平移/有限偏移、闭包完整的子组；Enola另比较原CZ两端移动者和八落点，真实全局pair-set仍由底座精确审核。MZ服务最大化有限完整local-role束，同载体依赖允许的MEASURE→RESET留同次服务中执行。
- `patch_layout.py`是experiments初态配置；selector/路线在strategies；env/hardware没有导入上层或改阈值。旧默认False/legacy保留。新增功能后的run保存`producer-source.json`实际生产代码hash；早于该功能的标准baseline/CZ-only不倒填当前代码身份，摘要明确not recorded。后续拒绝守卫/注释/观察器修正不改旧录制。
- 作者Enola仅未修改初始SA `place_qubit`：commit2944dbf4e163e8d2eeeec607add0d9139edce689、placer SHA d256c844...，17roles/24couplings/5×5/seed0/l2False。weighted proxy50.6052672685→20.4、无权距596.2475012515→240μm不是μs或fidelity；作者完整scheduler/codegen未用。真实物理配对/运输由本项目adapter。
- 冻结proposal raw SHA `b04b39ba29e6345c26404d289b6d3b441e1f3a92d9fb7ab249cd1b9b2d1b68ae`，mapping49a2c2d5...；`-text`保护跨Git raw字节。adapter核对fixedcommit/placer、role/layer/template/input SHA、全部17坐标和site/SLM一致性。

## 实际执行与对照

本地目录统一 `artifacts/patch-parallel-2026-10-04/`，每attempt独立保留。模型终态含归还。

| 运行 | 原门/投影/原子 | plans | CZ总脉冲 / syndrome脉冲 / 最大批次 | 模型终态μs | 当前证据 |
| --- | --- | --- | --- | --- | --- |
| single-baseline-attempt3 | 267/50/34 | 196 | 68/24/1 | 84684.130701 | 完整replay、独立源/Stim/几何通过 |
| single-intra-attempt3 | 同上 | 182 | 54/10/6 | 79207.855129 | 完整replay、独立layout/transport通过 |
| single-all-intra-attempt1 | 同上 | 164 | 54/10/6 | 40504.465183 | 完整replay、两层独立审计通过 |
| single-enola-attempt1 | 同上 | 161 | 52/8/3 | 33409.196973 | 完整replay、冻结proposal及两层独立审计通过 |
| full12-intra-attempt1 | 3006/413/221 | 182 | 54/10/72 | 79207.855129 | 完整replay、两层独立审计通过 |
| full12-enola-attempt1 | 3006/413/221 | 161 | 52/8/36 | 33409.196973 | 完整初态replay、冻结proposal、两层独立审计通过 |

标准三single的initial/source/circuit SHA逐字相同：CZ-only减6.4667%，全部服务减52.1699%。Enola初态不同，是布局+策略组合比较；不与历史legacy69.9277ms称同平台speedup。canonical标准1/4/4/1物理pulse=10，Enola2/2/2/2=8；逻辑四层及24对不变。标准full12独立核对9401依赖区间、192phases/5856canonical边/1632CSS门、682MOVE/17216载体端点、1311924非伙伴检查，实际min10μm；54次全局CZ=816原对。连续安全由Executor+原初态replay，两层独立audit不把端点检查当连续证明。

## 当前验证

- 14个相关test modules一次合跑174不同pytest通过（28.99s）：patch_layout/service/proposal/endpoint/audit/prefix/report/coreaudit/batchCZ/multiAOD/visualization/环境边界。未跑全仓库suite；后来report修正同7cases再通过不累加计数。
- architecture265 Python modules、0违规。
- 旧HEAD f36c772默认1/2/12patch CZ、2patch MZ、dualprologue共5plans canonicalJSON byte-exact；3份protocol源UTF8/LF相同。ignored `legacy-default-compatibility.json` SHA6417f3fd...，复现脚本probe_legacy_default_compatibility.py；不计为额外pytest。
- full12 Enola已通过完整replay及两层独立审计：9401依赖区间、192phases/5856canonical边/1632CSS门、479MOVE/16304载体端点、1263304非伙伴检查，实际min10μm。recording SHA `2ea57024eb909b045e5ddd8501491fdce2cc549fc9cfef0161f42c488aa577d8`；actual execution+replay wall1264.2641925s不等于物理模型33.409ms。
- 最终真实8774 full12共用report：11书签逐项点击并核对实际时刻/原门，RESET max77/H max72/CZ max36/M max48、四层各2pulse、双AOD同时带载运输及终态3006完成。390/320 viewport分别client/scroll375/375与305/305；主统计展开/逐项折叠、viewport恢复、console0errors。`browser-acceptance.json`和`full12-enola-layer1.png`保留；旧8773页保持。
- 最终full12 Enola的`viewer_fit_resize.cjs`与`viewer_qec_scale.cjs`均实际PASS：同步atom/trap/AOD、104X/Z角色、resize与immutable recording。非pytest不累计入174。
- 精确复现命令、单块占用分类、proposal与范围见[布局文档](../../docs/qec_patch_parallel_layout.md)。
- RAG最终67chunks/56sources/160本地路径；K66/K67与L42–L44保留当前实现/固定作者源码/论文前提，旧claim与历史raw保留。六run摘要同时收录真实browser、Node、旧默认兼容与中心几何边界。原目录此前214bytes核对相同；末次观察209相同、5个政策/参考交接文件由外部并行工作更新，本任务未写原目录且HEAD9e28保持，变化完整保留。
- 只读peer最终发布审查未发现已验收Clifford前缀material blocker；修正历史run的producer-source文案，未扩大测试或新增未来staging完成主张。
- 最终政策v2同步后的RAG source check、67/67检索（含纯调度S1–S3检索）与11/11 portable全部通过；历史raw仍保留。新增一例政策检索不改变67chunks/56sources/160paths。

## 失败、反例与修复

1. single-intra/baseline attempt1 在execution前因严格observer拒绝layout_contract，0committed plans；failure.json保留。仅给observer既有四metadata keys，实验合同另记summary。
2. 两组attempt2的 `AOD_ENVELOPE_EXCEEDED`：boundary60μm跟随时禁用spare40μm轴仍须检查。0plan、failed summary保持；初始平台额外预留50μm备用轴空间并相应右移resource，未跳过审核或改clearance。
3. 固定(-3,-3)偏移在10μm设计中使nonpair9.899μm，拒绝；标准(-3,0)通过。SA四近邻d4下6个CSS反例固定移动端无法满足spacing，pair_search切换原门另一端后44CSS都可合法配对；六对canonical同时捕获含额外data，实际拆为2×3对。静态失败/scale20审计保留，不宣称它们为物理执行。
4. peer独立MOVE审计同时间同轴选到LOAD前frame，报missing移动载荷；trace state_version精确定位committed frame修复，新增反例测试。录制/计划未改。最初多AOD初态字段aod/aods读取KeyError也保留诊断。
5. report拒绝测试最初malformed start_time在layoutguard之前触发KeyError，guard前移；valid新布局render暴露layer统计变量覆盖门Counter，分别命名后legacy/interleaved/enola真实书签回归7cases通过。
6. 只核坐标hash的proposal身份缺口由只读peer发现，root补guard/8tampertests；真实proposal未改。single-SA已经用真实固定proposal运行，full12-SA在guard补齐后开始。运行后仅strategy注释/报告生成器更新，保留各run实际source hashes。
7. 两次文档patch context不匹配无更改、legacy probe默认GBK读取中文失败；修正context/明确UTF8后通过，不把工具读取失败计物理失败或pytest。
8. 发布cached diff检查将`-text`保留的proposal原始CRLF判为trailing whitespace；该文件新增`whitespace=cr-at-eol`明确与旧raw packet相同规则，原始proposal字节/hash不改，重新运行cached check，不豁免实际空格错误。

## 后续能力边界与阶段发布

固定Enola中心d4=(20,20)的四邻ancilla=(10,20)/(30,20)/(20,10)/(20,30)，仅移动单端且旁观位不动：r²≥20|x|、r²≥20|y|推出非零r≥√200≈14.142μm，超过finite CZ6μm；r=0违反1μm clearance。ignored `enola-center-pairing-bound.json` SHA960055ba8549bf7320e10dc1abbd3c3c9ae201e5d15dee063b919a348c57fffb固定proposal与initial。当前prefix的CSS另一端移动和vacated方向提取已执行通过；未来中心跨块CZ须交互暂存位置或旁观ancilla搬移，再实际验收。此必要条件仅限制固定旁观单端直接方案，不是所有物理方案无解。

六run小摘要、冻结proposal与RAG固化纳入本轮发布；大型plans/trace/checkpoint留本地独立attempt。原工作区并行任务的最新用户共享协议v2已只读核对并同步到managed目录，原始SHA308a8710df419b026f125398b6113a89686e01da168e7afc50dbd4f63cabd77a；当前后续是完整工厂调度模块/同token单injection/processor按需接入S1–S3，不要求runtime量子态/Born后端。旧F1/F2量子参考与质量研究保留独立历史范围，RAG政策块加明确supersession；本轮不修改物理核或报告后端。未编码右侧载体不是工厂/库存，本轮没有完整工厂/injection或physical Shor验收。后续受限row_column候选可能进一步合批，但没有本轮production compiler或完整物理执行，不计完成。阶段GitHub回执另在发布后补充，不merge。

## GitHub阶段发布

能力提交[c272356](https://github.com/physics-Yu/QEC-schedule/commit/c272356ff913a561dc6e28708ca691b0483ce5ef)已沿用draft [PR#3](https://github.com/physics-Yu/QEC-schedule/pull/3)发布，不merge；GitHub Git data生成tree与本地index完全相同（b6505a8bc3a886a580c2b592fed80abdf6f83f37）。随后独立Git fetch核对parent=f36c772、完整tree、31个blob ID及staged raw bytes逐字匹配；本地HEAD安全前移到该提交。origin pushurl=DISABLED保持，无git push。

PR标题/正文按最终实现重写，确认draft/open/unmerged，附着到当前任务。[可移植发布回执](../../references/qec_pbc_validation/patch_parallel_publication_2026_10_04.json)固定能力commit/tree、31项原始blob证明及原目录并行变化观察；此回执与handoff单独追加，不回写已发布能力/录制。完整本轮要求已完成；后续能力与模型边界保持上节状态。

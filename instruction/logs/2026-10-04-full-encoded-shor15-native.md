# 2026-10-04 · 完整12逻辑比特编码原生Shor与逐功能可视化

- 状态：COMPLETED（完整编码原生分支、理想参考、逐功能观察器的已批准范围；非完整物理Shor／工厂）。
- 用户授权：批准解释中的方案实施与首次运行，追加每个功能的具体操作可视化；阶段GitHub提交授权保持。
- 基线：clean `codex/d3-shor15-stages` / `d7ef205` / PR #3；原workspace HEAD `9e28b2e` 与其他dirty保留。
- 范围：完整N=15/a=2、8phase＋4work、全模幂/逆QFT；理想编码分解语义与实际原生门分支输出；当前裸T/7T资源，工厂后续。没有预置阶/因子，没有修改ENV/物理约束，不宣称完整物理Executor或FT。
- 路由：agent/handoff、architecture/compiler_contract、visualization/workflow；收尾发现并遵守并行任务固化的qec_factory_pipeline，工厂优先的新主线不被本独立参考成果替代。Factoring15保持只读。

## 分工与验收

- full_encoded_generator：新多patch线路生成、完整source/测量/frame/资源epoch/终端readout与CLI。
- wide_cat_kernel：实际原生GHZ/controlledXYZ的符号化channel资格、顺序raw Born采样、独立allraw小核/宽核反例。
- factoring15_runtime_audit：实际输出驱动的逐功能可视化；百万门采用有界读取，不画未调度的原子运输/物理时间。
- root：整体源码/独立证据审查、完整运行和失败保留、浏览器实际交互、文档/RAG/发布核对。

## 必须保留的边界

每个native M/RESET须有实际小核或已资格分解投影的来源记录，native IDs/依赖/完整signed sectors/反馈/消耗与复位不能省略。每次完整算法需保留3500资源实际生命周期；204算法原子之外的资源、cat、verifier另计，峰值以实际线路账本为准。wide cat不得仅删除旧16cat/6logical护栏而声称验证；完整一般输入channel需要独立资格证明。

可视化覆盖编码、syndrome、magic制备、cat准备/核验、XYZ耦合、cat读出、9data资源读出/复位、frame/下一标签、回收、终端Pauli读出、phase阶寻找和失败重试。数据来源与证据等级显式显示；原生门步数不伪称μs。

## 本轮验证与结果

### 完成内容与明确假设

新增`encoded_shor_native.py`、`wide_cat_reference.py`和运行CLI；完整12patch算法、72源门、28CP／84Rz均核验，不提供阶／因子。每个shot3500个正／负资源，从实际17q native producer资格核获得载态边界，后续epoch展开完整制备模板并复用同一已验证零输入kernel。算法运行保留4096维逻辑复幅；canonical实际18q Choi、CSS两个完整码字、宽cat真实local矩阵／GHZ归纳、9data真实H／测量bra／RESET分别资格收缩。所有实际M/RESET有顺序报告来源，不宣称285角色全局dense，也不宣称每次epoch重做17q dense。24有符号frame生成元、完整ledger、raw m/r、资源消费和reset释放、终端F†C†ZiCF及全局复相位全部保存。

新增`encoded_native_visuals.py`／维护HTML／loopback只读服务器，以manifest和局部span SHA绑定实际功能、12门页、64投影页、角色／check支持、完整frame与资源epoch。功能stage按钮从真实native范围生成，播放1–32门/秒只移动观察索引；无placement、运输或μs。HTML进入package-data。新增独立`tools/audit_encoded_shor15_run.py`不导入项目量子模块，逐行SQLite核对全部native ID、串行依赖、每个M/RESET报告、模板签名、raw／frame／单次消费、shot cleanup成本，再独立执行完整CT／源矩阵及终端Born概率和阶／gcd。

### 实际完整运行

| 完整运行 | 本轮实际结果 | 门／投影／资源 | 参考生成wall |
|---|---|---|---|
| seed0，最终修复源码 | phase128未恢复阶→12patch真实读出RESET→phase64验证order4与3/5 | 11,243,634／2,402,810／7000，两shot | 222.731s |
| seed7，较早源码 | phase64成功，独立完整审计通过 | 5,951,556／1,269,619／3500 | 120.716s |
| seed8，较早源码 | phase64成功，未重复独立整流审计 | 6,704,145／1,445,781／3500 | 140.575s |

最终包为`artifacts/qec-shor15-2026-10-04/encoded-full12-native-seed0-fixed`，manifest SHA`16d12bb97b28d49c07b8a28d7a94ea81cf58d1c6fe7e3ee21f2a68fb350adac7`。首shot包含216cleanup门和216对应投影，fresh shot开始前12patch已释放。最终源码raw SHA：generator`e04e47657236fe189a48853994a18d2ad6fd62af302abf96eaf61f2d17fcfa34`、widecat`d506d0fece411bd666ae6df97976ef8d2e45bebde943af5c361d10b465fb4286`；其余指纹见公开摘要。seed7/8在别名／失败cleanup成本两项后续工程修复前已import源码，未捕获当时Python源码SHA；它们无失败shot，不能伪称使用最终源码重生成。最终seed0解决此来源边界。

### 独立验证与测试

| 检查 | 本轮结果 | 证据 |
|---|---|---|
| seed0完整流／复幅／真实终端分支 | PASS，80.924s；CT误差2.3734e-12／2.4040e-12，精确源3.5688e-5，Born误差<1.04e-12 | `full12-native-retry-independent-audit.json` |
| seed7完整流／复幅／真实终端分支 | PASS，43.900s；CT2.4032e-12，精确源3.5688e-5 | `full12-native-independent-audit-v2.json` |
| 一般12logical＋1ref／63cat三资源独立探针 | PASS，L2 2.46e-15，条件Born2.22e-16 | `new-generator-peer.json` |
| 源模幂／完整逆QFT独立检查 | 全4096输入通过；256维Fourier算子谱误差1.39e-13；全部28CP | 同peer摘要 |
| 六个同步篡改缓存反例 | 正常包通过，改非CP门／CP Rz轴／CP CX／外部相位／预算／wrapper相位均拒绝 | `full12-cache-negative-audit.json`，不另加pytest数 |
| 本轮不同pytest nodeids | **215＝65新＋150旧**，最终全部通过 | `full12-final-nodeids.txt`及下面组合证据 |
| architecture | 259modules（58env＋84strategy＋99experiment＋18app），0violations | 本轮运行`tools/check_architecture.py` |
| GUI | 8功能类别、actual stages／报告分页／frame／失败重试／390px通过 | `full12-browser/`原失败与最终截图 |

pytest选择：`test_qec_encoded_shor_native`10、`test_qec_wide_cat_reference`29、`test_qec_encoded_native_visuals`26、旧`test_qec_encoded_injection_reference`36、`test_qec_encoded_resource_reference`23、`test_qec_mixed_pauli_cat`35、`test_qec_conditional_clifford_frame`27、`test_qec_qft_synthesis`14、`test_qec_shor15_pbc_run`3和`test_environment_boundary`12，完整nodeids路径以公开摘要为准。最初旧回归114pass／1fail／1整个mixed-Y模块skip，是PYTHONPATH缺少隔离stim，不是量子语义失败；补入已有stim==1.15.0后失败项定向通过（最终留档2.20s），并将全部35个漏跑Y测试与65新测试联合100pass/11.91s。QFT14额外复验25.75s已包含于150旧测试，不重复计数。历史913与Factoring15旧58均不加入本轮215。

本轮Python3.12.14、NumPy2.5.3、pytest实际8.4.2、Stim1.15.0、pygridsynth1.2.0、mpmath1.3.0；requirements声明pytest9.1.1，但此轮复用原工作区已有隔离8.4.2，并明确未以9.1.1运行。没有修改Factoring15或ENV源码／物理默认。

### GUI实测与工程问题的修复

实际页面读最终seed0两shot同一包：CSS编码／canonical真实核／17RESET-H-T或7T-CSS-producer checks／cat GHZ两次相邻ZZ核验／XYZ-CY双T／cat H-M-RESET／资源9H-9M-9RESET／frame和释放／8项终端读出／216失败cleanup。frame下一轴跳转已同步左列表及shot／kind／injection／右侧function ID。32门/秒连续完成资源27门播放至真实末RESET；Home和ArrowRight定位native4158／4159，门表3798MEASURE显示actual bit0/P1及核来源；112条cat报告两页1–64和65–112往返。phase128失败显示CF1/2的模验证4，phase64显示CF1/4与order4／gcd3,5。最终console error为空。

390px最初375client／427scroll源于长SHA文本；修改维护HTML的foot／summary换行后375／375，原`narrow-390.jpg`和修复后`narrow-390-fixed.jpg`均保留。恢复默认viewport，最终`overview.jpg`为真实应用视口，tab已标记deliverable。早期浏览器play在tab隐藏时暂停属于已设计行为；最终同次调用等待27/27证明完整连续播放，未以早期10/27冒充通过。无FPS／物理运动验收。

首CLI在0.758s时因历史PBC wrapper三个合法额外相位／位序字段被严格dataclass拒绝；失败console保留，修复为先独立核对这些字段再剥离，其他未知字段仍拒绝。独立审查发现算法wire `resource`会别名共享资源角色，已在创建输出前拒绝并增加反例；失败cleanup实际门存在但shot统计漏计，已计入并验证shot求和等于整个native流。peer初次modexp探针使用不存在stage名导致选0门，改为真实`modexp`后4096例通过，此为审计探针错误而非产品修复。工程失败均保留，未改物理硬约束或放宽数学断言。

### 文档、RAG与发布

公开可移植[验收摘要](../../references/qec_pbc_validation/full_encoded_shor15_native_2026_10_04.json)保存三运行manifest／artifact bytes SHA、独立结果、全部215nodeids、最终源码与GUI截图指纹；GB原始流、SQLite和截图保持gitignored。生成、从新clone重建缓存、独立审计和本地服务器命令见[生成器](../../docs/qec_encoded_shor_native.md)。RAG在既有历史块上追加新能力与真实失败重试，保留旧快照日期／历史raw指纹；结构新鲜度、检索和换行可移植检查结果在发布收尾后记录。clean显式allowlist同步原workspace，原HEAD与并行工厂协议及其他dirty不覆盖。

GitHub沿用已授权draft [PR #3](https://github.com/physics-Yu/QEC-schedule/pull/3)，在`codex/d3-shor15-stages`上增加本能力checkpoint，Git-data connector创建tree／commit后独立fetch核对树及每个staged blob，再更新PR最终说明；不merge，不改变pushurl=DISABLED。发布回执在本日志追加节记录。

收尾发现原workspace并行协议任务已占用K55–K57／L34，与本批clean草稿编号冲突。合并保留政策三块和L34原文，原K54的supersession与L33当前normalized指纹及历史raw均保留；本批能力改为K58–K61、L35–L37。仅增量合入factory导航和原字节协议／其历史日志，不复制并行runtime改动。最终RAG为61chunks／49sources（12external＋37local）／110不同本地路径，53/53检索通过、freshness零错误。整份pyproject在两工作区含其他独立package-data差异，仅增量同步本viewer条目，不将其全文件hash当跨工作区current RAG源；发布快照的pyproject指纹仍在公开摘要保留。换行可移植验收与最终发布另见收尾回执。

## 未完成与下一项

收尾检查：最终61/49/110语料的11/11换行可移植检查通过（LF／CRLF／CR、真实字符修改、legacy raw、未知normalization、无效UTF8、路径逃逸）；新文档本地链接／代码块检查通过。显式26文件同步原workspace，并核对33个其他tracked dirty文件字节不变、原HEAD仍为9e28b2e；原factory三块及已有source raw指纹全部保留，原RAG freshness 0errors。

完整编码参考完成，`physical_executed=false`、`environment_committed_reports=false`、`magic_factory=false`、`fault_tolerant=false`，真实placement／peak／物理耗时／噪声质量为未知。本版只用裸T／7T和cat CY的TT，不称protected T。tracked ENV仍拒T，不能将reference reports写进物理键或关闭tracking绕过M／RESET。

按最新共享协议，下一项为F1：固定d=3及有来源15-to-1 native模板，完整参考生产与accept／reject／cleanup／补产；实际同一载态资源进入唯一库存并交付单T consumer，任意复幅／纠缠与所有正常分支独立核验完整T channel、符号与epoch，不重建理想魔态。之后F2 committed Executor闭环，F3逐周期噪声，F4 MSC backend，F5连续T和完整physical Shor。本独立完整算法参考可作为后续消费需求和对照。

## 发布回执

能力checkpoint已发布为[`dc2723d`](https://github.com/physics-Yu/QEC-schedule/commit/dc2723dfe4fc2d3ae5570f3341ad5537be65afcb)，parent`d7ef205`、tree`844683041d2882df9b4cb286dcfa1fb4cdb3ed2d`。Git-data远端tree与本地write-tree相等，fast-forward后独立`git fetch origin codex/d3-shor15-stages`，核对FETCH_HEAD、parent、tree、全部29个blob原字节及staged diff完全相同，再以旧HEAD条件更新clean本地ref；worktree干净。原workspace HEAD9e28b2e保持，33个其他tracked dirty指纹保持，pushurl=DISABLED未改。PR#3保持open／draft／unmerged；本回执文件是后续文档收尾提交，不重写能力checkpoint。

git staged whitespace检查发现observer Python第244空行尾空格，仅删除空白并同步其source／公开摘要指纹；无行为改动，不重复215项已通过测试。最终两工作区RAG freshness零错误。公开[发布回执](../../references/qec_pbc_validation/full_encoded_shor15_publication_2026_10_04.json)保存不可自引用的能力commit与完整核对结果。

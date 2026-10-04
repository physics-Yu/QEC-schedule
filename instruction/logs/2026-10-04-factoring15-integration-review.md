# 2026-10-04 · Factoring15对照与完整编码Shor集成路线

- 状态：COMPLETED（本轮只读审查/文档/RAG）；完整编码物理Shor仍PARTIAL。
- 用户目标：确认是否可以实现完整功能，查看Factoring15并确定可学习/复用内容。
- 基线：QEC阶段分支 `7301daf` / PR #3；原workspace HEAD保持 `9e28b2e`。Factoring15入口HEAD `580a7e1`，G1.1由另一活动任务继续修改。
- 指令：先读agent/handoff，按architecture/compiler_contract/workflow路由；Factoring15按AGENTS读state/decisions/g1-contract/最近验收并先运行Graphify定向query。

## 审查结论与改动

新增[对照说明](../../docs/qec_factoring15_integration_review.md)及[来源/运行/测试摘要](../../references/qec_pbc_validation/factoring15_review_2026_10_04.json)，RAG新增K52–K54/L33/三检索问法，handoff只添加本轮短摘要；没有修改两项目生产代码、门集、物理参数、平台或量子状态架构。

Factoring15已冻结G1可学习15-to-1、拒收补产、15 raw唯一来源、固定载体/库存、A−→T†和统一trace/demo。其physical measurement仍not_simulated/null，分支由ideal reference预选；旧串行平台只pass_reduced_model。G1.1并行RM16正在修改，不能复用旧包验收为新能力背书。

修正过宽的T能力表述：普通原生T物理排程已支持；实际限制是tracked T与MEASURE/RESET不能同时运行。现encoded consumer只接受单A，宽cat全raw资格限16，exhaustive logical/ref审计限6；完整12wire需要新分解语义与native generator。静态确定分支线路、预声明有限Clifford cat accept/abort无需先修改live DAG。

下一交付A/B/C：12wire完整native分支线路＋4096逻辑态/qualified kernels/顺序wide-cat采样；真实committed cat资源控制小闭环，再接明确非Clifford/Born/工厂合同；最后全12算法patch有限平台排程、actual Executor/replay与统一demo。代码变更或架构实施不是本轮审计范围。

## 本轮验证

| 检查 | 结果与范围 |
| --- | --- |
| Factoring旧G1 quantum/runtime/platform/artifacts四独立命令 | 15＋17＋18＋8＝58不同测试通过，0failure/0error；分别0.410/0.231/7.572/1.511s；只验证旧G1回归接口，不加入QEC历史913 |
| 三冻结final-03运行包 | 独立stream核对manifest的21artifact SHA全部匹配；ideal/retry/exhausted事件29997/53871/52364，物理readout仍null |
| RAG结构/来源 | 54chunks、45sources，0errors |
| RAG检索 | 39/39通过；新三问分别召回K52/K53/K54 |
| RAG可移植性 | 11/11通过；33本地sources、95不同路径，LF/CRLF/CR与坏hash/路径/编码反例均通过 |
| QEC源码独立peer | 无阻断：T范围、1patch/16cat/6logical限制、reference vs committed、静态abort方案及A/B/C范围正确 |
| 文档/发布范围 | git diff --check通过；仅本轮7文档/证据/语料路径，未包含Factoring活跃文件或原workspace其他dirty |

测试入口：在Factoring15使用 `.venv/Scripts/python.exe -B -m unittest discover -s tests -p test_quantum.py -v`，依次替换为test_runtime/test_platform/test_artifacts。RAG使用 `python tools/query_qec_pbc_rag.py --check` / `--self-test`。可移植性工具沿用本机ignored `tmp/stage11_rag_portability.py factoring15-review`，报告在clean `artifacts/shor15-publication-validation/portability-factoring15-review.json`。

## 证据边界与出版

Factoring15顺序观察指纹不是原子快照或测试启动源码捕获；新quantum/runtime与冻结G1 manifest不一致。peer早期G1.1字段检查曾有KeyError，之后源/test又改变；只保留当时两hash与观察，不作为当前永久缺陷或里程碑失败。旧G1四套测试的成功不替代新并行工厂验收。

本轮没有新QEC物理运行、全204+原子dense、完整编码physical Shor、含噪FT或浏览器验收。发布沿用用户已授权的 `codex/d3-shor15-stages` / [PR #3](https://github.com/physics-Yu/QEC-schedule/pull/3)，本提交只记录审查/新RAG；具体SHA可由该分支Git记录复核。原Factoring项目未由本任务写入，原QEC HEAD和硬件配置保持。

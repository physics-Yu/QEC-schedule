# 2026-09-11 · EZ 四邻格硬性预留

状态：COMPLETED。

用户要求：为装入 EZ SLM、准备做 2Q 的原子保留四个最近邻格点，无关原子不允许挪来占据。澄清后明确允许穿过，仅禁止占据；不扩展为整片 5 μm 禁区，不取消现有 sweep/SLM 避碰。

已加入 `hardware/ez_neighbors.py` 派生唯一下一次未完成 CZ 的伙伴，四个点使用 world pitch；共享状态构造、backend MOVE 终点、交接/运行态强制校验。adaptive EZ 候选优先局部合法站点，工作台文本明确无开关选项。

已修正纯预测 CZ 后的 DAG 更新及 serial/legacy origin 恢复，防止 pulse 后的伙伴更换/解除与真实 Executor 不一致。`predict_cz_completion` 只变更私有预测DAG，真实effect仍由Executor完成；M3已有的手动推进只保留1Q以避免CZ重复推进。legacy routing/parking的pulse预测同步；有initial_dag的plan从它恢复，无initial_dag的legacy从已完成前驱恢复逻辑起点。

前期未含最终 DAG 修正的检查：M4/policies/multi 49 passed /141.34秒；A*与运行前缀缓存30 passed /1.70秒。不能作为最后版本全部验收。

规则合同见 [EZ 四邻格](../../docs/ez_neighbor_reservation.md)。schema17结构保持，旧违反新硬规则的轨迹需重编译。

## 本轮已验证

- `tests/test_ez_neighbors.py`：38 passed /0.50秒。自建几何夹具，覆盖四点SLM/AOD、唯一当前伙伴、所有中心独立、blocked下一CZ、未来伙伴不豁免、保护生效/解除、两后端允许长MOVE经过但终点拒绝、多cell附带原子、空trap/缺trap名称、pitch/tolerance、交接预检失败原子性、热cache与checkpoint。
- `tests/test_cz_prediction.py`：4 passed /52.88秒。旧伙伴后处理拒绝、新伙伴允许、最后CZ释放后无关原子可停车、重复预测CZ拒绝；每个serial事件边界恢复与最终状态一致。
- 最终DAG修正后 `pytest tests/test_m4.py tests/test_m4_policies.py tests/test_multi_trap.py tests/test_astar_routes.py tests/test_runtime_prefix_cache.py tests/test_workbench_m4_policies.py -q`：**95 passed /228.09秒**。
- 原f902输入从头编译：greedy 12/12、完整终态3824.5μs（17.366秒，本轮同时有回归负载）；lookahead 12/12、完整终态3787.5μs（83.226秒，同负载条件）。新硬规则与候选排序可改变线路物理路线/成本，不沿用上轮55.967/13.334秒的性能结论。
- 两份 `artifacts/m4-ez-neighbors/{greedy,lookahead}` 分别经 `examples/verify_m3.py` 独立 verified：greedy156ops/7plans，lookahead152ops/8plans，均7atoms/12effects。`node tests/viewer_speeds.cjs artifacts/m4-ez-neighbors/lookahead/index.html`：0.25–32×双时间映射通过。
- 原8768服务/用户草稿未重启或改写，HTTP200且已提供新硬规则说明。浏览器自动化入口再次因nodeRepl.fetch连接失败，未声称真实鼠标/画面验收；本轮UI只增加说明文字，物理规则在worker后端执行。

legacy旧unintended初始夹具本身违背新规则（EZ中心5,-25与无关原子10,-25为相邻格）。已将其incident源移至10,0、无关静态目标15,-25，保留最终13/15的额外2μm作用对负例，同时使初态合法；不改硬约束来保旧坐标。

- Task IR、rigid parking、motion planner 的52项通过（初轮在随后的M1旧夹具停止，已修复并补跑）。
- 最终 `pytest tests/test_milestone1.py tests/test_milestone2.py tests/test_m3.py -q`：**76 passed /360.58秒**，覆盖夹具修复和M3逐事件恢复。本轮没有重跑全部旧460项，不借用历史全量PASS。
- 本轮规则/预测/适用回归均收尾，无遗留测试失败；文档本地链接检查通过，未创建Git提交或发布。

## 保留边界

规则是精确离散停车点约束，允许经过不意味着可撞原子或穿开启SLM势阱；CZ仍只支持现有模型，不模拟串扰概率。M4站点/开关候选和前瞻仍有界，新规则下任意线路成功率及90秒内完成不作保证；本轮并发测试负载下f902前瞻83.226秒不构成实时性能承诺。后续若继续性能优化，应使用含本规则的输入与模型重新基准测试。

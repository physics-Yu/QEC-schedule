# 2026-09-10 · 单 trap 可替换电路编译管线

- 状态：COMPLETED（本轮范围；非完整通用 M3）
- 用户授权：单活动 AOD trap 先搬 a 到 EZ SLM，再搬 b 做 CZ，随后 b/a 逐颗返回 SZ；抽象可替换编译策略，独立电路/平台/布局输入。
- 范围：M3 所需的动态 placement 程序接口与用户指定串行返回策略，不冒充通用跨门 KEEP allocator 或 M4 优化。
- 保留现有 rigid/row_column、严格 trap 间距、路线注入与联合停车行为。硬件能力与编译策略分离，单 trap 不需要 selective_transfer_enabled。
- 新通用计划保存 initial_placement，LOAD/OFFLOAD 使用逐操作 bindings，checkpoint schema 9 拒绝旧版本。独立程序校验不要求固定装卸次数或运输顺序。


## 完成内容

- `motion/program.py`：通用不可变计划构建和独立逐操作审核，始末 placement 分离，支持不同装卸次数和操作目标；不信任 strategy/planner 名称。
- `motion/single_trap.py`：单活动 AOD cell 编译策略，两个 anchor 顺序与真实 EZ trap 候选，复用可替换路线 planner。完整空载/loaded/交接/CZ/返回计时。
- `simulation/pipeline.py`、`planning/compilers.py`：外部输入边界、编译协议与策略注入；CLI `examples/compile_circuit.py` 接受电路/平台/布局，不导入特定场景 factory。
- domain、checkpoint、runtime 与 executor：schema 9 保存初始 placement，LOAD/OFFLOAD 按每次 bindings 执行；实际装载计数与指标采用当次集合。rigid offload 补上静止与实际 cell 的硬检查。
- recorder 与共享 viewer：正确装卸当前一颗原子、保持 EZ anchor 静止、共享 schedule；去程说明不再承诺所有策略都沿原路返回。
- 默认三份输入位于 configs/circuits/single_trap.json、configs/platforms/single_trap.json、configs/placements/eight_atoms.json。详细契约见 [文档](../../docs/circuit_pipeline.md)。

## 验证

| 命令/检查 | 本轮结果 |
| --- | --- |
| `python -m pytest -q` | 最终完整运行 202 passed, 1 warning，172.99 秒 |
| `python -m pytest tests/test_single_trap_pipeline.py -q -x` | 首批 15 passed；随后补充外部平台与未知 Q 用例，最终完整运行包含全部 17 项 |
| `python examples/compile_circuit.py` | 八原子十二 CZ completed，336 operations、696 commits，全部原子恢复输入位置 |
| `python examples/run_single_gate.py` | 五个 M1 场景 PASS |
| `python examples/run_circuit.py` | 五个 M2 场景 PASS |
| `python examples/run_reconfigurable_aod.py --backend row_column` | 三个合法场景 PASS，外列压缩按严格间距拒绝 |
| `python examples/run_motion_planner.py` | 相邻列、16 原子右/左路线三场景 PASS |
| `python examples/visualize_circuit.py --scenario three_gate` | completed，81 compact frames |
| `node tests/single_trap_controls.cjs` | 十二个真实 pulse、一个活动 trap、逐次交接、静态 anchor、全返回、数据不变 PASS |
| parking_controls / replay_controls / replay_row_column / viewer_component / schedule_controls / motion_controls | 六组既有 Node 控制回归全部 PASS，使用当前共享 JS；旧 recording 可直接重导出 viewer，无需修改物理数据 |

测试新增：逐边界 checkpoint 解码、代表性边界续跑最终完全一致；三门不同伙伴输入、反转 anchor 选项；不同 Q/trap ID、三原子、平移 world/grid origin 与另一 EZ 站点；非法 cell/绑定/阶段/时长/资源/初末位置拒绝且实时状态不变；KEEP_LOADED 非回归计划执行/恢复；未知 Q、无停车点、非 CZ、非单 trap 诊断。

开发中首次全量测试发现新增测试代码的一段恢复断言误放在另一个函数中（NameError）；调整测试位置后重新运行完整测试得到上述 202 PASS。未用第一次 201 PASS 的部分结果冒充最终验收。

静态查看 artifacts/single-trap/pulse.png：Q000 为 (5,-35) 的 SLM 原子，Q001 为 (3,-35) 的 AOD 原子，其余六颗留在 SZ，只有一个橙色 AOD trap 圆环。本轮未做真实浏览器视觉验收；前序本地 URL 自动访问安全限制未绕过。Node 是 DOM/Canvas doubles，512 原子合成控件检查不是物理规模或浏览器 FPS 测试。

## 数字与物理假设

单门 a 去/回 40/45 μm，b 去/回各 48 μm；两段空载各 sqrt(1250) μm，总原子路程 181 μm、AOD 251.71067811865476 μm，总周期 1103.7213562373095 μs。默认十二门 wall 18026.915473838395 μs，逻辑完成 17163.26724323606 μs，AOD/atom 5411.657736919199/3502 μm，装卸各 36，附带运输 0。

单 trap 仅用完整 load/offload，不默认启用理想选择性交接。SLM/AOD holder 是事实，移动和卸载不能凭空改变另一颗原子。速度、交接时间、光场简化与既有模型一致，未标定参数和空 trap 光场未被冒充实验结果。

## 未完成与下一步

本轮单 trap 每门返回；原 M3 的通用 loaded 起点候选、无 gate transport/cleanup、RETURN_ONLY/REPOSITION_AND_KEEP 与跨门 offload allocator 未完成。KEEP 终态的执行/恢复通过不代表默认策略能自动从任意驻留状态继续。仅支持 CZ 与有限 route/site 候选，不保证任意电路门集或任意布局成功。

下一项可执行任务：在既有 GateCompiler/Program 边界增加独立 transport/cleanup intent，支持 loaded 起点，验证 KEEP 后继续与显式退出；随后比较跨门策略。所有历史日志和已完成的严格间距/路线/联合停车工作保留。

补充 CLI 负例：用相同平台/布局输入 H 门，build 返回 stalled/UNSUPPORTED_GATE，committed_events=0；生成真实失败诊断与报告，没有预搬原子。产物在 artifacts/single-trap-negative/。

# 2026-09-21 · 分层编译器与 QMAP 的耗时差距

- 状态：COMPLETED（分析与测量）；未修改生产算法、环境或工作台。
- 用户问题：为什么当前编译比论文慢很多。
- 依据：论文 arXiv:2512.13790v1 Table 1 / §4–5；固定 QMAP 源码 `e2988b773a36665fd6e5a5e1228fc1df7c4e1ef1`；当前本地源码及新计时。

## 当前 16 原子案例的实际热点

使用 `configs/workbench/zoned_repeated16.json`、`zoned_ids`，4 层 32 CZ，所有物理校验开启。轻量函数边界计时：32/32 完成，物理时间 1658.670413 μs，与既有交付一致。单次墙钟 11.7261 s，工作台返回 compile_seconds=11.6858 s；单次运行有系统波动，不能与先前 7.55/10.81 s 当作受控回归比较。

| 阶段 | 秒 | 墙钟占比 |
|---|---:|---:|
| IDS 落点搜索（4 次顶层调用） | 8.8955 | 75.9% |
| 物理展开 | 0.1341 | 1.1% |
| ProgramBuilder.finish 审计 | 0.4997 | 4.3% |
| Env.submit | 0.2163 | 1.8% |
| Env.run（含录制） | 1.6310 | 13.9% |
| 其他初始化、结果整理等 | 0.3495 | 3.0% |

录制 observe 为上述 run 的子项，0.0716 s，不能重复加总；最终 recording_payload 位于其他开销中。该测量在 Python 后端进行，没有浏览器渲染。工作台 compile_seconds 在 recording_payload 之前取值，不含最终 HTML/文件写出、传输和浏览器绘制；但包含逐事件录制与环境执行。

另一个 cProfile 样本的 compile_input 累积耗时 26.05 s；探针显著增加开销，只用于函数热点/调用次数，不将其当正常编译速度。共约 2821 万次 Python 函数调用，`placement.options` 137 次、`validate_ez_neighbors` 19729 次、`build_batch` 22773 次、`PlacementView.__getattr__` 约 368 万次。

具体源码原因：`project_destinations` 检查一次 EZ 保护，`options` 对同一假设再次检查，`cost` 再建同一前缀的几何假设并检查；每个候选从头重算前缀兼容组，`build_batch` 构建轴、支撑和作用对。保护检查还会重复推导 next_cz 和占据/保留点。部分状态虽不再使用完整 SimulationState，但其计算仍未成为增量数据结构。

测量产物：`artifacts/zoned-compiler/runtime-analysis/{summary.json,repeated16.pstats,profile.txt}`。第一次 cProfile 在保存 profile 后的摘要阶段误把 compile_input 返回的 SimulationState 当 Env，发生 AttributeError；profile 已成功保存。随后独立轻量计时使用正确返回类型完成，不能把第一次摘要异常隐瞒成正常完成的报告。

## 论文与当前实现的差异

1. QMAP 的 Compiler.hpp 以 schedulingStart→codeGenerationEnd 计 totalTime，`assert(code.validate().first)` 在时间终点之后。benchmark 的 Qiskit 预处理、后续 evaluator/NAViz 写出不在该计时内。本地 compile_input 则运行完整环境和录制。独立重放在本地比较脚本中另外计时，不包含于前轮公布的 compile_seconds，不能再扣一次。
2. 作者 C++ placement 的 child 保留并更新 compatibility groups/max distances，用有序轴映射和增量兼容检查估分；本地 cost 对每个候选重复构造整个前缀。IDS 队列形状相似，不等于单节点成本相似。
3. 作者具有逐行/列拾取、错位、分时卸载的 relaxed routing；本地尚为有限路径尝试和不兼容批次拆分。QEC 从 17→81 CZ 脉冲的退化会连带增大实际事件/审计成本。
4. 本地 finish、submit、runtime 多次独立审计；runtime 仍扫描历史 trace。已有 `_expected_prefix` 缓存，并非每个事件都从零重放整个前缀，但全历史读取、计划比对和跨边界重复审计尚未充分摊销。其在本例不是最大热点；较长 QEC 的比例不能直接套用本例。
5. 论文不是所有千比特线路均数秒：Table 1 的 1000-qubit QFT 为 6.2 s、每层最多 10 CZ；1000-qubit graphstate 为 57.6 s、每层最多 306 CZ；5000-qubit graphstate 为 647.7 s。作者 benchmark 脚本去除 measure/barrier，不能等同本地完整测量/复位/条件 QEC。作者数据未在本机复现。

## 后续建议（尚未实施）

先消除 search 内重复全量检查：每层预计算 next-partner、位置、保留点和几何索引；子节点只更新新增原子及受影响邻居；兼容组/最大位移增量维护，必要时与完整检查交叉验证。然后接入已验证的成组装卸宏动作，减少路径试错。最后拆分并摊销执行审计：不可变计划、完整依赖指纹、版本绑定及恢复时验证保留，实时推进采用可证明等价的增量检查。不能简单关闭碰撞/支撑/EZ 规则；也不能用更换语言代替减少重复工作。

上轮完成的是模块边界与第一版行为接入，尚未完成论文性能关键点的实现。这次数据明确否定“主要是 HTML 或动画导致慢”，也不支持仅用额外物理校验解释全部差距。

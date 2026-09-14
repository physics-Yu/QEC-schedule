# 单脉冲并行 CZ 底座

`ENTANGLING_PULSE` 可显式声明 `Operation.gate_ids`。一次操作只有一个开始事件、一个完成事件、一段硬件配置的 CZ 时间；所有门在同一开始事件进入 RUNNING，在同一完成事件原子化进入 COMPLETED。它不是把多个单门操作的时间标签改成相同。

```python
intent = TaskIntent("batch-service", TaskTarget(), phase="program",
                    gate_effects=frozenset(batch_ids))
p = ProgramBuilder(state, intent)
# 可在此之前加入真实装载和联合移动。
p.add(OperationType.ENTANGLING_PULSE, "Parallel CZ", gate_ids=tuple(batch_ids))
# 可在此之后加入真实移动、归还及显式终态。
plan = p.finish("batch-service-v1")
Executor(state).submit(plan)
```

builder 的纯预测完成全部 CZ 后才构造后处理，所以后续四邻格保护按新的下一 CZ 伙伴计算。`phase="program"` 的 finish 返回经过独立时间、资源、几何和终态审计的 scheduled plan。新二维调度器可以直接提交它；不需要包成多个单 CZ。

## 硬校验

- `gate_ids` 非空、唯一、已知、全部 CZ，任意两个门不共享 qubit。所有门必须同时 READY，重复完成、blocked 或混合执行阶段不能通过。
- 单台 AOD 静止且支撑稳定，保留后端原有位姿、全容量、碰撞及四邻格规则。
- backend 扫描整个 EZ 中所有存活原子的实际作用对，要求集合**严格等于**整批预期对。遗漏预期作用对或多出旁观作用对都会失败，不按门分别局部通过。
- 每个声明门必须恰好有一次效果，独立审计展开所有操作的效果列表检查遗漏与重复。失败不会部分提交 live state 或部分完成一批门。
- 激光与 AOD 忙时按一个 pulse 计，不乘并行门数。门完成数按每个逻辑门计；一次 batch 不代表一个逻辑门。

单门 `gate_id` 保持原 API；不能在同一操作同时设置 `gate_id` 和批量 `gate_ids`。batch 字段仅允许用于 CZ，不允许把异类型单比特门装进 CZ batch。

## 记录、恢复与显示

batch 的单条效果完成 trace 包含 `gate_ids` 和 `effect_gate_ids`，单值 `gate_id` 为 null；不得同时再生成重复的逐门效果事件。`examples/verify_m3.py` 展开批量效果逐门核验 exactly once。

记录器给一个 pulse 记录 `batch_size`、`gate_ids`、`intended_pairs` 和全部 `qubit_ids`。共用 viewer 在同一时间画出所有作用对、显示实际并行门数，原子详情显示该原子的唯一当前作用伙伴。checkpoint 升为 **schema 18**；schema 17 需从输入重新编译，避免旧解析器静默丢掉新的批量效果语义。

## 验证范围

`tests/test_batch_cz.py` 覆盖 rigid 与 row_column 的 1/2/18 门真实单脉冲、二维 2×2 阵列上下 2 μm 作用、所有效果一次完成、中间状态恢复、后处理保护释放，以及共享 qubit、非 CZ、blocked、重复、额外作用对、缺失作用对和损坏计划拒绝。旧单门、M3、row 与运行期恢复回归另行执行。

`tests/batch_cz_controls.cjs` 对生成的 18 门 pulse 录制验证一个操作、36 个同时 gating 原子、36 个脉冲圆弧、终态及时间映射。这是离线 DOM/canvas 测试，真实浏览器验收由二维实验交付单独记录。

这是并行 CZ 的物理执行底座，不代表已经解决任意二维布置的最大批匹配、最优交换、任意电路全局调度、真实设备方向标定或完整 M5。

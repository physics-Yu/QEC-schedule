# 步骤 6：AOD TRANSLATE compatibility 与 movement epochs

## 实现范围

MovementPlanner 与未来 scheduler 分离。它消费**已 ready 的 MoveRequest**，
输出可一起执行 pickup / translate / dropoff 的 AODMovementEpoch 候选。
本步骤不分配开始时间、不推进实验时间、不运行资源锁。

默认仍使用已确认的线性区域布局：Memory、Entanglement、Measurement 自上向下，
Reservoir 在 Memory 右侧。

## AODController

硬件 YAML 新增可选 `aod` 段：

```yaml
aod:
  max_x_tones: 20
  max_y_tones: 20
  allowed_region: [0, 0, 100, 99]
  allowed_primitives: [TRANSLATE]
  displacement_tolerance: 1.0e-9
```

只支持 TRANSLATE。其他 primitive 明确报错；后续再实现 STRETCH/COMPRESS。
旧配置未提供 aod 时使用 20/20 tones，可达范围取所有 zone 的外接矩形。

`Translation` 包含 atom、source Position 和 target Position。
`AODController.compatible(translations)` 判断兼容性；
`incompatibility()` 返回不兼容原因，方便后续记录 blocked 原因。

同批必须满足：

1. atom 不重复，source/target 位置无重复。
2. 每个 atom 的 source、target 位于 allowed_region 闭区间内。
3. 所有位移向量 Δr 两两相等，使用绝对容差 1e-9 um，`rel_tol=0`。
4. x/y tone 预算足够。

tone 数按 source/target 两端不同 x、y 坐标数的较大值计算。
坐标去重使用精确数值，是保守的计数方式。
例如 3×3 阵列有 9 个 atoms，但只需要 3 个 x tones 与 3 个 y tones；
因此没有 `max_atom_capacity` 参数，也不将 tone 上限解释为 atom 上限。

位移采用两两比较，避免容差串联：A≈B、B≈C 不代表 A≈C。
重复坐标、zero-distance translation、非法 tone 数、越出 allowed_region 均不能合并。
可达范围是凸矩形，直线平移端点在内部即可满足区域限制；
这不等于完成了避障、与其他原子的连续碰撞检测或 crossed-AOD line-order 校验。

## 从 ExperimentalPlan 提取 MoveRequest

每个 MoveRequest 包装步骤 5 的三个原始 actions：

```text
PICKUP → MOVE → DROPOFF
```

校验同 atom、同 gate、相同 transport_id、精确的三阶段依赖和连续端点，
并要求 transport 的 AOD/atom custody reservation 覆盖整个 pickup→dropoff。
不丢弃原始 action ID，所以 physical gate_completion 和原有依赖仍然有效。

```python
from qec_schedule.lowering import TransportCatalog, MovementPlanner

catalog = TransportCatalog(experimental_plan)
planner = MovementPlanner(config.aod)
epochs = planner.plan_ready(catalog, completed_actions=set(), in_flight=set())
```

`TransportCatalog.ready_requests()` 只返回入口依赖已完成、未开始的 transports。
completed 集合必须遵守完整 action DAG；仅设置某个 MOVE/DROPOFF 完成而跳过它的
predecessors 会报错。已经完成部分 phase 的 transport 必须标记为 in_flight，
防止重复安排；全链完成后不再返回。

下游完成一个 epoch 时，应按三个 phase 正确报告原 action IDs 的完成：
所有 pickup 完成后执行 move，所有 move 完成后执行 dropoff；
不能在 epoch 启动时就把全部 action 标为完成。

也可以直接调用 `planner.plan(requests, completed_actions=...)`，但必须传入 ready 请求。
未满足依赖、重复 atom/transport/action IDs，或包含已完成部分的 transport 会被拒绝。

## 分组规则

采用确定性的 first-fit：按照输入顺序，将请求加入第一个兼容批次，否则建立新批次。
顺序不是 RESST priority，分组也不宣称最优。

除几何兼容外，三个 phase 的请求时长也须相等。仅允许相对误差 1e-12 以内的浮点差异，
取各 phase 最大值作为同步时长。明显不同的速度或 pickup/dropoff 耗时会拆批。

epoch duration = pickup duration + move duration + dropoff duration，
不是把同批各 atom 的 duration 相加。start_time 始终为 None。

## 保留依赖与资源生命周期

epoch 的 dependencies 是成员入口依赖的并集；成员之间存在先后依赖时不能合并。
每个 epoch 保存 phase_action_ids、request_ids、逐 atom 的起止位置、位移与 tone counts。

其 custody reservation 使用：

- 一份 `device/aod`，units=1；
- 每个成员一份 `atom_lock/<atom_id>`；
- acquire_before 为所有 pickup，release_after 为所有 dropoff。

输出 `replaces_reservation_ids` 明确列出被合并替换的原 transport leases。
后续 scheduler 应使用合并后的 custody，不能再额外扣减这些旧 transport leases。

pair/site/measurement/zone 的原始 reservations **保留**。
`additional_reservation_ids` 指明 epoch 入口涉及哪些其他预留；相同 ID 只申请一次。
它们仍按原始 acquire/release action IDs 定义生命周期，不能在搬运结束后提前释放。

这一步只保证 AOD 几何与依赖兼容。epoch 候选可能因其他场地占用、zone 容量或
资源冲突无法整体启动。后续 scheduler 必须检查全部 reservation，必要时选择更小的
ready 子集重新调用 planner。MovementPlanner 不把这些候选直接当作最终执行批次。

## 运行验收

```powershell
.\.venv\Scripts\python.exe examples/demo_aod_movement.py
.\.venv\Scripts\python.exe examples/demo_aod_movement.py --rounds 3 --output-dir results/aod_three_rounds
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

默认输出 `results/aod_epochs.json`。

独立的 10-atom 验收例：source x=5,7,...,23，y=5；全部移动到 y=15，Δr=(0,10)。
这些是用于验证控制器的合成坐标，不是默认硬件阵列上已有的 10 个 atom。
默认配置应输出：

```text
Acceptance: 10 equal-displacement atoms -> 1 epoch(s)
atoms=10, tones={'x': 10, 'y': 1}, duration=12 us, AOD units=1
```

附带对真实 d=3 单轮的**依赖集合检查**：
112 条 transport、25 次 ready 集合迭代、104 个 AOD 候选 epochs。
检查器每次符号性完成当前 ready 工作，再查看后续请求，仅用于确认全链覆盖和分组。
它不考虑 zone/laser 竞争，也不使用事件时间，因此 **104 不能当作最终调度后的 epoch 数**，
这些迭代也不是固定 circuit layers。

JSON 保留 original_reservations，并标记 `scheduled=false`。
GitHub Actions 在 Python 3.10/3.12 运行示例，上传单轮和三轮输出作为 artifact。

新增 10 项测试，累计 47 项：

- 10 atoms 合批，AOD 只扣一份，保留所有 atom 锁；
- 不同向量、相反方向、耗时不同不误合并；
- x/y tone 分拆，以及 3×3 阵列的 3/3 tones；
- allowed-region、浮点容差及非传递近似；
- 依赖、重复/partial/in-flight 请求；
- 完整 syndrome 的全 action 覆盖、确定性及原 reservations 不变；
- 配置与 transport chain 输入校验。

步骤 6 完成后，下一步为步骤 7：RESST Task、Pool、Priority、ResourceLock 和 TaskState。

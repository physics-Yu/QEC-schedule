# QEC 刚性 AOD 标准路由

2026-10-04 用户要求：原子移动优先采用最短合法路径；遇到障碍时沿既有 2.5 μm 偏移协议运输。该规则已接入码块并行编译器，策略标识为 `shortest-direct-or-halfgrid-v1`，CLI 使用 `--routing-policy standard`，也是该入口的默认值。实际执行与独立审计结果由对应运行报告给出；本文规定算法和后续实施路径，不以历史 5 μm 路线的成功证明新路线已经通过。

## 路由标准与最短性的范围

一次请求固定当前 holder、SLM/AOD masks、完整刚性行列偏移、设备身份和目标构型。先由物理 backend 校验起终点及整条直线：若通过，采用一条实际 MOVE，达到两端之间的 Euclidean 距离下界。直线可为对角方向，所有携带原子与活动空交点都要通过连续扫掠检查。

直线不合法时，复用 `AStarHalfGridPlanner` 搜索有限半格通道图：

```text
长段：x = 2.5 + 5k μm 或 y = 2.5 + 5k μm，k 为整数
接入：起终点到邻近通道的短正交段，每段不超过 2.5 μm
目标：固定构型和支持状态下，该图内的最短运输距离
```

长段沿通道水平或垂直运输；只有首末短接入连接非通道端点。对本平台的 5 μm SLM 格点，这是半格偏移，不是将原子整体强制偏移 2.5 μm、将 CZ 间距设为 2.5 μm，或改变碰撞排斥半径。`ordered_routes.py` 的 `2.5 + 2.5k` 有序行列有限候选属于另一种路线族，不能与这个 rigid A* 合同混用。

| 返回字段 | 解释 |
| --- | --- |
| `points`、`distance_um` | 实际准备生成 MOVE 的阵列原点路线与总长度；不是所有原子的路程之和 |
| `optimality_scope=euclidean-direct` | 直线通过完整 backend 校验，达到两端距离下界 |
| `optimality_scope=halfgrid-distance` | 路线在声明的有限半格图内距离最短 |
| `graph_result` | 图搜索距离、几何下界、展开数、物理边检查数等；直达时为 null |

图内最短不表示连续空间任意绕障路径最短，也不优化 placement、捕获 masks、装卸安排或整个线路调度。恒速 rigid 模型下距离与运输时间成正比；Enola 等非线性逐段起停计时必须重新累计 backend 时长，不能由距离最短推出时间最短。默认展开预算为 20,000；`GRAPH_ROUTE_BUDGET_EXHAUSTED` 与 `GRAPH_ROUTE_NO_PATH` 分开记录，均不表示连续空间物理无解。

## 设备、支撑与物理检查

共享入口位于 `src/neutral_atom_strategies/motion/validated_rigid.py`：`shortest_rigid_route()` 只读搜索并返回路线，`append_rigid_route()` 将成功路线逐段写入私有 ProgramBuilder，再由普通计划校验和 Executor 实际提交。

每条边使用 `backend_for(state, aod_id)`，通过 `with_aod()` 更新对应设备的候选构型。`AOD_0`、`AOD_MAGIC` 的身份、registry 和 holder 不混用。`RouteRequest.routing_bounds` 只限制搜索范围：已配置合法设备 envelope 时使用该范围，未配置时使用完整 world；非法 envelope 必须拒绝。边界扣除全部行列跨度，关闭的备用轴也不能超界。全 world 的 trap、原子和另一设备始终保留在物理障碍检查中，不能裁掉域外旁观原子来制造自由通道。

所有候选保持以下要求：

- 捕获集合等于实际受影响闭包；活动交点为启用行与列的完整 Cartesian 积，包含空交点。
- 全段校验载原子、旁观原子、活动空 AOD trap、开启的 SLM，以及轴序、间距、世界边界和设备 envelope。
- LOAD 后第一条 MOVE 的 `depart` 只绑定实际源 SLM；OFFLOAD 前最后一条 MOVE 的 `approach` 只绑定实际目的 SLM。一个 MOVE 不合并两个交接豁免；需要时保留已清离源支撑的中间停点。
- 关闭空 AOD 后的定位仍生成实际计时 MOVE；路由器不私自修改光阱开关、holder、live DAG 或测量报告。
- CZ 后和 MZ 读出/reset 后，归还路线根据 ProgramBuilder 的实际预测状态重新搜索，再实际 OFFLOAD；不强制沿去程逆序归还。

该修改保持有限 **6 μm CZ**、脉冲时全部实际作用对等于声明作用对、非伙伴原子至少 **10 μm**，以及运输的连续 **1 μm** clearance。Raman 仍要求目标与其他存活原子至少 5 μm，MEASURE/RESET 仍在真实 MZ 执行。不能通过扩大 CZ 到 10 μm 来代替运输或解决密集码块中心的配对障碍。

## 实施顺序：单块、复制与工厂

1. 固定 canonical d=3 协议、角色和源 native ID，在同一单块初态上以新标准重新编译。逐项检查 LOAD、直达/半格运输、CZ、读出/reset、归还与终态；保留原初态、计划、trace 和失败证据。
2. 单块方案通过后，将相同 placement 按声明 pitch 复制到多块。相同 READY 操作只有在 rigid 位移一致、Cartesian 捕获闭包完整、全部旁观作用对合格时才合批。单块路径不能直接当作多块路径证明，完整容量、空交点和其他码块仍需重新检查。
3. 工厂跨块 CX/cat、库存运输和 processor injection 复用同一设备感知路由 API。上层先选择真实交互位/暂存 SLM、目标构型和合法交接任务，路由层只解决这些端点之间的运输。保持原协议依赖；CX 的前后 H 在伙伴距离至少 5 μm时执行，不能在 3 μm CZ 接近构型中发 Raman。
4. 若固定旁观辅助位导致 CZ 端点本身不合法，先设计预声明的 interaction staging 或实际辅助位搬移/归还，再为每一段调用标准路由。若两设备 envelope 间距超过 6 μm，须提供实际可接近的边界交互位或受支持的运输路径；token 交付不能代替原子移动。
5. 工厂、库存和 consumer 在同一时钟与共享资源上组装，经完整物理执行、原初态 replay 和独立审计后进入共用 viewer。跨设备并发路径另按实际共同时间区间验收；本局部路由接口本身不证明并发全局最优。

后续 S1–S3 使用[共享工厂协议 v2](../instruction/qec_factory_pipeline.md#当前任务目标纯调度模拟)。复用的是 `validated_rigid.py` 的两项路由 API；当前 `run_parallel_patch` 仍是显式 Clifford 前缀验收 runner，不能直接充当工厂运行时。报告源在合法读出完成后提交；量子参考和质量研究独立可选，不是路由模块的前置条件。

## 使用与复现

从仓库根目录运行。每次 `--output` 使用不存在的新目录；依赖环境、原始输入与审计入口沿用[码块并行说明](qec_patch_parallel_layout.md#复现与审计)。单块新标准示例：

```powershell
python examples/run_parallel_shor15_prefix.py `
  --source references/qec_pbc_validation/shor15_native_prefix_seed0_2026_10_04 `
  --output artifacts/my-patch-routing-standard --patches 1 --layout enola `
  --proposal references/qec_pbc_validation/enola_patch_proposal_2026_10_04.json `
  --intra-patch --intra-services --pair-search --routing-policy standard `
  --readout-placement fixed_translation
```

多块示例使用相同保存源和冻结提案，独立输出：

```powershell
python examples/run_parallel_shor15_prefix.py `
  --source references/qec_pbc_validation/shor15_native_prefix_seed0_2026_10_04 `
  --output artifacts/my-full12-routing-standard --patches 12 --layout enola `
  --proposal references/qec_pbc_validation/enola_patch_proposal_2026_10_04.json `
  --intra-patch --intra-services --pair-search --routing-policy standard `
  --readout-placement fixed_translation --wall-budget 1800
```

默认不加 `--routing-policy` 也选择 `standard`。复现此前发布的固定 5 μm 路线与时间表时必须显式使用 `--routing-policy legacy_5um`，其内部标识为 `legacy-5um-v1`。该选项保留历史路线作为对照，不能把旧数据标成新标准结果。

每次运行的 `summary.json` 记录 `routing_policy` 和路由合同，`producer-source.json` 绑定实际模块字节和调用选项。路线 API 的 `optimality_scope` 用于区分直达与图内最短；若追加逐段最短性审计，应绑定实际请求的 holder/masks、起终构型、设备域、路线与 backend，不能仅凭策略名称判断一段路径的证明范围。

验收至少覆盖独立图距离 oracle、阻挡直线后的半格绕行、活动空 Cartesian trap、关闭备用轴 envelope、真实装卸边界、设备身份、失败纯度、预算/无路区分；实际单块与多块还需完整 Executor、原初态 replay、全局 CZ/依赖/终态独立审计与共用空间回放。通过范围以本轮实际报告为准。

## 2026-10-04 同初态实际验收

本表沿用固定MZ测量端点以隔离routing改动，命令明确使用 `--readout-placement fixed_translation`。后续标准入口默认的自动MZ选点见[设备感知选点说明](qec_rigid_readout_placement.md)，该恢复单独验收，不能将本表写成已完成选点的结果。

新旧各组的 initial/source/circuit/phases 原始字节、效果合批顺序与原生 ID 均相同，只替换路由。全部原门、有限 CZ 与依赖保持。

| 规模 | 原门 / 投影 / 原子 | 旧总时间 μs | 标准总时间 μs | MOVE 段数 | 证据 |
| --- | --- | --- | --- | --- | --- |
| 1 块 | 267 / 50 / 34 | 33409.196973 | 30055.938183 | 479 → 338 | 完整原初态 replay、两层独立审计通过 |
| 12 块 | 3006 / 413 / 221 | 33409.196973 | 30055.938183 | 479 → 338 | 完整原初态 replay、两层独立审计通过 |

两组总时间均减少 **10.0369%**，仍为161 plans、52次CZ脉冲、其中稳定子四层各2次；最大实际CZ批次分别3对与36对。时间是含归还的模型物理时间，执行/重放的机器wall time另记，不混用。

128项不同专项pytest通过，包含16项新路由行为测试与11项既有A*测试；独立手建Dijkstra oracle、真实装卸/Executor/replay、双设备身份/旁观者、活动空Cartesian交点、关闭备用轴域边界、失败纯度和预算分类已验收。266模块架构扫描零违规；显式legacy五份计划与历史字节一致。

完整输入、录制、实际生产模块指纹及审计摘要见[可移植验收证据](../references/qec_pbc_validation/routing_standard_2026_10_04.json)。最终单块使用最终router字节；12块启动后新增的单设备envelope守卫在其双设备运行中不进入。两组运行后CLI仅更正legacy metadata，独立AST检查证明standard合同与实际summary一致；所有实际producer hash保留。viewer的“计划路径”不再把MZ全程叠加统一误称“去程”。

实际[12块空间回放](http://127.0.0.1:8776/)保留同步缩放、X/Z标识和统计折叠，新增2.5 μm半格运输书签；本地12项书签、窄屏和console验收详见该证据的browser项。旧8774及历史录制保留。只证明相同Clifford前缀路由改进，不新增工厂、injection、FT或完整physical Shor完成结论。

# M4 半格通道图最短路

`motion/astar.py::AStarHalfGridPlanner` 已替换 M4 单 trap 与 1×2/1×4 rigid AOD 的有限 L 型路线枚举。M3/legacy 默认 planner 保持原行为。

## 搜索问题与边界

一次搜索固定起态、目标 AOD 配置、所有 SLM/AOD masks 和实际 holder。节点是有限 world 内 `x/y = 2.5 + 5k μm` 的通道交点及起终点接入点；非通道端点只允许不超过 2.5 μm 的短正交接入。原点可行矩形扣除完整阵列的行列跨度，关闭的容量格点也不能出界。

每条边保持所有行列坐标的刚性相对间距。backend 校验移动原子、附带原子、活动空 AOD trap、静态原子、开启 SLM、支撑与边界。`depart` 仅属于第一条边，`approach` 仅属于最后一条边；合并共线段时保留这些交接边界停点。路径进入 ProgramBuilder 后再做完整独立验证，最终只有 Executor 提交状态。

当前只接受 rigid 恒速平移；row_column 明确报 `GRAPH_BACKEND_UNSUPPORTED`。该规划器不会移动独立格点、开关 trap、修改作用距离或绕过碰撞检查。开关 masks 仍由上层 compiler 形成独立候选再比较实际成本。

## 局部最短性与快速路径

A* 使用 Manhattan 距离下界与确定性次序。先在同一图上忽略障碍求最短路径，合并合法共线段并检查整条物理路线。若通过，实际成本等于无障碍图下界，可以直接返回：加入障碍只会删边，不会产生更短路径。若未通过，再执行 backend 逐边验证的 A*。

成功结果在该固定图和固定支撑配置上长度最短；rigid 恒速模型下也就是移动时间最短。它不证明连续空间完备、不同 masks/装卸安排最优或整个电路调度最优。row_column 每段的非线性起停成本不能使用这个长度证明。

默认预算 20000 个节点展开，包含无障碍下界和必要的物理搜索。预算耗尽与图内无路分别报 `GRAPH_ROUTE_BUDGET_EXHAUSTED` 和 `GRAPH_ROUTE_NO_PATH`，包含实际展开、边检查、图规模及相关拒绝码。图内无路不等于连续空间物理无解。

## 接口与复验

`RouteRequest` 保持原有七个位置参数，末尾增加可选 `state`、`depart`、`approach`、`edge_validator`。M4 的 `single_trap.route` 传入只读物理状态。旧调用不传状态或校验器时保留原有限候选兼容行为。

`search(request)` 返回 `RouteSearchResult`：`points`、`distance_um`、`expanded_nodes`、`edge_checks`、`graph_nodes`、`geometry_lower_bound_um`、`fast_path`、`optimality_certified`。`candidates(request)` 保留原 planner 协议。

复验命令：`python -m pytest tests/test_astar_routes.py -q`。测试包含真实双墙绕行（旧 L 模板全部失败、图最短路 80 μm）、独立 Dijkstra 成本 oracle、共同移动的第二颗原子、活动空格点扫掠、关闭容量边界、接入距离及装卸边界、预算/无路区分。测试中的 2.5 μm 障碍候选格距属于专用路径夹具，不改变工作台 5 μm SLM 模型。

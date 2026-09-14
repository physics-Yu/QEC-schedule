# 四逻辑 surface-code GHZ：对称基线与规划器实验

2026-09-11。实验量子定义见 [独立量子核验](surface_ghz_research.md)。本实验从全部数据比特的 `|0>` 开始，包含四块旋转 `[[9,1,3]]` 的完整幺正编码与三个 transversal logical CNOT，合计36原子、135 H、59 CZ。没有测量纠错轮次或噪声模型，不声称容错制备或复现论文中的 color-code GHZ 实验。

## 公平比较合同

- 两份输入只有 `compiler` 字段不同；脚本检查其他字段严格相等。
- 四个量子码的3×3编号图是代码连接图；物理映射为 Q000–Q035 单行，x=0,10,…,350 μm，y=0。四块编号连续。编译器用运输实现门连接，物理布局不假称四个3×3方阵。
- 同一台 rigid AOD，1×36容量，10 μm固定列距、逐列开关。关闭的列仍受完整阵列边界限制；不是36台独立AOD。
- world候选网格仍为5 μm。SZ占据间隔10 μm；联合预置后的EZ占据间隔10 μm，四邻格规则保持、允许经过但不允许无关原子停驻。
- CZ仍为当前全EZ作用对严格相等校验、单个门一次0.3 μs pulse。1Q固定1 μs且只同类型并行，任意邻居距离至少5 μm。
- 主指标为全部门及原始holder/AOD配置/SLM和AOD开关完整归还后的总μs；逻辑完成、AOD路程、装卸次数、编译墙钟另列。

## 一个可构造的对称基线

`row_symmetric`先将完整稀疏原子行联合LOAD、沿合法半格通道运入最近可容纳整行的EZ行、联合OFFLOAD。静态原子之间始终相隔10 μm。在当前输入为 `(0..350,-25)` μm。预置和最终归还都是真实计时任务，不是初态中免费赠送。

对READY的1Q调用共用同类型并行/时间窗口填充。CZ按照确定的电路拓扑顺序选第一个READY门，固定第一个操作数为SLM anchor，将第二个操作数LOAD、运至anchor上方2 μm、施加CZ，再卸回其原EZ格点。所有门完成后全行联合返回原SZ，恢复所有声明的开关和设备配置。

每个门后恢复原EZ排列，给后续1Q和运输留下简单可验证起态。该基线只代表明确的逐CZ恢复模式；不称允许批量CZ、2D伸缩或多AOD硬件下最强的对称算法。

## 规划器改进

`row_greedy`使用同样的整行预置及恢复服务动作族。它考虑全部READY CZ、两种anchor/partner分工、上下左右四个2 μm作用方向，策略不识别surface/GHZ名称或固定gate ID。任意支持门集的单行电路均可编辑和重新编译；行不满足跨度、容量或EZ几何条件时给出明确结构化失败。

对一个候选的服务时间，建立下界：

```text
LB = [D(empty AOD pose, partner source)
      + 2 D(partner source, proposed CZ pose)] / speed
     + LOAD + OFFLOAD + CZ pulse
```

`D`是在实际A*使用的同一有限半格通道图上删除碰撞障碍后的最短距离，保留完整rigid footprint边界及端点接入口。图搜索使用一致Manhattan heuristic；距离缓存只包含不可变几何。去掉障碍不会比保留障碍更贵，因此这是该固定恢复服务族的可采纳下界；开启/关闭成本不被重复添加。

候选按下界排序。只为可能优于当前已验证候选的项构造完整计划；后续下界不小于incumbent时停止并记录剪枝数。最终候选仍经过A*的真实整段扫掠、共享backend、计划审核、Executor事件提交及独立重放。只有全部候选已验证或有下界排除、没有候选验证拒绝时才记录 `local_optimum_certified=true`；作用范围明确为 `restoring_cz_base_duration`，不包含额外Raman窗口填充，更不是全剩余电路全局最优证书。

相比原逐门通用搜索，这一策略改变了上层动作族和候选构造顺序，而不仅是提高站点/前瞻上限。常规M4策略仍可选择，已共用大容量联合预取和归还能力。两族搜索自由度不同，因此“新策略击败固定恢复基线”不证明它在所有布局或相对原完整候选族始终占优。

## 大容量计算优化与边界

空间筛选替代每个四邻点对全部原子的重复距离计算；仍逐次从DAG、holder和存活状态推导许可。AOD每个不可变实例缓存其已验证轴几何，保留int/float与有符号零的原始序列化。缓存不存物理校验的PASS，不使用旧状态授权新状态，checkpoint仍schema17。详见 [大容量运输](large_aod_transport.md)。

工作台已开放128原子、4096门/列、1×1–1×128 AOD。实验显式提高ready/site到128，depth8、beam32、rollout4096，行候选4096、每条A*展开100000，编译时限3600秒。默认小任务仍使用原默认预算/时限；大上限并非速度或完备性保证。

`run_row`提供从静态单行起态开始的构造策略。中途checkpoint可按既有Executor继续已提交计划并独立验证；本轮不承诺中途直接重新调用整行策略会逐字复现原策略决策。

## 复现与可视化

```powershell
python examples/run_surface_ghz.py --strategy row_symmetric --output artifacts/surface-ghz/row_symmetric
python examples/run_surface_ghz.py --strategy row_greedy --output artifacts/surface-ghz/row_greedy
python examples/verify_m3.py artifacts/surface-ghz/row_symmetric
python examples/verify_m3.py artifacts/surface-ghz/row_greedy
python examples/render_surface_ghz.py --output artifacts/surface-ghz
python examples/circuit_workbench.py --port 8769 --output artifacts/workbench-surface-ghz
```

正式产物保存输入、实际预算、全部门、OpenQASM、完整电路SVG、执行trace、checkpoint、recording、两份完整动画、源码指纹和比较JSON。`examples/accept_surface_browser.py`使用独立无登录的headless Edge：载入36原子示例、加H再撤销、实际点击编译、检查联合运输、两模式32×播放以及已完成任务深链接。

工作台 `?example=surface-ghz`只载入可编辑输入，不自动提交大编译。`?job=<id>`读取真实已完成任务的输入与回放，仍可编辑重编译；服务重启或任务被8项保留窗口淘汰后链接失效，离线HTML和JSON仍保留。

最终测量与本轮验证结果见 `artifacts/surface-ghz/comparison.json`、对应 `verification.json` 和交接日志。探索性旧搜索压力探针为主动限时profiling，若终止仅表示未在该观察窗口完成，不能当作物理无解证明。

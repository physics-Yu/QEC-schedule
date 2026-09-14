# 2026-09-11 · CZ 四侧候选与单比特邻近禁光

- 状态：PARTIAL（距离边界与 CZ 四侧已实现并检查；AOD 目标资格待澄清，整体 UI 验收待完成）
- 用户指出移动逻辑疑似强制到左侧；源码确认 greedy 只用 interaction_offset=(-2,0)，backend 本身没有方向要求。
- 本轮：四侧合法 CZ 作用位置及当前位置复用；Raman 邻近原子禁用，同时检查脉冲期间移动的旁观原子；保持六门集/同类型并行/正交通道/实际可编辑编译。
- 最新用户纠正：5 μm 本身允许打光；实际距离 <5 μm 禁止，≥5 μm 允许，不按邻居 holder 豁免。此前 ≤5 μm 或 SLM 邻居例外的理解已被覆盖。目标 AOD 本身是否可打光正在确认；该部分尚未部署和验收。

## 当前实现与检查

- GreedyCompiler 比较四个正交作用侧以及已合法近邻位置的复用，保留源/目标支撑和全路径检查；候选按实际计划成本选择。准备阶段在各方向间共享只读预测，分支独立校验。
- HardwareConfig 新增 raman_minimum_separation_um=5；邻近判断为 distance + 1e-9 < 5 时拒绝。空 trap 不计入邻居，所有 alive 原子按真实位置参与判断。
- Executor 检查脉冲与移动实际重叠部分的完整扫掠，既包括移动中开始打光，也包括打光中开始移动；支持现有线性/共同三次进度的空间线段。M4 当前候选填充保守排除整段靠近目标的 MOVE，可能少利用该 MOVE 的远距离部分；执行器能精确接收合法的局部重叠。
- 若 Raman 目标旁边仍有 loaded CZ 伙伴，greedy 增加显式移开伙伴或迁移目标的候选，移动与支撑开关均计费，不只拒绝后停住。
- 源码 checkpoint 升到 schema 16；交接首页尚未把本轮标为完成，先前服务页面/产物仍代表历史验收。
- `python -m pytest -q tests/test_cz_sides_raman_neighbors.py --basetemp=artifacts/pytest-cz-neighbors`：**8 passed，3.94 s**。覆盖 4.99/5/5.01 μm、SLM/AOD 邻居、四侧 CZ 与零移动复用、移动端点远而脉冲中途靠近的拒绝、同路线早期远距离脉冲的接受。
- 集成检查：`tests/test_m4.py tests/test_adaptive_ez.py tests/test_parallel_orthogonal.py tests/test_gate_contract.py`，**45 passed / 1 failed，186.64 s**，日志 `artifacts/cz-neighbors-integration.log`。唯一失败是旧候选 key 断言没有方向字段；实际选择下侧 `g1/Q002/down/EZ1` 且 loaded 伙伴正确复用。更新该断言后，与距离/方向专项一起复跑 **9 passed**，见 `artifacts/cz-neighbors-final-focused.log`。旧左侧唯一方向的边界失败案例已改为四侧均无 EZ 作用空间的实际几何拒绝案例。

下一步：接收 AOD 目标资格的澄清，完成必要资格/资源/编译与可视化改动，再做最终检查、服务更新及真实浏览器编辑编译验收。不能用此前 340/49 项 PASS 代表本轮已验收。

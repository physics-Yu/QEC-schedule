# 2026-09-12 · 二维 surface patch、非均匀矩形 AOD 与真实批量 CZ

- 状态：COMPLETED（本轮二维、并行、对比、可编辑编译及文档交接完成；不宣称完整M5）
- 用户纠正：36数据原子不能物理排成一条线冒充 surface-code 排布；参考实验二维 patch，必要时关闭四邻格禁占。AOD可按不同间距生成矩形交点并隔原子抓取。
- 旧基线：`artifacts/surface-ghz` 的 row_symmetric/row_greedy 成绩仍是真实历史记录，但只适用于单行恢复服务，不满足此次二维并行目标。

## 实现

- `motion/patch_array.py`：按实际非均匀轴坐标匹配捕获集，联合装卸/刚性运输/成组近接与分离。坐标集合而非逻辑块或门名决定组；活动交点完整Cartesian闭包由后端审计。
- `simulation/patch_greedy.py`：结构基线与并行贪心，READY CZ按相同空间位移分组，比较每完成门的服务成本；完整物理A*路线及去障碍二维通道图下界，避免指数子集枚举，组失败可回退单对。
- `hardware/rigid_aod.py`：去掉“rigid必须等间距”的代码错误；刚性只保持既有相对offset，捕获索引和边界使用真实axes。动态变距仍为独立能力。
- batch CZ：一次pulse对应多个互不共享qubit的门，全EZ实际pair集合必须等于intended，统一START/COMPLETE、逐门exactly once，checkpoint schema18，记录与viewer显示全部同刻pairs；见 `docs/batch_cz_contract.md`。
- 工作台可编辑rows/columns及两组非均匀offset；四邻保护字段默认True，surface示例显式False。任意受支持门编辑后仍实际编译；四个patch原点(0,0),(40,0),(0,40),(40,40)，局部10μm，6×6 axes=(0,10,20,40,50,60)。

## 已有验证

- `pytest tests/test_patch_greedy.py tests/test_row_greedy.py tests/test_surface_ghz.py -q -x`：16 passed /39.20s，含18实际并行CZ+完整compiler-free回放，非uniformaxes，任意H/T/CZ/X线路。
- batch及M3专项43 passed；另40 batch/旧CZ/row/runtime回归（存在重叠，不求和）。18门单脉冲Node控制通过，不能冒充真实浏览器证据。
- 工作台/guard/shape/旧输入兼容63 passed，另guard等54通过（有重叠）。节点控制真实handler通过。
- 最终结构基线194/194、独立GHZ真，8978.2μs、最大18CZ同刻，编译109.70s；新版贪心8149.2μs、编译112.23s。源码运行期稳定，两个正式输出均经最终代码独立物理重放通过。此前首份基线78.07s是开发期单次观测，最终复现时并发负载不同，不能据此比较优化速度。

## 模型边界

非均匀矩形固定axes并整体平移已实现；搜索中动态伸缩行列尚未接入此策略。只关闭用户授权的四邻格停驻规则，碰撞、空活动trap扫掠、支撑、SLM避让、全作用对、5μm Raman、异类型互斥均保持。10μm/2μm/1μs是项目参数，非实测保真度保证。理想酉编码无测量辅助原子/噪声/容错声明。M5真实batch底座按本轮请求提前补齐，不代表完整M5。

## 复现

```powershell
C:/python312/python.exe examples/run_surface_ghz.py --strategy patch_symmetric --output artifacts/surface-2d/patch_symmetric
C:/python312/python.exe examples/circuit_workbench.py --port 8769 --output artifacts/workbench-surface-2d
C:/python312/python.exe examples/accept_surface_2d_browser.py
C:/python312/python.exe examples/verify_m3.py artifacts/surface-2d/patch_symmetric
C:/python312/python.exe examples/verify_m3.py artifacts/surface-2d/patch_greedy
C:/python312/python.exe examples/render_surface_2d.py
```

## 最终成绩、反例和证据

- 正式同二维输入仅compiler不同、同完整归还终态：8978.2→8149.2μs，省829μs/9.233%。415μm AOD路程减少贡献830μs，Raman多1μs；两者24批CZ、最后9+18真实并行，装卸各26次。
- 初版贪心反例14082.1μs、37批CZ、最大4门、39轮装卸；跨块27门从2批被拆成14批。额外装卸2600+移动2486+CZ3.9+Raman14=5103.9μs损失。完整反例另存`patch_greedy_initial`，物理重放和实际GHZ效果均验证。
- 原因与尝试：仅提高深度或仅本地优先模型未击败基线；添加同源行/列Cartesian闭合子组后才出现收益。采用透明的locality_closed策略，balanced_closed只留离线模型。详见`docs/patch_ordering_analysis.md`、`examples/analyze_patch_ordering.py`和`ordering-analysis.json`。脚本固定初版候选族，不随生产函数更新改变历史模型。
- 全部正式大运行后，仅补本地候选全失败时剩余预算跨分量回退；`pytest tests/test_patch_local_fallback.py -q`4项通过8.09s。成功路径顺序、计划和日志保持，两个正式产物在补丁之后`verify_m3.py`逐字重放通过：基线557操作/69计划、新版548操作/70计划、各194唯一效果、精确终态。
- 实际headless Edge新版job `35d259897145482e86032c24ed54a591`：194加H195再撤销194、点击compile、实际9/18绘制、32×物理11.282s/关键帧17.406s全程至8149.2μs、deep-link恢复、page_errors=[]，源码py/js/html运行期无变化。基线另离线Edge实际画布36红原子/18连线及等比例坐标通过。
- 最终代码另做真实编辑任意门集：同36二维平台，实际清空并放H/X/Y/Z/T与跨patchCZ，共6门；job `4cf9a5b67ef54197970ae22ec34f2a49`，1137.3μs、6效果各一次、36原子完整归还，viewer完成6非旧194。`artifacts/surface-2d/edited-smoke`保存完整输入/trace/checkpoint/recording/浏览器报告。验收脚本误读gate_counts.done后改为completed，复用同job完成，无重复编译。
- 报告`examples/render_surface_2d.py`从真实结果/验证文件生成`artifacts/surface-2d/index.html`；1440px/390px真实Edge检查无横向溢出和page error，资源HTTP200，实际截图已检查。完整线路SVG/CSV/QASM只在逐门输入按ID排序相等后复用历史文件；未复用历史单行动画。
- 当前服务：8769 PID15860（workbench-surface-2d）；8780 PID13488（surface-2d报告）。原8769/8780服务已明确替换，旧job深链接失效但离线历史产物保留；8766/8767/8768未动。
- 本轮未跑全量suite，只记录上述有交叉专项，不把数量相加。研究来源均一手论文，见surface_2d_research；没有修改或更新Codex记忆。

## 下一步和边界

优先做多种非对称/异构二维layout与用户编辑电路矩阵，再研究同构批次就绪同步、减少每次归还、动态非均匀轴重构。最小间距连通分量可能把各向异性布置识别为多个行组，只是启发式。当前可编辑门集不意味着任意layout都可路由或全局最优。理想编码不等于辅助测量QEC；完整M5、动态变距规划、多个AOD及M6仍不在本轮完成声明中。

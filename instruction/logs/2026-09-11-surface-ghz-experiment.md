# 2026-09-11 · surface-code 四逻辑 GHZ 调度实验

状态：COMPLETED。用户要求完整编码线路、10μm稀疏布局、充分开放AOD与搜索、构造对称基线、相同布局比较规划器并分析改进，最终可编辑重编译和完整动画。沿用既有pipeline，未进行Git提交、发布或触碰旧工作台草稿。

## 已实现

1. `experiments/surface_ghz.py`：4个旋转[[9,1,3]]数据块，36个|0>起态，block0编码|+L>，另3块编码|0L>，逻辑CX0→1、0→2、1→3；194门=135H+59CZ。CSS幺正编码不是测量纠错或容错制备。参考资料、明确稳定子/逻辑算符/8-CNOT编码见`docs/surface_ghz_research.md`。
2. 大容量`motion/multi_trap.py`：任意配置1×N的同排group transfer、未来CZ需求预取（blocked门不提前执行）、跨行门单侧预置、同平移终态联合归还。后端继续检查全部实际启用交点，仍单CZ/cell0门服务。工作台容量上限128，并不声称所有128列场景验证。
3. `simulation/row_greedy.py`：可构造row_symmetric和通用row_greedy。联合预置后全体EZ SLM相隔10μm，每CZ伙伴回原位，完整联合归还。greedy枚举READY门/两原子分工/四作用方向，下界使用实际通道图删除障碍后的最短距离；仅完整构造有机会改善incumbent的候选。独立Dijkstra对照与小规模穷举实际候选比较，明确证书仅限CZ基础恢复服务时长。预算/终态边界错误已修。
4. `hardware/ez_neighbors.py`空间筛选与不可变四邻点缓存，`world/world.py`AOD不可变实例的派生几何cache，不缓存物理PASS或动态许可。保留原异常优先级与int/float/signed-zero序列化。schema17未变。
5. 工作台128原子、4096门/列、64列分页、AOD1–128、提高可配置预算、逐job时限，普通默认90s。实验显式ready/site128、depth8/beam32/rollout4096、row candidates4096/A*100000、3600s。可载入/编辑/撤销/真编译，ROW_*错误可见；?example不自动启动大编译，?job读取真实已完成结果，可编辑续编译。

## 正式结果

输入除compiler以外逐字段相同，36原子单行x=0..350、y=0；AOD1×36，10μm列距；world候选5μm；EZ预置y=-25；原始holder/AOD pose/masks完整归还。

| 指标 | 对称基线 | 下界剪枝greedy |
| --- | ---: | ---: |
| 完整模拟μs | 36083.7 | 34956.7 |
| 逻辑完成μs | 35113.7 | 33891.360254 |
| 编译s（单次本机负载） | 340.975881 | 292.234204 |
| AOD路程μm | 11889 | 11354 |
| 原子总路程μm | 12094 | 12094 |
| LOAD / OFFLOAD | 61 / 61 | 61 / 61 |
| 完成门 | 194 | 194 |
| plan / operation | 149 / 1134 | 92 / 1099 |
| Raman/运输重叠μs | 47 | 104 |

节省1127μs，3.123293897%。空载3790→2720μs节省1070μs（28.23%），另外57μs来自更多重叠。载原子往返19988μs、装卸12200μs没有变化，约89.2%的原基线受此固定恢复模式成本支配。

greedy总共构造59个CZ候选，按下界剪去4013个，候选预算遗漏0。不是依靠把运行取消在较短前缀获得更快结果，也没有免费初始EZ预置或省略尾部清理。

正式两份`source-at-start.json`/`source-sha256.json`一致，`source-stability.json`为false（未改变）；两份Python源码指纹也相同。墙钟受同机其他probe、回归、独立replay等负载影响，不是统计性能基准。`row_symmetric_pre_cache`为探索前版490.764703s，相同物理结果36083.7μs；没有完整起始源码稳定性证据，仅作探索留档，不据此宣称严格30%加速。

## 验收与证据

- `pytest tests/test_surface_ghz.py -q`：6 passed。32码稳定子+4逻辑GHZ稳定子均为+，穷举码距3，9q稠密振幅独立编码验证，删除末logical-CX层/单CZ负例拒绝。
- `pytest tests/test_row_greedy.py -q --basetemp=artifacts/pytest-row-frozen`：6 passed/24.16s。两策略真实Executor/replay、下界对全部方向实际成本、Dijkstra对照、预算可见/最后清理边界、空线路终态、非法行初态原子性。
- 子agent工作台/API首批46 passed/18.74s，旧multi容量相关12 passed/75.43s，run_m4参数拒绝6 passed/0.17s；深链接新增模块15 passed/4.61s含真实HTTP加载旧物理结果后加X再真编译。不同批次有重叠，不相加为独立测试总数。
- 大容量及旧多trap20 passed/120.73s，含1×9/1×36实际联合搬运/满载checkpoint恢复/跨行单侧预置。
- 最终cache版本路径/row/largeAOD/cache26 passed/17.54s，加row_column/runtime_prefix_cache31 passed/26.84s；之前EZ/CZ/独立brute oracle46 passed/34.98s。保留异常优先级和每次动态许可校验。中间全局LRU曾有int/float数值表示合并风险，已改逐实例缓存并新增精确序列化测试。
- **本轮未重跑全部pytest**，没有将旧460 passed当作本轮结果。所有已运行适用检查无遗留失败。
- `python examples/run_surface_ghz.py --strategy row_symmetric --output artifacts/surface-ghz/row_symmetric`：completed，实际效果顺序独立理想GHZ检查true。
- `python examples/accept_surface_browser.py ...`：headless Microsoft Edge+真实8769页面/API，载入194门，加H到195再撤销194，实际编译按钮生成job6cc94f7ae83c46258f9056a66fe2bd54；194/194，实际效果顺序GHZ=true；joint view、两模式32×推进、终态定位、?job回填原始可编辑输入与回放通过，page_errors=[]。
- `python examples/verify_m3.py artifacts/surface-ghz/row_symmetric`与`.../row_greedy`：两份独立验证器/Executor重放均verified，checkpoint逐字相等，194效果恰好一次，终态与资源区间通过。重放不调用编译器。
- `node tests/viewer_speeds.cjs <两份index.html>`：.25–32×两模式准确映射、终点停止、物理数据不变。
- `python examples/verify_surface_playback.py`：真实headless Edge完整录制连续32×播放，keyframe43.06s、physical44.73s，终态34956.7μs，逐秒采样单调推进、无停滞、无page error。不是只跳进度条模拟播放通过。
- 报告/完整36线SVG已渲染检查；同column多CZ分配独立视觉竖线，避免误画成多体门。列仅为依赖顺序。

## 调研与未计入成绩的结果

`legacy-search-probe`：相同36/194/36traps且高预算，独立60秒主动限时profiling。初始36H完成、仿真1μs，首个CZ SGHZ006从5.659s起枚举未返回；42组anchor/site、165方向开始，MultiTrap joint尚未开始。说明先完整构造单服务候选再考虑联合预取的搜索结构问题。该观察不证明无解或旧策略不能最终完成；没有改用户服务。

`docs/surface_ghz_ordering_analysis.md`和`ordering-analysis.json`：各CZ必须最终支付的内禀服务成本与次序无关，应在全线路评分里保留剩余必付项，不能单纯偏好短门。模型对已运行两策略的AOD busy精确相符；内禀校正估计空载1730μs，有限beam2640/2380μs，增加搜索深度不保证更好。**这些新排序只经过离线几何模型，没有完整物理/Raman/量子/浏览器验收，不属于本轮已交付成绩。**

## 入口、边界与下一步

- 报告 http://127.0.0.1:8780/，PID24816，静态根`artifacts/surface-ghz`。
- 已编译且可编辑 http://127.0.0.1:8769/?job=6cc94f7ae83c46258f9056a66fe2bd54，PID5880，服务输出`artifacts/workbench-surface-ghz`；?example=surface-ghz可重新载入模板。job深链接只保留于服务内存8项窗口；离线HTML/JSON持续在磁盘。
- CUA接口失败；本轮真实浏览器验收为独立无登录headless Edge，不声称操作了用户当前标签页。旧8768、8767、8766未停止、刷新或覆盖。
- 当前仍rigid单排恢复族、单CZ光照、cell0服务。没有2D行列伸缩优化、多个独立AOD、跨门任意多cell驻留、批量CZ或测量反馈。
- 下一条可执行工作：将`analyze_row_ordering.py`的内禀校正作为可选通用行策略接入（当前明确不修改已验收row_greedy含义），以同一输入和终态重新完整物理/量子/动画验收。若改动作族去掉逐CZ卸载，需先说明Raman5μm、作用对和多cell支撑约束；不得将预测1730μs直接当模拟成绩。

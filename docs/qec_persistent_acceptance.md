# 持续 AOD 复用：第二步首次验收

2026-09-12，attempt 1：PASS。完整执行、独立物理重放、真实编辑编译及完整动画均通过；持久状态记录在 `artifacts/qec-roadmap/status.json`。

## 同输入的实际结果

冻结基线为用户原工作台提交的481门/控制槽、34原子、二维布局、seed7、Y(Q000)，原始SLM归还终态不变。新策略为 `qec_persistent`；原 `qec_ghz2` 保留。

| 指标 | 冻结基线 | 持续复用 |
| --- | ---: | ---: |
| 完整物理时间（μs） | 22055.9 | 20885.9 |
| LOAD / OFFLOAD | 51 / 51 | 45 / 45 |
| 105个CZ所用pulse | 33 | 33 |
| AOD路程（μm） | 3498 | 3498 |
| 原子总路程（μm） | 15610 | 15610 |
| Raman忙时（μs） | 33 | 63 |
| 提交plan数 | 93 | 150 |
| 本机单次编译墙钟（秒） | 189.438 | 326.401 |

六次相同捕获组续用各省一对装卸，合计1200μs；当前核心逐个移动原子的Raman操作独占AOD资源，保留载原子后多出30μs单比特串行时间，净省1170μs（5.31%）。CZ批次数及运输距离未改善，不能声称增加了CZ并行性。

编译本次明显更慢。策略为了严格保持基线候选顺序，先在纯预测卸载态验证原服务，再在实际载原子态构造与验证持续计划；新增释放边界及单比特拆分也增加了计划数。这些是代码可见的重复工作来源，尚不是逐函数性能剖析结论。墙钟为本机单次观测，统计性能与优化留在后续阶段。

## 正确性与证据

- `tests/test_qec_persistent.py` 首次2项通过：同组CZ–H–CZ真实省200μs；换组必须显式释放，效果和终态一致。
- `examples/run_qec_persistent_acceptance.py` 首次完整执行：481效果各一次、32测量位及32RESET投影逐门与基线相同、实际条件纠正ID相同，量子GHZ₂和测量协议检查通过，正式运行源码未变。
- `examples/verify_surface_qec.py artifacts/qec-roadmap/step2-attempt1` 不调用编译器，独立执行150份计划，通过物理校验及checkpoint逐字一致，34原子恢复原SLM。纠正前XX/ZZ为−1/−1，纠正后为+1/+1。
- 正常搜索候选排除仅 `PATCH_CAPTURE_CLOSURE` 64项和 `CAPTURE_CHANGED` 4项；没有把计划绑定、事件一致性等内部错误掩盖成正常候选失败。
- 工作台入口和只读恢复15项首次通过。真实Edge编辑4门H/CZ/H/CZ并点击编译，4个效果各一次、1246.6μs、物理completed；这份短线路预先声明并非GHZ协议，量子GHZ指标为false符合预期。保存的完整481结果在physical/keyframe两模式32×播放至终态，26.734/27.578秒，无page error，保留AOD时的H帧检查通过。

可编辑入口：`http://127.0.0.1:8783/?job=38839edeb9eea6eae376020ca54c7662`（PID27364）。页面明确标注保存的真实执行结果，修改后点击编译才启动新工作。全线路没有为制作入口而重复编译。

实际产物保存在 `artifacts/qec-roadmap/step2-attempt1/`，含input、strategy、recording、完整HTML、trace、checkpoint、决策、量子结果及verification。input保留冻结基线的compiler标签以便逐字核对，strategy明确实际执行器为 `qec_persistent`；工作台恢复展示会显式标注保存结果来源。

本阶段尚未实现动态轴伸缩、多个AOD、任意布局最优或全噪声容错。保持所有现有路径、捕获闭包、SLM开关、实际CZ作用对和读出条件校验。

# 2026-09-21 ZAC 大实例 benchmark

用户要求：在既有 ZAC reuse-aware 接入和本框架可视化的基础上，需要更大的 benchmark。未要求新任务、发布或修改物理规则。

## 改动

- 新增 `examples/benchmark_zac_reuse.py`、experiments 中的 `zac_benchmark.py` / `zac_benchmark_report.py`。生成 repeat / butterfly / seeded random 全匹配层，批量隔离运行 reuse 开关，逐份保留失败，保存代码 SHA256、输入/预算/seed/依赖环境、CSV、HTML、plans/trace/recording。
- 输入扩展到 2–128 原子、1–4096 CZ；允许显式 1–7200 s 本地预算。默认原几何公式、源算法、AOD 总容量和物理参数保持。实验规模增加时几何和 AOD 容量也扩展，不能称固定设备强扩展。
- 计时分开记录作者 frontend、作者含 routing/verifier、本地规划执行/录制、独立重放。μs 阶段成本来自接受 decisions；秒为主机墙钟。完全恢复初始 holder、轴及 masks 后才能算成功。
- 定位大容量小批次的 `AXIS_BOUNDS`：旧候选把空闲轴全部向右/上延伸 10 μm。新增可选 `bounded_spares`，在两端共同容纳的左/右/内部间隙分配禁用轴，依次尝试 10、2.5、硬件下限+0.01 μm。环境/连续碰撞/Cartesian 捕获校验不变；旧策略默认 False。
- 第一次最紧间距实现造成离散 corridor 候选塌缩。其结果保存在 `benchmark-bounded`，14 failed、2 cancelled；取消通过精确匹配输出目录的 parent/children 执行，不记作物理失败。新工具 `tools/cancel_zac_benchmark.py` 保留已收集结果与明确取消原因。
- 较宽间距版本先在独立 `artifacts/zac-reuse/grid-source` 源码快照中运行，随后接回主源码。实验后核对环境和策略所有 Python SHA256 一致；最后仅主编排器增加取消项 elapsed=None 的打印处理。
- 原工作台保留，新增 benchmark 链接、输入导入、预算和闲置轴开关。大电路显示全部 gate/Q，电路区域限高滚动，原子编号详情折叠，共用物理 viewer。
- GUI 发现最终操作 end 与录制 duration 差约 3e-11 μs，导致已结束仍显示 AOD 运动。共用 viewer 对 active/end 使用既有 ULP 显示容差；未改录制、物理时间或状态。重新生成 ZAC 视图并验证中点 pulse 仍 active、终点不 active/静止。

## 执行结果

原批 `artifacts/zac-reuse/benchmark-large`：N=16/32/64/128，depth=8，三族，random seed20260921，2 workers，600 s 软预算/1200 s 进程上限；24 份中8 completed、16 failed。repeat 四种规模的总物理时间均21299.470→3595.479 μs，−83.12%；原子装载次数272/544/1088/2176→48/96/192/384。这是并行容量一起扩展的正对照，不是一般电路平均收益。整批收集833.50 s。

较宽间距批 `artifacts/zac-reuse/benchmark-grid`：N=16/32，蝶形及random、同预算；8份中7 completed、1 failed，整批763.10 s。

| case | no-reuse μs | reuse μs | 结论 |
| --- | ---: | ---: | --- |
| butterfly16 / 64 CZ | 53294.970 | 33799.620 | −36.58% |
| random16 / 64 CZ | 61434.983 | 44392.072 | −27.74% |
| butterfly32 / 128 CZ | 末尾恢复失败 | 41552.119 | 不计算比值 |
| random32 / 128 CZ | 128809.089 | 97369.461 | −24.41% |

butterfly32 no-reuse 128 CZ 已完成（逻辑完成73083.198 μs），但 `terminal return` 为Q016找不到有限路线。85778.265 μs 仅为前缀，不能和完整reuse作速度对比。random32原子装载次数544→306；本地规划执行/录制246.10→135.78 s，独立重放118.29→75.75 s。主机存在并发和其他检查负载，秒数只报告本次观察，不是专用空闲机器编译速度。

## 验证与证据

- `python -m pytest tests/test_zac_benchmark.py tests/test_zac_reuse.py tests/test_environment_boundary.py tests/test_batch_cz.py -q`：52 passed（初次有界实现）；较宽间距接回后前两个测试文件26 passed。
- `python -m pytest tests/test_ordered_axis_greedy.py tests/test_ordered_routes.py tests/test_axis_hold_routes.py -q`：17 passed。新独立单原子运输测试验证旧方案AXIS_BOUNDS拒绝、新方案真实执行/重放一致，不修改世界/硬件。
- `python -m pytest tests/test_visualization.py -q`：6 passed。
- `tools/audit_zac_benchmark.py` 三个批次通过，分别核对24/16/8份结果状态、同初态、trace exactly-once、ASAP深度、阶段总和、驻留完整性及成功项的终态字段。
- `node tests/zac_reuse_viewer.cjs artifacts/zac-reuse/benchmark-large`：24录制、75 CZ pulse、1680驻留区间；`benchmark-grid`：8录制、64 pulse、349驻留区间；旧5例默认检查10录制、28 pulse、24区间。两种模式32×、pair=2μm、SLM holder、源数据不变均核验。
- 终点新增断言初次误置在pulse中点循环导致测试失败，已移到真正终点；中点独立断言仍要求1个active pulse。修复后上述Node检查重新运行。
- `python tools/check_architecture.py`：188模块、零违规。物理模型与后端未修改。
- 真实浏览器：汇总规模筛选、失败/完成区分、32原子随机完整输入+bounded=True+600秒导入原编辑器；128原子512门首层64对pulse定位和两种模式32×终态；32原子随机16对pulse定位、关键帧32×自动到97369.461 μs且128/128完成。最终容差修复后重新载入验证“记录结束”“静止”“承载0原子”。

当前本任务服务 `http://127.0.0.1:52813/`，PID20896。原始更大规模入口 `/benchmark-large/index.html`，复杂线路入口 `/benchmark-grid/index.html`，均有CSV和现有viewer；原49901服务未关闭。文档见 `docs/zac_benchmark.md`。

## 未完成范围 / 下一项

当前最高完整复杂线路为32原子随机128 CZ，最高完整规模为128原子重复配对512 CZ。较宽间距版本的复杂64/128尚未完整评估；原始失败不证明物理无解。下一可执行研究项为调查蝶形32终态Q016/边缘buffer的路线构造，再以新目录重跑同合同，不能删除原失败。完整AE应用benchmark、混合1Q、保真度、固定硬件强扩展、更多seed统计均未声称完成。无提交或推送。

# 2026-09-16 动态 AOD 回放与工作台查验

## 需求与根因
用户发现初始偏移界面像固定抓取点，要求恢复自行决定偏移的强 AOD。核对当前8b98输入、决策与OrderedAxisGreedy/build_batch后确认能力已经接入，不能冒称此次才实现。旧例仅一对CZ且未展示坐标过程。本轮保留现有物理/策略，补齐可观察性和带载变距见证。

## 改动
- 平台x/y明确标注初始相对偏移；有序与rigid语义分开。
- VisualRecorder只读记录MOVE源/目标行列、启用掩码和移动原子；旧记录从movement帧回退。
- 共用viewer实时显示绝对/相对轴坐标、当前轴运动和目标；新增载原子变距跳转（只有空载变距时明确标注空载）。统计按真实运动段计，包含往返。
- 原工作台决策表列出抓取/作用坐标并支持批次跳转。nonuniform_pairs线路示例只改gates，少于6原子明确拒绝；配置JSON可导入与独立编译。
- 生成Demo及维护文档同步；RL本地工作保留，未纳入。

## 本轮证据
- `pytest tests/test_ordered_workbench.py tests/test_visualization.py tests/test_studio_config_files.py -q`：26通过。
- `pytest tests/test_dynamic_aod_workbench.py -q`：2通过（双策略、3对同批、带载变距、终态恢复、独立逐字重放）。
- `pytest tests/test_studio_config.py tests/test_environment_boundary.py tests/test_workbench_compilation_config.py -q`：66通过。
- `node tests/dynamic_aod_viewer.cjs <job>/index.html`：实际JS中点三次插值、变距跳转、只读性及旧记录回退通过。首次检查因VM跨realm数组原型不同导致deepStrictEqual失败（数值完全相同）；改为宿主Array.from后通过，未修改物理预期。
- `node tests/ordered_workbench_controls.cjs http://127.0.0.1:49870`：实际编辑器JS+HTTP，任意原子数/布局/非均匀配置、贪心与SMT编译、新电路示例及真实变距记录通过；DOM/Canvas替身不等于GUI。
- 架构检查161模块/0违规（包含本地RL）；bundle132文件校验通过；HTTP10项通过；JS语法检查通过。
- CUA getState连接仍失败 `nodeRepl.fetch request failed`，没有真实GUI截图或交互PASS。

## 交付
`http://127.0.0.1:49870/?job=cd31e74422b8455f9e3c6cc9123c8b66`，PID28096。
文件 `artifacts/dynamic-aod-workbench/jobs/cd31e74422b8455f9e3c6cc9123c8b66/` 包含输入、recording、checkpoint、独立HTML、decisions及逐原子统计。
6原子row / 1x3 AOD / 初始偏移[0,15,35]；3CZ同批，抓取x=[10,40,50]→作用x=[-2,22,32]，间距30,10→24,10μm。仿真2838.981509μs，本次编译3.467s（非隔离性能基准）。历史端口保留。

## 未解决与下一步
真实GUI验收仍OPEN。每批归还、有限beam/路线、未用轴+10μm补齐及全局驻留仍是策略限制；此次没有扩张完整搜索空间，也没有重跑480槽完整QEC（该证据在上一日志）。下一步优先按实际新电路评估候选覆盖与跨批驻留成本。

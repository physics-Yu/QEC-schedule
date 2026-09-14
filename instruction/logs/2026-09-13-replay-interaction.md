# 2026-09-13 · 回放主动操作与图形界面验收

- 状态：COMPLETED
- 用户要求：解释回放用途并解决难以主动操作；明确要求两个agent分别提出优化和直接操作GUI验收。
- 分工：physics_research只读设计审查；acceptance真实隔离Edge逐项操作；root实现与集成。

## 已定位原因

旧GUI在1440×900时canvas y78.84–690.84可见，播放按钮y951.84在屏外。鼠标位于画布时普通wheel600保持scrollY1874却把zoom1改0.65，妨碍向下找按钮。点播放后canvas.y=-299.66，主要原子区域滚出视野。底层播放、暂停、拖时间轴和缩放并没有普遍失效。

另外四个实际门：QEC0009批H、QEC0049批CZ、prepare_X0_0测量、QEC0186复位，选择后定位按钮均禁用。原因是workbench只查单gate_id和CZ/Raman，没有识别批次gate_ids或MEASURE/RESET。

旧证据：`artifacts/replay-interaction-before/actions.json`及截图；真实输入导出保留，零编译请求、零page errors。

## 已实现

- 共用viewer将播放与时间轴置于画布前，并在页面滚动时保持操作条可见。加入暂停/播放/终点提示、有效范围内的μs跳转、到终点、键盘空格和左右事件操作。
- 普通滚轮滚动页面，Ctrl/Meta＋滚轮才缩放；保留拖动、缩放按钮、全景，新增聚焦原子（仅视图平移缩放）。
- 静态无操作记录明确显示静态布局，禁用播放/时间轴，不再显示周期完成。
- 工作台回放画布先于长诊断明细，增加专注回放；门定位统一单/批次ID及CZ/Raman/measurement/reset，按原记录中点暂停。条件false保持未打光语义。
- 同时缓存同一回放时刻的活动操作查询，避免每次绘制按每颗原子重复扫描；不写输入或执行状态。

## 验证

- `pytest tests/test_replay_interaction.py tests/test_slm_display.py tests/test_raman_batch_visualization.py tests/test_visualization.py -q --disable-warnings --maxfail=1`：12 passed in9.74s。
- Node workbench_temporal_four_controls / workbench_large_controls：PASS。
- 新GUI全动作复验PASS：四门定位精确到H1110.5/CZ1247.15/MZ7157.3/RESET7457.3μs并暂停，测量中点无读出；鼠标拖时间轴、物理与关键帧32×、前后事件、数值12345、起终点、Space/左右键、zoom/pan/原子点击、聚焦/全景均正常；初始及clear空预览禁用。证据 `artifacts/replay-interaction-after/actions.json`、review-summary.json和截图。
- 第一次after仍存在布局不合格：控件顶部但重复标题和指标挤占画布；#viewer overflow:hidden阻挡sticky。继续修复为overflow:visible，嵌入compact隐藏重复标题、指标移后、planner细节折叠、两行工具、44vh画布。只复验布局而不重复全部动作。
- 最终布局GUI PASS：1440×900专注回放中播放y114.75、slider231.75、canvas409.25–805.25完整同屏。滚动后播放吸顶y47、slider164；实际播放推进，page_errors为空、compile请求0。root再次检查图像。证据 `artifacts/replay-interaction-layout-final/review.json`，截图focus-complete-canvas.png/playing-complete-canvas.png/scrolled-sticky-controls.png。
- 最终布局检查第一次严格console断言遇到资源404，定位URL为favicon.ico，原证据initial-console-check.json保留；最后仅排除此已核实的图标404，其余console错误仍失败。不是脚本或物理失败，不宣称完全零console资源报错。
- 最后compact改动后test_replay_interaction再PASS0.82s，Node temporal_four控件再PASS。没有重跑完整1868槽或小时级物理重放。

## 范围

没有改物理、编译器、recording事件或门时长。当前已编译实例仅回放验收，不重新编译1868槽，不操作用户未导出草稿。新代码通过8788静态文件生效，已打开旧页需重新载入。

## 交接

用户本轮目标完成，两个指定agent分别给出设计分析和直接GUI before/after证据。8788服务不重启，原savedjob保留，未刷新用户持有的旧页面或改其草稿。打开更新页面后点「专注回放」，可直接控制已执行记录；改物理轨迹仍需编辑线路后手动编译。

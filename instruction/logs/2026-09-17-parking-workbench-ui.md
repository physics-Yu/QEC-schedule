# 2026-09-17 · Parking 分享版恢复原工作台

用户纠正：分享版应保持原有工作台及格点可视化，不应呈现为独立项目；认可红色目标/蓝色固定原子的显示。继续保留无需本地编译器、可编辑和再次分享的前次要求。

## 改动

- `parking_portable.html/js` 恢复原 Parking 页的实验参数、格点编辑、原子执行回放结构；移除单独产品式大标题/独立SVG运动画布。方法介绍放回说明区。
- `parking_recording.js` 将浏览器模板转换成共用 `neutral-atom-view/2` 展示时间线；标明构造式模板来源、非Executor审计。包含全活动轴、支撑交接、源SLM在转移完成后关闭、路径、静态网格与候选点。
- `tools/build_parking_portable.py` 直接内嵌维护中的共用 `viewer.js` 与shell。页面保持单文件、无后端、无网络请求；文件名保留兼容，下载的文件仍能编辑和生成。
- 共用viewer增加可选角色颜色、空SLM虚线圈和模型说明；未配置的其他界面保持原按活动着色。原Python Parking工作台也传入角色配色，算法/环境物理执行没有改变。

## 验证

- `node tests/parking_shared_viewer.cjs`：实际共用renderer运行于DOM/Canvas替身。逐行/逐列共182个采样时刻，每次85个原子的坐标、holder、源SLM启用状态均与模板采样一致；红蓝色、网格候选点、下一事件、32×到终点通过。无选项时原静态蓝/移动橙颜色保持。
- `node tests/parking_portable_ui.cjs`：原结构控制器、100格点、画笔与键盘、撤销、手动生成、参数错误、逐列、导入/导出、分享文件重开继续编辑通过；此项renderer用替身，上一项测试实际renderer。
- 构建器重新生成HTML/ZIP，Demo bundle同步共享viewer。真实浏览器连接本轮仍返回`nodeRepl.fetch request failed`，没有实际GUI验收。
- `python -m pytest tests/test_visualization.py -q`：6 passed；`tools/check_demo_bundle.py`：134文件哈希/链接通过。当前HTML约186 KB，ZIP约41 KB，当前验收摘要`artifacts/parking-portable/acceptance.json`；旧摘要保留`acceptance-lab-v1.json`。
- 本轮不提交/推送、不改RL或模板策略。历史完整环境核验和188组几何检查见前一日志；不将其称为本轮重跑。

## 交付

原入口 `artifacts/parking-portable/Parking-Lab.html` / ZIP 与 `demo/parking/index.html`。下一步人工确认浏览器显示/下载。优化版策略仍未实现。

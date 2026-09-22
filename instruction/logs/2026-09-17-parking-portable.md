# 2026-09-17 · Parking Lab 离线可编辑分享版

## 用户目标与范围

重做当前 Parking 可视化，直接把 demo 发给别人，不需要接收者安装本地编译程序，仍能修改示例，并介绍 patch 移动方法。承接用户对标准构造不应耗时编译的要求。本轮未提交/推送 GitHub，不修改环境执行器和 RL 工作。

## 实现

- 纯 JS 标准模板放在策略包，`preset/normalize/compile/sample` 可独立调用；运行时无搜索、无网络、无完整环境逐步审计。
- 新 SVG 界面包含10×10图案、灰色虚线空圈、红色目标、蓝色固定原子、5种预设、画笔、撤销、逐行/逐列、折叠参数、手动生成、分步解释、共享行列完整交点、最高32×、时间轴和关键节点跳转。
- 当前配置＋动作＋完整编辑器可重新导出一个 HTML，接收者继续编辑、生成、播放、分享。支持 JSON 往返。
- 明确隔离规则 patch 的教学合同；容量/偏移/终点/外部障碍不符合时返回错误，不静默退回其他算法。完整 Python Executor 服务仍由原独立入口提供。
- 源文件与构建器维护单页；`demo/launch.py` 的 Parking 入口改为静态页，不再另启 parking 编译服务。整套 Demo 恢复首页＋三个编译服务。

## 验证与证据

- `node tests/parking_template.cjs` 加4个 reference目录：PASS；188组独立解析扫掠/闭包/有序轴/终态检查；2×2三态穷举、随机10×10四种间距、额外空轴。
- 对照既有完整 Executor 记录：`artifacts/parking-large-grouped/jobs/{c45be1e47faa4ce4ad63350590b5bf02,d814b3a792124fd7a731597367e90bd6,91c740853beb4a759a1e730fd9f19c06,f2bc2a8166fb45889f564e999ecbb7a4}`。逐操作类型、时间、移动轴起终点一致；包括用户修改例。不是本轮重新运行完整 Python 物理仿真。
- 默认44动作，10次拾取，43目标/42固定/15空；pickup 2201.624837 μs，总2776.544171 μs。100次10×10直接规划：中位1.86 ms、P95 3.14 ms、最大5.07 ms（本机 Node；非浏览器帧率/完整物理编译耗时）。
- `node tests/parking_portable_ui.cjs`：PASS，实际 HTML 脚本 + DOM 替身；编辑不自动生成、错误禁播、逐列、seek、32×终态、导入/导出、分享重开及继续编辑。初次测试用 deepStrictEqual 比较不同VM对象导致原型差异，改为序列化比较；不修改应用掩盖失败。
- `python tools/build_parking_portable.py`、`python tools/build_demo_bundle.py`、`python tools/check_demo_bundle.py`：PASS，134文件哈希/链接；独立HTML约132 KB，ZIP约23 KB。
- `python tools/check_architecture.py`：PASS，164个Python模块、无包边界违反。
- `python tools/check_demo_http.py`：PASS，首页与三编译服务正常，Parking链接指向同一静态HTML且内容哈希一致，不启动Parking编译服务；已保存QEC回放与接口烟测保持。最终交付HTML再次运行离线UI测试PASS。
- 浏览器连接 `cua.getState()` 本轮失败：`nodeRepl.fetch request failed`；尚无真实 GUI/下载对话框验收。已请求在应用内打开交付文件（工具返回 queued），不将打开请求当作浏览器验证。

## 交付与下一步

- `artifacts/parking-portable/Parking-Lab.html` / `Parking-Lab.zip`；仓库入口 `demo/parking/index.html`。
- [使用和模型边界](../../docs/parking_portable.md)。源在 `src/neutral_atom_app/visualization/parking_portable.*` 与 `src/neutral_atom_strategies/motion/parking_template.js`。
- 当前动作生成已毫秒级；下一步先人工核验真实浏览器显示与下载，再独立实现 Pattern 优化候选，与相同输入标准模板对比，不改模板/环境硬条件以制造改善。

# 2026-09-11 · 隔离 HTTP 服务与浏览器连接恢复

- 状态：COMPLETED（本轮服务与内置浏览器连接恢复并验证）
- 用户目标：恢复此前被自动审批拒绝的 8767 隔离测试服务和不可用的浏览器连接，补齐实际检查。
- 范围：开发工具连接与工作台验收；不修改物理编译、validator、Executor 或审批规则。
- 相关规范：`instruction/workflow.md`、`instruction/visualization.md`。

## 已完成

- 核实主服务仍为 127.0.0.1:8766，PID 12336；独立测试前 8767 未监听。
- 通过正常终端执行 `python examples/circuit_workbench.py --port 8767 --output artifacts/workbench-http-check`，成功监听 127.0.0.1:8767，PID 22204。本轮没有再出现审批拒绝，也没有更改审批、安全或网络设置。历史工具仅返回 `blocked by policy`，其具体拒绝理由仍不可确定。
- 浏览器首次 `cua.getState()` 复现 `Browsers: Error: nodeRepl.fetch request failed`，发生在枚举阶段。使用公开 `js_reset` 重置会话后，通过 `cua.getBrowser({url: 'http://127.0.0.1:8767'})` 选择内置浏览器并新建隔离页成功。此恢复证明本轮连接可用，不证明已经确定底层根因或所有浏览器枚举均恢复。
- 真实浏览器默认 greedy 编译成功：8/8 门、21 个物理操作、1028.515 μs；32× 关键帧完整达到 1028.52 μs / 100%，自动停止，8 门完成。观察到 Raman 与运输并行时的实际页面状态。
- 保持 8766 主服务和用户原草稿；HTTP 编辑测试只提交至独立 8767。
- 真实浏览器编辑 G003 的 θ：0.3 → 0.123；先显示旧版本 1，再手动编译为版本 2。定位执行显示 `U(0.1230, 0.7000, -0.2000)`、102.50 μs、稳定 SLM S002，同时 Q000 在 AOD 运输。
- 展开并查看真实浏览器资源图截图：AOD 1027.52 μs、Raman 5 μs、CZ 0.9 μs；Raman 100–104 μs 与运输 100–170.71 μs 同轴显示。真实时间比例模式也在 32× 播放到终态并停止；测试页作为本轮可继续查看的产物保留。

## 验证

| 命令/检查 | 本轮结果 | 证据 |
| --- | --- | --- |
| `python -m pytest tests/test_workbench.py -q` | 16 passed in 18.91s | 包含 HTTP、Origin 拒绝、真实子进程编译、取消/替换、超时 |
| `node tests/m4_workbench_controls.cjs http://127.0.0.1:8767` | PASS | `artifacts/m4-editor-http.json`；实际 HTTP + DOM 替身，非视觉证据 |
| `node tests/playback_boundaries.cjs artifacts/ez-switch-current/index.html artifacts/ez-switch-demo/index.html` | 2 个实例 PASS | 完整 1×/32×、暂停续播、原 recording 不变 |
| `node tests/playback_boundaries.cjs <artifacts/m4-debug-current 下六个 HTML>` | 6 个实例 PASS | 包含 bea1faa3… 与 16177b8… 原卡住记录 |
| `python examples/verify_m3.py artifacts/ez-switch-current` | verified | 10 effects、56 operations、3565.3432094505174 μs |
| `python examples/verify_m3.py artifacts/ez-switch-demo` | verified | 0 effects、9 operations、374.80109889280516 μs |
| 内置浏览器隔离页 | PASS（本轮范围） | 真实编辑/编译/门定位、资源图截图、两种时间模式 32× 播放到终态 |

## 限制与下一步

- 原运行会话已在本轮排查期间补齐全套回归日志：308 passed、1 warning、613.38 s，见 `2026-09-11-ez-switch-playback.md`；这里区分原会话结果与本轮独立运行的 16 项专项结果。
- 未改应用源码或插件安装文件，未关闭审批、防火墙、Host/Origin 检查；原始 `blocked by policy` 的具体原因未知，不能声称永久消除审批拒绝。
- 浏览器恢复路径为重置工具会话后直接选定内置浏览器。外部 Chrome/Edge、全局枚举和长时间 FPS 不在本轮验证范围。
- 服务按本轮核实的 PID 22204 保留，停止前须再次核实 PID/命令行。若 8767 被占用，应查明已有监听，不盲目杀进程。
- 下一项开发继续沿用 handoff 的 M4 范围。再次出现连接故障时，按工作台文档区分服务响应与浏览器工具连接，不把工具错误当成物理编译故障。

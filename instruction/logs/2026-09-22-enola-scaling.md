# 2026-09-22 · Enola Figure 2 风格原生扩展实验

- 状态：COMPLETED（首轮有界实验）；5000级完整对照仍OPEN
- 用户目标：基于引用的 Enola 对照工作，将相同公开三正则图扩展到当前千/5000原子规模。
- 范围：原生软件栈的编译和指令评分；与旧30/40/50原子本地 Executor 物理验收分开。Figure2损失分解和Figure9编译时间分别呈现。
- 不改变生产编译器、物理约束或原可视化。
- 逐级单进程、有界墙钟/内存，保留输入、原始输出和失败；不以GHZ链替代三正则图。
- 最终12次：8完成、4超时，完整配对至1000原子。命令/指标/限制见 [实验说明](../../docs/enola_scaling_benchmark.md)。没有重跑OLSQ-DPQA、没有复现原文10图统计或声称5000规模成功。

## 实现与交付

- `examples/benchmark_enola_scaling.py`：公开graphs.json逐级单进程，300s/3GiB预算，输入/源码冻结、进程树资源、失败保存。原QMAP C++及生产工作台/Env不修改。
- `tools/enola_scaling_worker.py`：原生动态SA+windowIS1000，full_code=False紧凑指令；阶段计时、完整门与holder账本、log域评分。阵列边长按本轮max(16,ceil(sqrt(n))+4)，非原文确切资源参数。
- `tools/score_qmap_scaling.py`：真实EZ曝光，按原子统计装卸，作者运动计时；复用独立H/CZ/holder/CZ位置/终态审计。
- `tools/render_enola_scaling.py`：嵌入图表的中文HTML、三组PNG/SVG/PDF、CSV/JSON，失败不补零、严格配对；两方法超时标签分离。
- `tools/analyze_enola_scaling_schedule.py`及`tools/audit_enola_scaling.py`：调度层因果检查与原始输入/计数/算术核验。
- 产物 `artifacts/enola-scaling-20260922/`；静态服务63841（PID40136），已请求在Codex打开，工具返回queued，故不宣称实际GUI点击验收。

## 测量

| n | Enola原生s | QMAP原生s | E / Q脉冲 |
|---:|---:|---:|---:|
|30|111.880|0.138|4 / 9|
|100|118.898|0.869|4 / 13|
|300|140.063|7.567|4 / 16|
|1000|206.926|141.601|4 / 20|
|2000|300s预算超时|300s预算超时|N/A|
|5000|300s预算超时|300s预算超时|N/A|

1000例QMAP落点141.466s、路由0.075s；Enola总放置186.245s、路由16.767s。模型时间412.174/563.518ms；−ln F 336.595/489.819。硬件容量/曝光/终态不同，不能解释成纯算法排名。每规模仅graph0。

## 验证

- `python -m pytest -q tests/test_enola_scaling_worker.py tests/test_enola_scaling_report.py`：本轮最终8 passed，1项第三方datetime弃用warning。
- 完整12份`suite-audit.json`通过：输入/装卸/CZ/模型算术，4超时无完整程序；没有关闭物理检查冒充通过，因为本轮没有走本地物理Env。
- 原生Enola校准与历史full-state逐条相同，fresh作者Simulator各分量相同；142.082s校准不混入正式111.880s测量。
- 结构化异常负例 `artifacts/enola-scaling-worker-validation/invalid-duplicate`：0.55s失败，保留ValueError与完整worker-result.json。
- PNG静态图查看、HTTP和本地下载核验；没有交互动画验收。

## 工程问题与记录

- 首次git来源读取遇Windows所有权检查，限定到已验证Enola路径使用单次`git -c safe.directory=... rev-parse HEAD`；没有修改全局git配置。
- 正式QMAP运行中未使用的Enola校准辅助代码更新。QMAP执行源未变；正式Enola启动前重新冻结该helper，旧源码/manifest保留并记source_revisions。图表和原生数值未因此修改。
- 表示fidelity下溢时，使用实际`exp(logF)==0`，不把subnormal值误标为0。模型超出正定义域必须N/A。
- 全部12次结束后加固结构化错误保留；冻结的运行版本与当前维护版分别保存，不能混淆指纹。

## 下一步

固定QMAP平台/终态/预算，对照原顺序与可交换CZ重排，再跑完整落点/路由。调度层已验证1000例20→5、5000例30→25，但没有编译该变体，不能宣称物理时间已下降。真正5000级配对、10图重复与连续路径验收仍OPEN。

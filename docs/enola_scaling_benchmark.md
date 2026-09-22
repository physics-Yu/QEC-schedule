# Enola Figure 2 风格的大规模原生实验

本轮将引用任务的公开三正则图 CZ 子电路扩展到 30、100、300、1000、2000、5000 原子，每规模 graph0。目标是逐级可行性与瓶颈实验，尚非论文每规模10图的完整统计复现，也不把5000原子的GHZ链当作同类负载。

## 对比合同

- 输入来自 UCLA-VAST/Enola `graphs.json`，每个规模均为3正则、无重复边、门数3n/2；两方法保留相同门集合。仅比较可交换2Q子电路，没有悄悄声称执行完整QAOA的1Q、参数化演化或测量。
- Enola 使用原作者动态SA、sortIS+window1000、紧凑codegen；原生源码不修改。平台边长采用本次声明的 `max(16,ceil(sqrt(n))+4)`，不是论文已公布的精确资源公式。其最终原子在SLM、AOD空载。
- QMAP 使用已有3.5.0原生C++、strict、IDS trials4/queue100及作者固定square平台。340对EZ落点、90%填充上限即每层306个CZ；100×100 AOD；完整结束回到SZ。继续保留作者原始输入顺序调度。
- 两软件栈的平台、曝光、资源和终态不同，主图不代表同硬件上的纯算法排名。
- 单个方法独立进程，顺序运行；每例300秒整进程墙钟和3GiB进程树预算。源码、输入、指令、资源采样及失败保留；原生计时与含导入/序列化的进程墙钟分开。

## Figure 2 评分

`−ln F = −G ln(.995) − Nspectator ln(.9975) − Ntransfer ln(.999) − Σq ln(1−Tidle(q)/1500000)`，时间单位μs。

Enola按全局Rydberg曝光，QMAP按每次脉冲真实EZ居民曝光；装卸按原子次数，非指令数。门后尾部运输纳入总时间。Enola保留原作者指令时长；QMAP按原作者Evaluator的jerk运动公式及平台15μs装卸、0.36μs CZ计时，并逐例核对原生重排时间一致。

与引用任务旧30/40/50原子的本地Executor物理时间曲线分开：本轮未进行本地Env、连续原子避碰或空trap扫掠验收。QMAP额外进行实际CZ位置/配对与终态点检查；Enola只审计紧凑指令声明的门与holder账本。模型保真度不是实验测量。

任一原子 `Tidle≥T2` 时评分域失效，显示N/A，不能截断成0。有效logF极负导致exp下溢时仍保留负对数。损失图只使用同graph ID双方完整且模型有效的实例；失败不补零。一图/规模不产生样本标准差或置信区间。

## 可复建入口

```powershell
C:/python312/python.exe examples/benchmark_enola_scaling.py --methods qmap --sizes 30 100 300 1000 2000 5000 --graph-ids 0 --timeout 300
C:/python312/python.exe examples/benchmark_enola_scaling.py --methods enola --sizes 30 100 300 1000 2000 5000 --graph-ids 0 --timeout 300
C:/python312/python.exe tools/render_enola_scaling.py --root artifacts/enola-scaling-20260922
```

依赖现有QMAP隔离venv及Enola `.venv-research`。同目录保留已存在结果、不覆盖失败；源码指纹不同会拒绝混入，重试请选新输出目录。可用 `--source` 改Enola位置。

论文：[Enola](https://arxiv.org/html/2405.15095v2)；公开源码：[UCLA-VAST/Enola](https://github.com/UCLA-VAST/Enola)。Figure2是误差分解，编译扩展性是Figure9。本实验未重跑OLSQ-DPQA，不声称重现论文两原始方法的柱高。

## 本轮结果

首轮12次尝试全部结束：8次完整、4次超时，完整配对到1000原子。2000/5000双方都未在300秒整进程预算内返回完整程序；不是无解证明，也不是5000级完整复现成功。

| 原子数 / CZ数 | Enola原生编译 s | QMAP原生编译 s | CZ脉冲 E / Q | 模型执行 ms E / Q |
|---|---:|---:|---:|---:|
| 30 / 45 | 111.880 | 0.138 | 4 / 9 | 11.825 / 14.423 |
| 100 / 150 | 118.898 | 0.869 | 4 / 13 | 36.873 / 44.042 |
| 300 / 450 | 140.063 | 7.567 | 4 / 16 | 119.344 / 145.101 |
| 1000 / 1500 | 206.926 | 141.601 | 4 / 20 | 412.174 / 563.518 |
| 2000 / 3000 | 300s预算超时 | 300s预算超时 | N/A | N/A |
| 5000 / 7500 | 300s预算超时 | 300s预算超时 | N/A | N/A |

正式产物 `artifacts/enola-scaling-20260922/`，报告入口 <http://127.0.0.1:63841/>；`index.html` 嵌入图表可离线阅读，PNG/SVG/PDF与CSV可导出。独立校准在 `artifacts/enola-scaling-worker-validation/`，不混入正式计时。

四个超时都没有完整native程序，均未触发3GiB内存限制。Enola 2000在第4阶段编译期间停止；5000初始SA耗时56.274s，此后进入第2阶段，最后日志为该阶段SA成本，尚未返回完整路由/代码。QMAP大例没有返回分阶段计时，不能把邻近成功案例的profile当作超时案例的确切调用栈。

## 已经定位的差异

1. QMAP 1000例的141.601s中，落点搜索141.466s，路由0.075s。Enola 1000例的206.926s中，初态+动态放置186.245s、路由16.767s、代码生成3.905s。两边的主要开销都不是HTML，也不能只因后者用了快速路由就推断全编译很快。
2. 同一1000例的装卸原子次数为5362 / 11388；模型 `−ln F` 为336.595 / 489.819，主要分量为退相干。不同曝光/硬件/终态下的这些差异不等于纯算法收益；不放大极小F的比值作为实验优势。
3. QMAP的ASAP保留输入的逐原子顺序，Enola在本CZ子电路上使用边着色。独立重算保留全部CZ集合后，在QMAP同样306对容量下，30/100/300/1000/2000/5000的门层可由9/13/16/20/24/30变为4/4/4/5/10/25。已完成的四例实际脉冲数与原顺序ASAP精确一致。这里只验证调度，**重排后的完整落点/路由与保真度尚未运行**。

调度核查入口：

```powershell
& 'C:/Users/86136/Documents/ChatGPT/项目/research/Enola/.venv-research/Scripts/python.exe' tools/analyze_enola_scaling_schedule.py --root artifacts/enola-scaling-20260922 --source 'C:/Users/86136/Documents/ChatGPT/项目/research/Enola'
C:/python312/python.exe tools/audit_enola_scaling.py artifacts/enola-scaling-20260922
```

下一项有价值的受控实验是：在同一QMAP平台、同一终态和预算下，对照原顺序与已证明可交换的CZ块重排，再测完整编译。这能分离前端调度与IDS落点的影响；一般电路不能跨非交换1Q门套用本图的全局重排。

## 验证与版本记录

- 8项worker/统计报告测试通过；结构化异常保留负例通过。
- 12份产物公开输入精确一致；8份完整程序门/装卸/模型算术审计通过；4份超时保留日志且没有完整native指令。`suite-audit.json` 保存检查结果。
- 30原子紧凑Enola程序与既存full-state程序逐条一致，重新执行原作者Simulator，各分量一致。校准耗时142.082s仅作校准记录；正式表使用另一次完整测量111.880s。
- 所有原生算法在运行期间保持固定。正式Enola启动前，仅修复尚未用于正式编译的辅助worker校准元数据/浮点下溢标记；旧版本与`manifest.qmap-phase.json`保留，`source_revisions`解释该变更。
- 实验结束后加固父进程保存子进程结构化异常，并用重复边无效输入验证；不改变已完成实验的原生算法或数据。实际执行版本保存在`sources/qec/`，当前脚本与旧目录指纹不同时须用新输出目录。
- 三组PNG静态图已检查，HTTP及本地下载链接核验；没有本轮本地Env/连续路径或动画GUI验收。

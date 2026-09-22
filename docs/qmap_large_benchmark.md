# 5,000 原子 IDS 原生编译实验

相同规模的公开三正则图、Enola/QMAP 原生误差与耗时对照另见 [Figure 2 风格扩展实验](enola_scaling_benchmark.md)。GHZ链成功不替代该负载。

2026-09-22。用户要求实际尝试超级大电路。两次实验顺序执行，使用原 QMAP 3.5.0 C++ 内核、作者平台及 strict 路由；没有修改当前工作台或放宽本地物理规则。

**结果：5,000 比特 GHZ 链编译成功；5,000 比特高并行 graph-state 在 900 秒预算内未完成。不能用前者替代后者，也不能把超时解释为不存在合法解。**

## 原生指令可视化（2026-09-22补充）

页面：`artifacts/qmap-native/large-20260922/ghz-chain5000/native-inspector.html`。开发机入口：`http://127.0.0.1:61286/ghz-chain5000/native-inspector.html`。页面数据内嵌，也可直接打开HTML；链接的QASM、NAViz、审计与失败文件需保留相邻目录。

保留格点、SZ/EZ区域和原子承载配色；支持1–32×、逐指令、起终点、全景/EZ/原子聚焦、CZ层跳转与全部14998门的分页定位和局部线路图。每个线路门关联原生指令及源码行；5000原子使用差量操作和每512指令的内存检查点，避免生成5000×78433个完整状态。

这是独立的原生程序诊断视图，明确不产生或伪装 `VisualRecorder`/Env执行记录。横轴是指令进度，1×=100指令/s；可关闭的直线插值仅为源/目标端点间的展示，不是验证后的实际连续轨迹。原生格式缺少完整空AOD交点及SLM开关，因此不凭空补出这些状态。图态超时只显示失败记录，不提供成功动画。

生成及状态检查：

```powershell
C:/python312/python.exe examples/export_qmap_native_view.py artifacts/qmap-native/large-20260922/ghz-chain5000
node tests/qmap_native_inspector.cjs artifacts/qmap-native/large-20260922/ghz-chain5000
```

28处正反向跳转对照顺序读取的原子坐标与holder，终点14998门/4999CZ/零AOD载荷、中间CZ2500及最后线路门定位通过。真实浏览器验收记录见后续日志。

## 输入、平台与计时

本机 Windows，Intel Core i7-10510U（4核8线程），约16 GB内存。平台来自 `third_party/qmap/square_architecture.json`：SZ 73×101、4 μm 间距；EZ 10×34 对、对内2 μm；AOD 100×100。90%填充上限下最多306对CZ一层。这不是原小工作台的AOD容量或5 μm单比特光平台。

原配置：IDS、window/min16/ratio1/share0.8、deepening0.01/value0、lookahead0.4、reuse5、trials4、queue100、strict。两个输入的原子数均为5000，但电路结构完全不同。

| 项目 | graph-state | GHZ 链 |
|---|---:|---:|
| H / CZ 数量 | 5000 / 5000 | 9999 / 4999 |
| 总门数 | 10000 | 14998 |
| 原生编译时间 | 未返回 | 9.277799 s |
| 原生接口调用时间 | 未返回 | 9.643874 s |
| 整个工作进程墙钟 | 900.467 s，超时终止 | 14.215749 s |
| 输出 CZ 层数 / 最大并行 | 未生成，不能填写论文值 | 4999 / 1 |
| 工作集峰值 | 约0.99 GiB | 约2.95 GiB |
| 采样 private bytes 峰值 | 约1.24 GiB | 约2.17 GiB |
| 输出指令与独立门级审计 | 未生成 | 通过 |

GHZ 输入为 `H(0)` 后逐个执行 `CNOT(i-1, i)`，每个CNOT展开成目标位 `H–CZ–H`。这是5000个物理比特的理想GHZ制备线路，不是surface-code编码GHZ，也不包含纠错、测量或噪声。

GHZ 的放置计时8.303093 s，运输分组0.151404 s。作者模型的重排总时间为4.912518 s，是输出电路的运输成本，不能与编译墙钟或本地Env执行时间混用。原生程序含12687次load、12687次store、38061条move；编译成功不表示搬运成本已经最优。

graph-state 来自固定版本 MQT Bench 和作者前处理，实际编译输入是保存的 `input.qasm`。没有原生搜索展开计数或逐层完成日志；只知道它进入原生编译后一直计算，不能声称超时前完成了多少层。

论文表1对graphstate5000报告647.7 s、18层、最大306 CZ一层，实验机器为Apple M3。这里没有完成该行的本机复现；硬件不同、单次运行且未隔离整个操作系统负载，不能从超时推断论文不实，也不能声称速度复现。

来源：[论文表1与实验设置](https://arxiv.org/html/2512.13790v1#S5.T1)。

## 验收范围

`tools/audit_qmap_hcz.py` 独立读取QASM和NAViz，跟踪原子身份、装载/卸载、移动后的坐标；按每个CZ时刻的EZ成对站点恢复真实伙伴集合。核对全部H/CZ数量与配对，按每比特依赖检查H边界，并仅允许连续CZ块内部的对易重排。终态要求全部原子卸载到SZ站点且无重叠。

5000比特GHZ：4999对CZ精确匹配、9999个H匹配、每比特依赖通过、终态通过。已有60/1000比特graph-state输出也通过；故意修改CZ伙伴、将H移到其CZ之后的负例均被拒绝。

这是门级结构与离散端点验收，**没有运行5000原子的本地Env、连续扫掠碰撞检查、量子态数值仿真或可视化回放**。原生NAViz文件可供后续物理适配，不能当成本地物理已通过。

## 复现与文件

```powershell
C:/python312/python.exe examples/benchmark_qmap_large.py --qubits 5000 --timeout 900 --output artifacts/qmap-native/large-repeat/graphstate5000
C:/python312/python.exe examples/benchmark_qmap_large.py --family ghz-chain --qubits 5000 --timeout 600 --output artifacts/qmap-native/large-repeat/ghz-chain5000
C:/python312/python.exe tools/audit_qmap_hcz.py artifacts/qmap-native/large-repeat/ghz-chain5000
```

输出目录必须不存在，避免覆盖以前的失败。主Python需要psutil，原生worker使用已固定的独立虚拟环境。监控以1 s间隔采样，限制进程树工作集/private bytes及系统剩余内存，正常情况下不并发运行两个编译器。

此次产物：`artifacts/qmap-native/large-20260922/`。各案例保存request、QASM、architecture、summary、worker.log和资源样本；成功案例还保存native.json、program.naviz、audit.json和逐层CZ伙伴清单。

首次监控只读到了Windows虚拟环境启动器，发现后对实际子进程单独监控，使用OS保留的工作集峰值补齐早期峰值。graph-state的原启动器摘要保存在 `summary-launcher.json`，修正摘要及 `actual-worker-memory.*` 均保留；private峰值仅代表附加监控之后的采样。当前脚本已改为监控整个进程树。GHZ峰值是进程树各进程OS工作集高水位之和，未宣称精确同时峰值。

结论限于这两个实例：总原子数和总门数不足以预测编译时间，层内放置与运输兼容性搜索的规模需要单独考察。下一步可以固定输入记录每层搜索节点、候选数量和耗时，再决定是否调整搜索窗口/预算；本轮未修改搜索参数或算法。

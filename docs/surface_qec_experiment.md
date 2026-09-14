# 已执行的两个逻辑比特 GHZ 纠错实验

日期：2026-09-12。此轮按用户要求在既有可编辑线路工作台中接入真正的辅助原子稳定子抽取、投影测量、复位与测量结果驱动的纠正。运行的是物理操作模拟器，不是实验室硬件。

## 交付入口

- 可编辑完整结果：http://127.0.0.1:8781/?job=55831b7d3be24c56ada3cd4958460db2
- 新草稿模板：http://127.0.0.1:8781/?example=surface-qec-ghz2
- 完整离线回放及输入：`artifacts/surface-qec-ghz2/browser/index.html`、`input.json`。
- 量子及测量记录：同目录 `qec_result.json`、`verification.json`、`browser-acceptance.json`。

本机服务 PID28100、输出 `artifacts/workbench-surface-qec`；服务重启后内存 job 链接需要重新编译，离线产物与输入不依赖 job 存活。旧8769服务和旧36data实验保持。

## 实际执行内容与结果

两个二维 rotated [[9,1,3]] patch，18数据＋16辅助原子。数据间距10 μm，稳定子辅助位于相应格面的中心和边界；单台AOD为7×14=98交点，含非均匀列间隔，所有活动空交点也参与物理校验。门表经过可证明的HH消去、显式依赖传递约简，再通过真实编辑器加入 `Y(Q000)`，seed=7。

执行链为：测量制备 |+>_L|0>_L → 九对横向物理 CNOT 构成逻辑 CNOT → Y(Q000)故障注入 → 全部X/Z稳定子提取 → 真实测量位驱动Z(Q000)、X(Q000) → 恢复初始SLM布局。辅助原子每次在MZ测量和复位后返回EZ，没有隐藏瞬移或逻辑测试执行器捷径。

| 已执行项目 | 结果 |
| --- | --- |
| 输入门／控制槽 | 481/481，逐个效果恰好一次 |
| 单比特实际光脉冲 | 127 H＋1 Y故障＋3实际条件纠正=131 |
| 条件纠正槽 | 184，其中181不发光；制备Z(Q011)，最终Z(Q000)及X(Q000) |
| CZ效果 | 105个，33次真实pulse，批量分布2×18、4×12、6×2、9×1 |
| 稳定子读出 | 两轮各16位，共32位；8批、每批4原子 |
| 复位 | 32次目标复位，共8批 |
| 第二轮非零syndrome | final_X0_0=1、final_Z0_2=1，其余14位为0 |
| 纠正前逻辑XX/ZZ | -1 / -1，来自物理重放中的中间量子态 |
| 纠正后逻辑XX/ZZ | +1 / +1，且16个码稳定子全部+1 |
| 完整物理时间 | 22055.9 μs，包括清理归还；逻辑完成21665.9 μs |
| 读出／复位设备忙时 | 4000 / 800 μs |
| 装载／卸载 | 51 / 51轮；953个操作，93个plan，2092个提交事件 |
| 单次编译墙钟 | 189.438 s，本机观测，不是统计性能保证 |

测量500 μs、复位100 μs为本次模拟假设；单比特光仍固定1 μs，CZ默认0.3 μs。条件false仍占固定控制时隙，明确不计Raman光照。AOD资源忙时包含测量/复位锁定，不应解释为纯移动时间。

## 验收证据

1. 精确量子测试涵盖18数据×3种Pauli=54种单数据故障与12个随机初始化seed，均恢复码空间和逻辑GHZ关联；含删除必要check/恢复步骤的失败对照，以及小规模独立稠密振幅比较。
2. 完整正式输入经真实headless Edge编辑、添加H再撤销、点击编译。测量中点不提前展示结果，完成后显示实际bit；false条件控制槽无激光。两种32×播放均到22055.9 μs终态，无页面错误：physical28.766s、keyframe26.765s。正式运行期间源码未变化。
3. 不调用compiler，重放保存的93个plan并独立验证全部物理事件。量子态、RNG、测量结果、DAG、placement和整个checkpoint与正式结果逐字一致。checkpoint恢复通过；所有481效果恰好一次；34原子归还SLM且已复位辅助的measured标志清除。重放中间态证明XX/ZZ从-1变为+1。

重现命令：

```powershell
C:/python312/python.exe examples/circuit_workbench.py --port 8781 --output artifacts/workbench-surface-qec
C:/python312/python.exe examples/run_surface_qec.py --fault Y --qubit Q000 --seed 7 --output artifacts/surface-qec-reproduction
C:/python312/python.exe examples/verify_surface_qec.py artifacts/surface-qec-ghz2/browser
```

正式浏览器输入保留实际编辑器依赖（1093个显式边），与直接生成带fault模板881边不同，均保留必需顺序。正式验收以保存的input.json为准。代码优化包含依赖传递约简、DAG运行节点复用、直接不可变结构比较及等价序列化快路径，不放松任何物理校验。首轮未优化性能探针主动停止，不计作完成成绩。

## 边界与后续

这是理想Clifford门、理想投影读出/reset下，syndrome前单数据Pauli故障恢复；不是完整电路噪声容错、重复时域解码或实验保真度证明。四逻辑版本尚未按本协议执行，旧36data GHZ的9.23%时间改善不能套到本实验。

编辑器中的实际门表直接驱动编译；任意修改不保证仍是GHZ或完整稳定子协议，页面分别给出编译状态、协议完整性和量子目标。QEC模式支持H/X/Y/Z/CZ/MEASURE/RESET，T明确拒绝；普通模式保留T。

当前QEC runner是按几何优先大批、首次精确合法候选的构造基线，不承诺全局最优。仍有51轮装卸；下一步可评估附带捕获辅助原子后集中读出、减少往返、连续纠错轮和带测量噪声的时域decoder，再扩展四逻辑GHZ。此轮没有放宽CZ作用对、5 μm单比特邻距、AOD Cartesian捕获闭包或半格正交路径约束。

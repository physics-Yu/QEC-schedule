# 2026-09-12 · 电路级优化与稳定子测量范围核验

状态：COMPLETED（只读核验和记录；没有开始完整QEC实现，没有改变当前工作台电路）。

用户质疑电路未优化、并行不足、缺少stabilizer辅助原子，以及物理电路是否正确。

## 核验结论

- `experiments/surface_ghz.py`确实只生成36数据原子的无测量理想酉编码，再做三个逻辑transversal CNOT；135H+59CZ固定194门，比较策略未改量子电路。8个local稳定子/patch只在软件符号验证中出现，不是8次实际测量或8辅助原子。
- `examples/audit_surface_input.py`按每条qubit线上实际依赖消去相邻HH，发现28对、56个H可消去，194→138门（79H+59CZ）；简化前后signed GHZ检查均真。H²=I和不同qubit操作可交换保证该局部变换等价。没有重新物理编译，不能宣称新的μs成绩。
- 真实24次CZ脉冲为14×单门、7×两门、1×四门、1×九门、1×十八门。编码32CZ用了22批，最终逻辑互连27CZ仅2批；36原子在每颗只能参与一个2q门时最多18对，所以18已达这部分的并行上限，问题集中在编码电路和运输组织。
- 结论必须分层：当前理想编码目标态正确；选定运动和pulse通过项目硬件代理验证；但不等于已实现包含辅助原子、稳定子测量、读出、reset/Pauli frame的surface-code过程，也不能证明容错或真机保真度。

## 一手核对

- [Krinner等作者论文](https://arxiv.org/pdf/2112.03708)：标准rotated d3为9data+8测量辅助；四块独立完整X/Z syndrome布局可选36+32=68原子。辅助可复用，所以68不是所有协议必需的唯一计数。具体CZ实现的X/Z时隙和hook次序须按原电路核验，不能把抽象四CNOT层直接称四段任意并行CZ。
- [Bluvstein等中性原子Methods](https://arxiv.org/html/2312.03982v1)，Surface code and its implementation：先data全|+>再用辅助测Z稳定子，或data全|0>再测X稳定子，四个纠缠脉冲；d3单次基态投影只需四个对应类型辅助/patch，一次性制备四块独立辅助可52原子。该方案仍需要辅助测量和测量结果处理，区别于当前36data无测量构造。论文4logical GHZ部分用color code，不能混为surface GHZ复现。
- [Chen等Fig1(d)](https://arxiv.org/html/2412.01391v1)：抽象surface stabilizer extraction可安排四层CNOT，合法次序不能任意交换；物理实现仍含基底变换、运动、交接与读出。

## 后续优先级修正

先选择并定义带辅助原子的surface-code制备/稳定子提取线路，明确测量结果、Pauli frame和是否多轮纠错；核验logical GHZ与故障传播。之后先做电路级等价化简与层编排，再对**同一个完整含辅助线路**比较运动编译。不能只给旧36data动画补画32个辅助点或继续以9.23%作为完整QEC成绩。

证据：`artifacts/surface-2d/circuit-audit.json`，复现`C:/python312/python.exe examples/audit_surface_input.py`。当前8769用户实例未修改；本轮只做核验，未执行新的物理编译或测量后端。

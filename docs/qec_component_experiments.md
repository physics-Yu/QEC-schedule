# QEC 组件实验可视化交付

**用户已拒绝初版交付（2026-10-03）。** 初版只验证参考数学结果与界面交互，不能声称用户要求的 PBC／T 注入 physical circuit 功能完成。复核和缺失链路见 [实现审计](qec_pbc_implementation_audit.md)。修订页把 E1 明确称为 PPR 酉表示、E4 称为理想注入参考；补画资源态输入与经典条件反馈，不把缺失功能画成成功。原报告保存在 `artifacts/qec-component-experiments-2026-10-03-before-user-review` 作为被拒绝版本，不能作验收证据。

2026-10-03，生成器 `examples/run_qec_component_experiments.py`；输出 `artifacts/qec-component-experiments-2026-10-03/index.html`。页面内嵌完整结果与脚本，可离线查看六个实验；导出数据和阶段 A 链接依赖相邻文件。

| 实验 | 输入与对照 | 本轮证据 |
|---|---|---|
| E1 exact signed Pauli 编译 | 三线 Clifford+T；四种输入态；独立完整矩阵 | 最大误差 1.7772239894833365e-16，显示振幅、相位和概率 |
| E2 canonical 并行与硬件合同 | 三轮12层；reuse/fresh四轮容量；远/近 spectator；矩形捕获 | 最低17/41原子；34容量拒绝fresh；近spectator额外CZ作用对与矩形额外捕获均拒绝 |
| E3 d3 CNOT/H | 九对data transversal、四种逻辑算符、H前后checks | 16稳定子像保持；显示编码朝向变化，非运动或FT验证 |
| E4 T/Tdg injection | 六种gate/input组合，含纠缠reference；两个测量分支 | 分支概率均0.5，修正后态 fidelity 为1；理想资源明确标记 |
| E5 noise/decoder | X/Z memory、三类人工噪声、五个p；每点20k，seed17 | 30点600k shots；Wilson95%；同一raw shot→m2d→MWPM；解码成功与失败样本 |
| E6 N21模幂 | 作者QASM SHA固定；所有1024指数；独立CCX矩阵 | 1024/1024正确；CCX矩阵误差2.2610626239330836e-16；643输入门、2583PPR、3226residual Clifford |

E5 p取0、0.001、0.003、0.005、0.01，各点实际seed记录在JSON/CSV。Stim1.15.0、PyMatching2.3.1。退相干小图使用人工Tphi=1e6μs和move depolarizing rate=1e-7/μs；是裸物理比特模型，不是编码逻辑寿命。统计量是解码后observable失败率，不是完整量子态fidelity。未自动读取真实trace曝光，未模拟loss/leakage/非Pauli过程或工厂。

模幂oracle固定指数寄存器后执行可逆算术，排除输入H制备；不是完整15线酉矩阵验证。Toffoli的8×8矩阵另含相位检查；原始N21线路不包含本轮QFT和完整Shor。

导出 `experiments.json`（含生成器源码SHA）、`noise-scan.csv`、`modexp-truth.csv`、`noise-scan.svg/png/pdf`。阶段 A 真实Executor回放使用相邻 `qec-baseline-2026-10-03/memory-{z,x}-verified/index.html`，不生成替代轨迹。

复现（Python3.12，NumPy/Stim/PyMatching/Matplotlib）：

```powershell
& '.venv-qec-noise-modern/Scripts/python.exe' examples/run_qec_component_experiments.py --qasm artifacts/shor-greedy-2026-09-15/circuits/gidney-factor21.qasm --output artifacts/qec-component-experiments-2026-10-03
& '.venv-qec-noise-modern/Scripts/python.exe' -m http.server 8832 --bind 127.0.0.1 --directory artifacts
```

本轮13项相关测试通过；176模块架构检查无违规；浏览器六面板、态/层/spectator/逻辑算符/两个注入分支/解码失败/PPR分页/指数1023交互通过，390px视口下无横向页面溢出。硬件核和阶段 A 实验文件未修改。本轮未Git提交或推送。

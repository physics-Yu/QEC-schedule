# 2026-09-22 · 独立快速编译与对抗式RL初始placement

- 状态：COMPLETED（首版研究框架与小规模训练验收）；算法优势与物理迁移OPEN。
- 用户目标：基于ZAC→Routing-Aware Placement→IDS/relaxed研究脉络，脱离界面训练循环，以简单AOD约束/冲突图快速评价RL初态。用户明确选择“布局策略与可训练的对手共同学习”。
- 本轮范围：独立严格离散模型、可训练有限场景对手、REINFORCE actor、消融/搜索对照、独立审计；不修改生产env、GUI、已有编译器或作者源码。
- 相关instruction：architecture、planning_rl、research、workflow。

## 完成内容

新增strategies/placement_rl五模块；model/compiler标准库，policy/game可选torch。固定CZ匹配层→有限IDS配对落点→显式停车/复用→冲突图兼容分组→load/move/unload/pulse/终态。支持完整Cartesian闭包、行列容量/最小间距/不交叉和不拆合。独立审计不调用编译器组合法性函数，检查全部门、承载、时间、共同终态。

Actor使用三时间分箱交互图编码和掩码站点pointer。对手读线路和完整mapping，输出五种合法场景的概率；每次精确枚举评价后共同更新，非固定权重伪对抗。双方梯度隔离，greedy基线不依赖当次actor采样。失败2劣于所有成功的有界相对损失。同场景启发式归一化，基线失败则实验停止。

新增experiments/rl_initial_placement、训练/自定义推理CLI、配置、依赖文件、独立产物审计和中文合同文档。训练/验证/测试在运行前冻结，验证选模保留update0。随机和退火/actor搜索同八布局预算；退火不是作者ZAC SA。参考与候选同终态条件。

## 本轮证据

- `.venv-rl-stage-b/Scripts/python.exe -m pytest -q tests/test_placement_rl.py tests/test_environment_boundary.py --basetemp=artifacts/pytest-placement-rl-final`：48项通过（36项新框架＋12项环境边界，5.54s；包括非零性能梯度更新双方网络、最小间距、空交点计时、篡改trace拒绝和训练runner烟测）。
- `python tools/check_architecture.py`：通过，无反向依赖。最终模块数以本轮报告为准。
- 正式先导运行：`examples/train_initial_placement_rl.py --output artifacts/placement-rl/pilot-20260922-attempt2`；两seed×共同学习/uniform共四组完成。256训练episode；7,505次快速编译+审计，36.689s，约204.6次/s（不含网络/IO）。
- `examples/evaluate_initial_placement_rl.py`：加载seed11所选权重，自定义4原子3层，五场景completed，输出custom-four.json。
- `tools/audit_placement_rl.py`：PASS，零错误；产物审计结果见同目录audit.json；冻结30个不重复线路、6个执行源码文件、600/600份完整见证。
- 120个额外随机编译/重放覆盖1/3/4/8/12原子、两个终态和四种分组顺序通过；该组由编译实现agent运行，发生在最小间距新增回归前，不冒充全部最终参数覆盖。

## 结果与解释

共同学习两个seed的测试nominal相对启发式为−0.169%/+2.233%；uniform为−1.928%/+2.233%。均显著区别于“必定优于baseline”的假设。Actor候选池与随机/退火结果详见docs；不依据这批测试调参重选。可训练对手贡献未成立，小规模泛化未成立。

首次pilot目录保留失败：evaluation报告把同名worst_bounded_regret解包两次；修复为嵌套search元数据。同期纠正AOD计时采用整个活动Cartesian网格而非仅载原子最长位移，再用同数据/超参数重跑attempt2。测试首次3失败是fixture未配置目标SLM及tuple篡改写法，保留工具输出，按模型合同修正fixture未放松断言。

## 决策与限制

- 用户本轮明确授权独立快速研究抽象；生产物理硬约束没有改变。
- 单台AOD、合成成对EZ；5us装卸、1usCZ、2sqrt(d_grid)us移动均为示例模型参数。
- 无连续避障/空阱扫掠/空AOD定位/trap开关/量子态/噪声/QEC测量反馈；不得把离散审计称物理重放。
- 默认末态任意合法SZ空AOD；canonical可选。初态制备不计入时间。
- 当前parking贪心、无未来伙伴lookahead；IDS仅为有限搜索启发，非作者等价复现；relaxed未实现，不通过删冲突边冒充。
- Checkpoint是验证选中actor+最终对手，概率仅最终对手诊断；质量验收枚举全bank，与对手概率无关。
- 网络编码只保留三时间分箱及统计，不等于完整序列可辨识。
- 没有per-method搜索墙钟，不宣称RL搜索速度胜过SA。

## 下一步

1. 固定现有测试集，另建训练/验证资料，提高对手可区分场景与预算；补nominal-only及更大独立测试。
2. 引入有实操作展开的原生strict/relaxed compiler oracle，并验证它真正使用给定初态；不先降低物理规则。
3. 把保存布局接入同几何/终态的物理抽查，量化fast/physical排序误差及失败率，再谈物理优化收益。

未提交或推送。未更新长期memory。

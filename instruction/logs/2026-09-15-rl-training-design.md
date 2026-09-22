# 2026-09-15 · RL 框架与训练路线

- 状态：COMPLETED（设计讨论与文档）；RL 实现与训练未开始。
- 用户目标：在测量策略化基础上规划跨电路并行训练，明确学习目标、自由度与课程。
- 本轮读取：agent/handoff、planning_rl、workflow、environment.py、environment_strategy_boundary；主文献 Learning to Dispatch / Invalid Action Masking / PPO。

## 完成内容

新增 [设计](../../docs/rl_training_design.md)：外部 adapter、事件决策、图观测、自回归动作、硬 mask 与启发式截断分离；相同终态物理总时间奖励、失败下界、跨电路独立 rollout；四阶段验收与泛化评估。明确当前完整服务串行/固定归还限制，历史 QEC 耗时仅用于提醒吞吐风险。

## 验证

本轮只改文档；检查新增文档存在、相对链接目标和 diff 空白错误。未运行训练、物理回归或浏览器；8798原产物与运行代码未变。无权重/学习收益声明。

## 下一步

实现设计阶段A的外部决策接口，以小实例验证 random/greedy、奖励望远镜和失败不获利、观察隔离及采样吞吐；随后据实测决定训练配置。无提交推送。

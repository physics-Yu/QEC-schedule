# 原生编译与轻量运行内核迁移

生效日期：2026-10-04。状态：独立内核首阶段已验收；工厂接入与完整 Shor 尚未验收。

用户进一步授权的主目标是迁移内核、获得快速运行能力并去除探索时期的臃肿架构。仅给旧 Executor 增加 trusted 分支或把 QMAP 输出送回旧 ProgramBuilder，不满足这次目标。可采用原生编译器的 EZ 配对布局或 Enola 类指令加显式 measurement 服务；新平台必须版本化，保留原子身份、有限 CZ、旁观者、安全间距及报告完成语义。

## 新主路径

```text
冻结协议 / processor 请求 / 工厂库存与反馈
  → 有完整依赖与测量边界的原生酉块
  → QMAP C++ 排布 / 分层 / 路由
  → LOAD / MOVE / STORE / GATE / CZ / MEASURE / RESET / WAIT 操作流
  → neutral_atom_kernel 唯一提交的紧凑位置、holder、时间、完成索引与报告
  → 增量日志 / 可选观察器 / controller 下一段
```

新 kernel 不导入旧 ENV、策略、实验、QMAP 或 UI。QMAP 位于策略层；协议、inventory、token、carrier、epoch、frame 和接受拒收归控制器。新 kernel 只执行已编译操作，不搜索路线，不预测整份状态，不逐 event 重建 DAG、不复制完整历史、不生成旧 SimulationState。

门和操作保留源 ID。每个 block 绑定起态版本、摘要与原生 provenance。错身份、过期提交、未就绪依赖、重复效果和提前报告仍拒绝。MEASURE 结束才采样并提交声明报告；RESET 不删除历史报告，也不更换载体。checkpoint 保留全局时间、位置和 holder、游标、已完成效果及当前 fragment。

## 两种独立工作

- 日常路径执行原生结果，保留轻量状态与控制门禁；记录可关闭或流式增量写出。
- 离线审核读同一初态和操作流，检查几何、连续运输、全 Cartesian 活动交点、实际 CZ pair-set、SLM 支撑、寻址、MZ 与时长。不得重新选路线。trusted 完成和离线物理资格分别记录。

旧 ENV / ProgramBuilder / SimulationState / 全 trace 审核仅保留作显式兼容或离线对照，不是新生产默认，也不做静默 fallback。旧六个 factory 长跑继续停止。旧物理结果和 Git 历史保持可追溯，不通过删除已有证据进行清理。

## 本阶段

1. 先交付独立轻量 executor、版本化 IR、恢复与声明报告完成门禁。
2. 用实际 QMAP C++ 编译完整 canonical d=3 综合征轮，显式运输到 MZ 读出和 RESET，再续接下一轮。
3. 单独测冷启动、native、lowering、推进、记录/导出、离线审核；比较 recording 开关及恢复终态。
4. 通过小例后，由工厂实施对话用薄 observation/environment 桥接已有 controller，默认 runner 迁入新主路径。完整 S1–S3 另行验收。

原生 NAViz 目前不分配多 AOD；首个资格例明确只用 AOD_0。IR 可带设备 ID，不等于原生双 AOD 已实现。现有 QMAP 编译入口没有 live initial placement，段间必须实际运输衔接并计时，不能覆盖起态。

源码与成果说明见 [迁移说明](../docs/native_kernel_migration.md)，本次日志见 [内核迁移日志](logs/2026-10-04-native-kernel-migration.md)。

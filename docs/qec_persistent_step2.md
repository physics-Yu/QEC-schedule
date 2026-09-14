# 步骤2第一次尝试：保留相同 CZ 原子组

本轮在步骤1旧基线恢复、量子、物理和终态审计通过后，由主任务授权实现。旧 `simulation/qec.py` 不变；新入口是 `simulation/qec_persistent.py::run_qec_persistent`，使用新 `motion/qec_persistent.py::PersistentCohortCompiler`。

## 构造

首次载入一个完整、笛卡尔闭合的移动原子组，按原后端运输并执行 CZ。脉冲后返回捕获时的原始坐标，来源 SLM 保持关闭，原子仍由 AOD 支撑。返回段是普通 MOVE，不声明没有紧邻 OFFLOAD 的 approach 豁免。

候选次序保持旧基线：若当前有保留原子，先构造只读 OFFLOAD 预测态，在该视图上运行旧 first-valid CZ 候选校验。这个预测态的计划从不提交到实时 Executor。旧基线本来选择同一个完整移动原子组时，真实计划绑定当前 loaded 状态，省略新 LOAD；选择其他组、读出或终态时，先提交真实显式 OFFLOAD，再继续基线构造。

整个阵列的几何、活动空交点扫掠、SLM 支撑、碰撞、实际 CZ 对、单比特光5μm间距与 checkpoint 校验均保持。没有修改核心 validator/readout/checkpoint。

## Raman 限制

当前核心给每个 AOD 目标 Raman 操作独占 AOD_0，所以第一版每个光照时隙最多安排一个移动原子上的 Raman；相同类型静态目标仍可加入并行时隙。所有 READY 单比特控制仍在进入下一个 CZ 前执行完。共享稳定 AOD 资源或真实 batch Raman 留给下一步，不在本步骤放宽。

## 首次最小验收

2026-09-12，预先定义两个真实物理测试后只执行一次：

```
C:/python312/python.exe -m pytest tests/test_qec_persistent.py -q --disable-warnings --maxfail=1
```

结果：**2 passed，7.83s**。

- 同初态/终态的两原子 CZ–H–CZ：H 的实际 holder 是 mobile；新策略少1次 LOAD和1次OFFLOAD，物理时间恰少200μs；独立量子预期和基线量子态一致。每个事件 checkpoint 可恢复，并可由 Executor 执行已提交计划后缀。保留计划没有 approach 标记。
- 三原子两次 CZ 需要不同移动原子组：新策略显式释放后更换组，复用次数0，时间及装卸次数与基线一致。

`decision_log` 最后一项 `kind='reuse_summary'` 提供 `retained_count`（新建保留组次数）、`reuse_count`、`flush_count`。每个 CZ 日志还记录 `cohort_reused` 与 `retained_atoms`；release 日志记录原因。

## 正式全输入验收状态

最小验收通过不等于步骤2正式通过。主任务接下来对同一481门输入、同终态与全部测量结果/RESET投影/实际条件分支进行独立公平对比；目标是物理时间小于22055.9μs且LOAD少于51。此文件尚不包含完整运行成绩。

按用户流程：正式阶段/测试出现意外失败立即停止并报告，只有用户批准修改方案后才重试；正常候选几何拒绝及明确预期的负例例外。内部计划不一致、过期状态或runtime mismatch不得归类为普通几何候选拒绝。

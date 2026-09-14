# 4C之前的快照成本分析（未实施）

4B首次编译916槽、256plan，耗时1235.164秒；decisions中准备候选/plan的compile_wall_time_s合计709.602秒，其余包含执行验证、观察、保存与最终检查，不能全部归因于路径搜索。末checkpoint132.9MB，trace106.7MB。尚未profile，不能宣称某一函数占全部时间或预报加速倍数。

明确源码事实：motion/compiler.py fingerprint调用sha256(state.snapshot().encode(...))；state.snapshot将trace.records再次编码为JSON字符串数组。Trace.records为只追加的tuple[str]，每条record自身已经是规范JSON，但外层字符串仍必须正确转义。既有snapshot内容和SHA256都不能更换成简化摘要。

优先工程方案：在独立模块缓存不可变trace记录的JSON字符串字面量，按明确内存/活跃分支限制管理；追加只编码新增项，分叉/历史替换/恢复必须确认完整前缀或重新编码。snapshot按现有顶层键排序结构化拼接，trace仍是字符串数组，不能直接插为对象，也不能哨兵replace。保留原canonical_json作为独立参考实现；完整规范字节仍参与SHA256，不删字段、不跳过校验。

不建议简单缓存(id(state),version)：Executor.schedule可在相同version替换event_queue；step原地逐字段提交，外部CompiledPlan嵌套列表也未统一深冻结。这样的身份缓存可能漏掉真实状态变化。

实施前需在4B完整重放及UI验收之后解除源码冻结。检查包括旧schema19与新噪声checkpoint逐字/哈希一致，中文/引号/反斜杠/换行、追加/分叉/替换/恢复、同version schedule及RNG/测量/开关变化。基准分别量化冷/暖转义、拼接、UTF8、hash，不用减少验证换速度。当前仅只读设计，尚未写缓存、未做性能实验。

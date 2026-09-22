# 2026-09-22 ZAC 原生 SA 初始化与四组完整结果

用户要求补齐初始化优化并完整展示。在原ZAC算法→本地Executor边界内接入，不改物理、运输策略或旧benchmark。

## 实现与合同

- frontend的SA模式不注入given mapping，关闭trivial placement，直接调用作者未修改SAPlacer；保留seed=0、l2=False、默认退火参数。保存SA源码哈希、实际mapping、改变原子数、原/选定代理及初态求解秒数；额外代理核算保存/恢复RNG。
- run_one按作者首映射创建真实初态；fixed/SA × reuse关/开四组恢复固定编号顺序的同一绝对终态，包括holder、SLM masks、AOD axes/masks，保存target及SHA256。初次制备初态的成本不计入episode，共同终态实际成本计入。
- 新zac_initial runner/CLI/report：独立进程、预算、失败保留、CSV、五种比较、同尺度布局、完整CZ/驻留/共用viewer。失败前缀不算比值；原编辑器支持手动两组/四组编译。失败回放顶部警告，默认优先打开完整SA记录。
- 新独立产物审计；render工具支持新schema。189份执行相关源码按运行前哈希保存到source-snapshot；后续展示更新另存presentation及render.json，不改变物理记录。

## 执行结果

`artifacts/zac-reuse/benchmark-initial-20260922`：16/32原子、8层、蝶形和random seed20260921，4进程、本地600s、作者前端120s、单份硬上限1500s。整批1171.89s，14/16完整，2失败，无超时。完整表/命令/口径见[结果文档](../../docs/zac_initial_placement.md)。

SA在reuse开启时的增量：蝶形16 −0.92%、随机16 +1.05%、蝶形32 +6.69%，随机32不可比较。关闭reuse时随机32减少5.01%。代理均改善，物理收益不普遍为正；共同终态与路径成本影响结论。

两条失败：butterfly32 fixed/off完成128门后Q016末尾归还耗尽候选，85778.265μs为前缀；random32 SA/on完成48门，在第4层prepare为Q012寻路时耗尽44个有限候选，33669.830μs为前缀。候选含AOD_OUTSIDE_WORLD；未扩边界/放宽约束，不声明无解。

## 验证

- 26项原ZAC/benchmark测试及2项新增测试通过；新增真实8原子SA案例核对实际初态不同、完整CZ效果、独立重放及同一终态。207模块边界零违规。
- GitHub固定版本与Zenodo AE的saplacer.py哈希相同；执行源快照匹配原189份哈希。
- 大批audit通过，覆盖输入、实际初态、两次SA映射一致、同CZ/平台、独立ASAP深度、trace恰好一次、阶段时间、驻留、共同完整终态及成功项比值；不将两份失败改成成功。
- Node：16录制、123真实CZ pulse、616驻留区间；两种模式32×、pair距离、静态holder、终点和源数据不变通过。
- 真实GUI：四组表、16/32布局；16蝶形SA/on首层8对CZ定位、两模式32×自动到33490.019μs且64/64；32随机SA/off首层16对CZ定位6726.037μs、终点122360.202μs且128/128；切换SA/on明确48/128前缀。
- 原编辑器完整导入16蝶形并自动选四组；随后手动选四原子换伙伴/四组/60s预算，job `66b3f5b347bc44ce843550415f0164c5` 的4/4执行及独立产物审计通过，GUI收到完成反馈。

## 交付与边界

52813 `/benchmark-initial-20260922/index.html`；当前用户32随机子页`/benchmark-initial-20260922/random-n32-d8-s20260921/index.html`。旧49901保留。未提交推送。64/128的SA未测；无完整应用AE、混合1Q、保真度、普遍加速结论。下一步可单独研究SA代理与本地有界AOD路径/共同终态成本的错配，保留本轮原作者对照。

最终重载服务：52813 PID22440、49901 PID15128（本次快照），独立后台进程；首页API、总表、当前32随机页、CSV和audit均HTTP200。189份执行源快照与原哈希一致，计算相关源码未漂移；展示模块的后续更改由render.json单独核对。

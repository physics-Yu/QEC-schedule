# 候选、调度策略与未来 RL 接口

状态：2026-09-11。M3 单 trap 持久任务、并发和恢复已实现；M4 greedy 首版已接入可编辑工作台，包含局部候选成本和连续 Raman 填窗。critical-path、有限 lookahead、在线候选注入和 RL 尚未实现。当前 API/预算/非抢占边界见 [M4 greedy](../docs/milestone4_greedy.md)，正式目标接口见 [compiler_contract](compiler_contract.md)。

## 1. 调度与编译分工

scheduler 从逻辑 frontier 与持续平台状态出发，提出任务目标、可选终态域、允许资源和时间约束。compiler 返回一个或少量局部合法候选及操作依赖、成本、占用和预计终态。scheduler 选择候选并安排开始时间；独立 validator 验证，Executor 唯一提交。

选择是否保留、什么时候归还、先准备哪颗原子属于全局调度；给定目标后如何装卸/走路径属于局部编译。站点可由 scheduler 指定，也可作为允许域交由 compiler 生成候选。文献中的 compiler 常包括这两层，本项目命名不否认这种用法。

## 2. 候选不必完成一个门

候选可只运输、停车、关闭空阱重定位或清理，也可包含门效果。prepare/pulse/cleanup 可独立成任务，通过操作依赖与前后状态衔接；CZ 本身仍是一个完整 pulse，门效果只完成一次。basic 将一次往返打包是策略便利，不是接口约束。

合法 EZ SLM、loaded、空 AOD 异位状态均可继续。RETURN_ONLY、REPOSITION_AND_KEEP、OFFLOAD_TO_NEW_SITE 表示不同目标；目标必须明确 holder/位置/区域及允许分配规则，不推断永久 home。legacy ExecuteGateBatchIntent 仍要求单 CZ；M3 TaskIntent 支持上述独立运输与目标，scheduled program 支持一个 AOD 服务和多个 Raman，M4 在该接口选择候选。

## 3. 搜索预算、缓存与失败

避免 ready 全子集 × 捕获集 × 站点 × 路线 × 终态的全量笛卡尔积。配置 ready、目标域、路线数、候选数及时间/节点预算，稳定排序并记录截断。可保留成本相近但终态或占用不同的少量候选，供调度看未来。

缓存依赖平台能力、相关起态/启用/轨迹、预约及任务约束；不能只按 gate IDs 缓存。当前全快照 fingerprint 是串行防陈旧方案，并发必须设计相关前置条件和预约版本校验，不能直接删除保护。

搜索内部候选拒绝允许继续；候选耗尽、已选计划校验失败或无可推进事件时，结构化报错并终止运行，保留 scene/trace/checkpoint/输入/搜索范围。当前 stalled 是诊断底座，尚不等于统一的可见 fatal 出口。若以后增加安全 baseline 回退，须显式配置和报告，不静默掩盖失败。

## 4. 决策时机与优化

决策时机是门完成、相关资源释放、准备完成等有意义的事件边界；不以每个 CZ 的完整归还作为全局屏障。一个全局时钟；与其他运输不冲突的稳定 SLM 1Q 可开始。并发时预约按操作和持续占位区间，安全性仍需整段轨迹检查。

首要最小化全部门和声明终止条件完成的总时间。局部 compiler 可最小化固定任务的移动时间/距离；scheduler 需要 lookahead 判断额外装卸、占位和复用对全局的影响。不能把“每门装卸次数固定”推广到所有策略。

M4 比较 basic、greedy、critical-path 与有限 lookahead。特征包括依赖深度、next use、可用伙伴、真实重载成本、EZ/轴占用、附带运输及终态。复用不是必然更优；留在 EZ SLM 不等于 KEEP_LOADED。[ZAC](https://arxiv.org/html/2411.11784v3)

## 5. Batch 与能力

M3 已验收一个局域 1Q 通道与运输重叠，M4 greedy 继续填充连续时隙，SLM 资格/区域/时长与 Raman 容量由平台声明。M5 才扩展同时 CZ batch：READY、无共享 Q 仅是必要条件，还要共同 placement、全作用对、启用模式及路线/资源可行。[Atomique](https://arxiv.org/html/2311.15123v3)

不同 AOD 数量、是否变距、是否允许 AOD-held 1Q 是独立能力，不能改变策略名称时隐含增加硬件能力。

## 6. RL 目标（M6，待实现）

动作优先采用有限合法候选 index 和明确的时间/等待选项；等待只能指向有意义的未来事件，不允许空事件无限 WAIT。mask 与候选表一致，空列表是失败/完成判断的输入，不是随便选 0。

Observation 来自当前状态、资源和允许的 circuit lookahead；包含目标/终态、成本、依赖与 mask，不能偷看未发生随机结果。step 执行到明确定义的决策事件，返回状态和完成/失败/截断原因。

与主目标一致的首版奖励为负的实际时间增量，累计覆盖相同 episode 起点至包括清理的程序完成；失败/预算截断不得因耗时短反而优于合法完成。距离、门数、装卸先作为报告特征；引入 shaping 时必须说明是否改变目标及避免重复累计奖励。不要给 KEEP/RETURN 标签固定奖励，不推断少移动即高 fidelity。

## 7. 公平比较与条件保证

相同 circuit、初始 placement/开关、硬件参数、搜索预算约定与终态条件下比较。报告 wall/逻辑完成、真实路程、装卸、每资源区间并集利用率、编译成本、可完成率和失败原因；类别时间可重叠，不相加冒充 wall。

先给出可验证的平台布局族和串行恢复构造，再对该族内任意有限支持电路声明可完成。预算耗尽不是全局无解证明；无噪声/测量结果模型则不报告 fidelity 或 logical error rate。详细验收见 [validation](validation.md)。

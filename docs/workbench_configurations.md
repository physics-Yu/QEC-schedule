# 线路、平台与编译配置

2026-09-13：工作台整理后的维护合同。入口是线路编辑与回放，配置管理为独立页面；所有执行仍由物理 compiler → 独立校验 → Executor → VisualRecorder → 共用 viewer 产生。

## 三层职责

| 层 | 内容 | 保存方式 |
| --- | --- | --- |
| 线路方案 | 门列表、原子数、layout、seed、patch 原点、线路协议及故障门 | 线路区导入/导出完整 JSON，包含本次使用的平台与编译配置快照 |
| 平台配置 | AOD 行列、两组偏移、EZ 四邻停驻保护、兼容 EZ 平台字段 | 命名副本存本机浏览器，也可单独导入/导出 JSON |
| 编译配置 | 推荐/基线调度、时限与高级搜索预算 | 单独命名、保存、导入、导出，可跨线路应用 |

AOD 容量只读显示 rows × columns，不再有第二个可编辑总容量。旧 `aod_traps` API 输入仍支持；新 UI 草稿转为显式行列。偏移从 0 开始递增，支持非均匀间距，活动 trap 仍是开启行 × 开启列的全部交点。

模板带配套初态与平台，载入动作明确替换线路方案，但**保留当前编译配置及其预算**。随机载入只替换门列表。改变调度不载入模板、不改原子数/layout、不改 gates 或协议。独立配置载入先校验，失败保留原草稿；成功也保留门数组的原始顺序。完整方案导入恢复其显式编译配置。

本机配置保存键为 `atom-studio.configurations.platform`、`atom-studio.configurations.compilation`，同名副本不覆盖；不同端口的浏览器存储独立，可用 JSON 迁移。草稿仍需手动导出保存，配置库不代表草稿自动保存。

## 编译接口

```json
{
  "circuit_profile": "physical",
  "compilation": {
    "strategy": "recommended",
    "compile_timeout_s": 120
  }
}
```

这些字段与原来的 `gates`、`layout`、硬件等字段组成完整请求。`circuit_profile` 定义量子跟踪、门集、读出历史与协议检查；`compilation` 只控制调度及搜索。Python `resolve_compilation` 是执行真值，返回 `compilation_backend` 能力说明和旧 flat 字段的兼容镜像。新 nested 配置整体权威；缺省预算不会从旧镜像悄悄补回。

| profile / 平台 | recommended | baseline |
| --- | --- | --- |
| physical / 普通布局 | greedy | basic |
| physical / surface_patches | patch_greedy | patch_symmetric |
| qec_ghz2 | qec_joint | qec_ghz2 |
| qec_temporal | 原带历史校验的 temporal joint | 明确拒绝，未接入 |
| qec_temporal_four | 原四块分组 temporal joint | 明确拒绝，未接入 |

2026-09-13 补充：内置配置下拉框按组提供九个具名预设：M4 greedy / critical_path / lookahead / basic，二维 patch_greedy / patch_symmetric，单轮 QEC qec_joint / qec_persistent / qec_ghz2。选择预设写入独立 `compilation`（复用 `strategy=legacy` + `implementation` 的现有精确派发接口，界面显示策略正式名称）；不改线路、协议或平台。M4预设 READY=16、site=4，lookahead额外depth=2/beam=3/rollout=12；patch/QEC预设candidate=4096、A*=100000；max_decisions=10000，原编译时限保留。参数来自现有执行器默认值，可调整后保存副本。与当前profile/layout不兼容的预设可见但禁用并说明原因。多轮QEC推荐明确标为联合优化，未支持的其他实现不能绕开历史guard。旧 M3、row 等其余实现仍可经旧输入精确导入。读保存结果时，实际运行策略优先于历史输入标记，不给旧运行换调度标签。以上是在已有能力族中选择实现，没有新增通用最优算法、动态变距或扩大物理支持范围。

独立配置文件：`{schema:"atom-studio-configuration/v1",kind:"platform"|"compilation",name,config}`。平台文件不接受 gates、profile 或 compilation 字段，编译文件不接受布局、量子态和电路字段。

## 显式执行与显示

- 自动编译及 debounce 触发已移除。初始打开、改参数、放门、载入模板、导入配置和保存结果链接都不发起 `/api/compile`。只在量子线路卡片点击编译后运行；编辑会取消过期任务，结果有版本标识，失败弹窗和诊断下载保持。
- 初态默认摘要，可展开修改；模板和搜索预算折叠；测量明细、量子验证和调度日志按需展开。QEC 模式为协议状态显示，不能用一个开关悄悄换整条线路。
- 关闭 SLM 改为淡灰小点，开启 SLM 为细环。空 SLM / 关闭 SLM 可分别隐藏；网格不重复画已配置 SLM 的点。原子不随 trap 筛选消失，所有活动 AOD 空交点保持，坐标、holder、物理状态完全不变。
- 已保存四块结果继续保留后缀续编译标识、完整前缀与后缀回放范围、真实测量报告与独立重放证据。显示精简不改变结论的支持范围。

## 验证入口

`examples/accept_workbench_configuration_ui.py` 在独立 headless Edge 检查三层隔离、配置往返、无自动请求、普通四 H 的真实并行编译、读取已保存 1868 槽实例，以及任意编辑为六门的真实 CZ/MEASURE/RESET 编译。该检查不重编完整 1868 槽或重复小时级物理重放；原完整验收见 [四块报告](qec_temporal_four_acceptance.md)。本轮结果见 [日志](../instruction/logs/2026-09-13-workbench-configurations.md)。

## 回放主动操作（2026-09-13）

播放/暂停、时间轴与模式/倍速位于画布顶部。可输入真实μs跳转、跳到终点、逐事件或下一门定位；批H/CZ、测量和复位均可从线路编辑器定位。普通滚轮滚动页面，Ctrl/Meta＋滚轮缩放；拖动平移、聚焦原子/全景和键盘空格/左右键可用。「专注回放」收起线路区，返回按钮恢复编辑。回放展示已编译执行记录；操作时间或视图不更改原子物理状态。零操作记录明确标为静态布局并禁用播放，仍需在线路区手动编译。

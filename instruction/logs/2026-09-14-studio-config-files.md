# 2026-09-14 · 工作台规则固化为配置文件

- 状态：COMPLETED
- 用户要求：将上一轮配置分层方案固化到配置文件。
- 范围：共用目录、默认预算/初态/电路选择、完整demo配套输入；保持物理约束、锁定规则和旧输入兼容。
- 已导出迁移前五份demo的规范化SHA256，作为配置外置后语义不变的对照；证据目录 artifacts/studio-config-files-2026-09-14。
- 已完成：`configs/studio/workbench.json` 统一管理六种通用算法、预算、默认初态、纯电路目录及完整 demo 索引；`configs/studio/demos/*.json` 保存五份完整电路/平台/协议/编译输入。删除 demo 中派生容量与 flat compiler/budget 镜像。
- `studio_config.py` 启动时读取和验证目录，固定同一进程内 demo 快照；前端 `studio_model.js` / `workbench.js` 读取后端同一目录，不再各自维护默认值。保留实际实现白名单、服务端 demo 锁定、物理能力检查。
- 验证：相关三文件测试57项通过；最后快照读取调整后配置文件专项6项再次通过（重叠，不相加）。五份 demo 规范化输入迁移前后 SHA256 全部相同；Node 语法检查通过；HTTP 目录与源文件一致，demo API 及既有结果恢复通过。真实浏览器加载可编辑4门已完成结果，console errors 为空；没有重新完整编译 GHZ 或运行全仓 suite。
- 服务交付：http://127.0.0.1:8791/?job=679c19d84cd444c680517fdd71dedec9 。自动审批拒绝停止旧8790服务，仅返回 `blocked by policy`，没有提供更具体理由；未重试停止，改为独立8791服务。旧服务保留，已保存结果与取消状态保留原 job ID。最初文件恢复断言遇到的是取消后未完成结果的 job，不是新的物理编译失败；未中断用户编译。
- 证据：`artifacts/studio-config-files-2026-09-14/demo-migration-verification.json`、`server-verification.json`、测试输出及独立服务脚本/日志。
- 修改配置后重启服务并刷新页面，新建自定义配置使用新默认；已有草稿/用户保存配置不被静默覆盖。使用说明见 `configs/studio/README.md`。
- 物理硬约束、唯一 Executor、checkpoint schema19 不变。源码留在 main 工作区，本轮未提交或推送 GitHub。

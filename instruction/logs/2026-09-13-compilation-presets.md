# 2026-09-13 · 重要编译策略内置配置

- 状态：COMPLETED
- 用户要求：精简后仍应能直接选择之前讨论的重要编译策略及默认配置。
- 实现：workbench.js增加九个内置预设，按M4、二维批量运输、单轮QEC分组；HTML配置标题改为内置策略配置。原推荐/基线保留，具名实现复用现有精确派发API。默认搜索参数采用现有backend默认值，选择保留时限；线路、layout、协议不改。与当前平台/协议不兼容的条目显示原因并禁用；多轮推荐明确命名，无guard旁路。
- 规范：同步docs/workbench_configurations.md、docs/circuit_workbench.md及handoff。没有改物理、Python API或重启服务；8788刷新静态UI即生效。
- 验证：node语法、workbench_large_controls.cjs、workbench_temporal_four_controls.cjs通过。examples/accept_compilation_presets_ui.py真实Edge PASS：九项实际API preview派发、各项切换的线路/初态/协议保留、默认预算与时限、错误范围禁用、无自动编译。最后手动lookahead实际执行4H为1μs，无page errors。证据artifacts/workbench-presets/acceptance.json和两张配置页截图；没有重编1868槽或重复小时级重放。
- 适用范围：多轮QEC仅已有guarded joint实现，其他策略不能因列入菜单便宣称可用于该协议；M3/旧行对照仍能通过历史JSON导入。

# 2026-09-14 · 独立逐原子统计与 main 分支统一

- 状态：COMPLETED（本地实现与验收；Git 交付核对见文末）
- 用户目标：独立汇总每原子累计路程、装卸次数、各类门次数、等待时间；提交 GitHub；唯一分支改为 main。
- 起点：本地/远端默认分支 codex/snapshot-2026-09-14，提交 377744d；现有 checkpoint schema19。
- 规范：agent.md、motion_execution、validation、workflow；统计只读，Executor 仍是实时状态唯一写入者。

## 完成内容

- 新增 statistics 模块，完整已提交 trace 单遍增量消费，支持状态重建及独立 JSON/CSV 导出。
- VisualRecorder、新工作台 worker 与离线 compile_workbench 导出接入；历史 trace 可用 summarize_atoms CLI 补算，无需重新规划或量子重放。
- 口径与边界见 [逐原子统计合同](../../docs/atom_statistics.md)。不改变物理参数、调度策略或 checkpoint。

## 验证记录（持续更新）

- 首批 6 项专项通过；随后扩大回归 101 passed / 1 failed：旧串行 plan 的 initial_placement 为 None 导致统计初始化异常。已修复可选字段兼容，增加旧串行真实执行回归；失败记录保留于 artifacts/atom-statistics-2026-09-14/regression-attempt1.json。
- 修复后 replay_interaction / visualization / row_column_aod 19 项通过；新增专项扩充至 8 项通过。
- 已保存四逻辑 GHZ：68 原子 / 8360 条提交记录，统计生成约 5.64 秒（本机单次，不是编译加速基准）。累计路程合计 62282 μm、装载/卸载各 853 原子次，与历史全局路程、捕获总数一致；历史 231 次是装卸批次数。
- 未重跑全仓 suite、小时级完整物理编译、独立量子重放或真实浏览器验收。

- 最终命令：`python -m pytest tests/test_atom_statistics.py tests/test_replay_interaction.py tests/test_visualization.py tests/test_row_column_aod.py -q --basetemp=artifacts/atom-statistics-2026-09-14/final-tmp`，**29 passed / 26.41s**。证据 `final-tests.json`。其中 10 项逐原子专项含真实局部 PARK/RECAPTURE、工作台 worker 实际 H/X/Y/Z/T/CZ 编译、CSV 与独立 CLI 重建相等。
- 离线 `compile_workbench.py` 单 H 冒烟成功，两个原子的统计 JSON/CSV 与 recording 一致，未参与原子等待 1 μs；`compile-cli-verification.json`。首次验收读取脚本用系统 GBK 解码 UTF-8 recording 失败，显式 UTF-8 后只重读已生成文件通过；生产编译/导出未失败。
- 历史实际效果审计核对：H689、CZ1014 原子参与次、X2、Z3、MEASURE160、RESET160 完全匹配；347 个 false 条件槽未记门数。所有 68 原子的 busy+waiting 等于程序 elapsed。证据 `ghz4-verification.json`。

## Git 交付

- 按用户明确要求将当前完整历史分支统一为 `main`；推送后设置 GitHub 默认分支为 main，再删除旧 snapshot 名称。保留全部既有提交历史，不做强制覆盖。
- 推送前已核对远端只有 `codex/snapshot-2026-09-14`，HEAD 仍为 377744d9046aff85bfe6d4f63a91a11220b7e5fd。删除旧名使用该精确 SHA 的 lease；远端出现新提交则拒绝删除。
- GitHub 推送/default/唯一分支核对凭据保存在本地 `artifacts/atom-statistics-2026-09-14/git-delivery.json`；若该凭据不存在，不能仅据本日志假设网络交付已成功。

## 后续与限制

- 本轮独立数据模块与导出已验收；GUI 逐原子表尚未增加，旧服务需重启才能加载新 Python 代码。没有更改当前用户的浏览器实例。
- 后续可由界面直接读取 atom_statistics 制作逐原子表；若要按任意播放时刻查看历史累计，需要单独建立时间索引，不能将最终汇总冒充该播放时刻的统计。
- 架构 A0–A8 与生产编译性能优化仍待实施；本轮统计模块不表示这些工作包已完成。

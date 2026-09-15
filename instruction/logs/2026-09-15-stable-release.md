# 2026-09-15 · 非 RL 版本整理与 GitHub 发布

- 状态：IN_PROGRESS（整理及本地验收完成，待推送核验）
- 用户目标：整理当前版本、补充说明，上传 physics-Yu/QEC-schedule；新增 RL 工作不纳入。
- 基线：main / 7fe9f59；最新工作台为测量落点策略版本（开发机 8798）。
- 相关规范：agent.md、instruction/workflow.md、docs/environment_strategy_boundary.md。

## 完成内容

1. 汇总尚未提交的非 RL 功能：有序 AOD 贪心/独立 SMT、2.5 μm 路线和 axis-hold、正交后端、精确完成时刻修复、QEC 编辑器、测量支撑与落点策略。详细合同沿用专题说明，本轮未修改规划或物理语义。
2. 新增 [当前版本说明](../../docs/current_version.md)，区分环境、策略、运动、实验和应用职责，列出固定规则/用户选项/自动计算项、复现命令、已有结果及限制；更新 README 和源码导航。
3. Demo 首页与启动器增加当前 QEC 可编辑入口，动态分配独立端口；两份完整已编译动画、输入、诊断、CSV 和分析导出到 `demo/qec/reference/`。动画合计约 7.1 MB，完整精选包 132 文件 / 55.2 MB。大型 trace/plans/checkpoint 由复现生成，不随 Git 上传。
4. 缩短 handoff，逐轮摘要移入 [发布前归档](2026-09-15-pre-release-handoff.md)；归档保留历史状态，不能把旧“未推送”误当现状。
5. 显式选择非 RL 路径暂存；新增 RL 代码/配置/文档/测试和 `instruction/planning_rl.md` 的本地修改保留。handoff 暂存版本只含本次稳定内容，工作区保留另一个任务的 RL 摘要。

## 本轮验证

| 检查 | 结果 |
| --- | --- |
| 主工作区 6 个相关 Python 测试文件（版本说明中的完整命令） | 43 passed，117.00 s |
| Git 暂存树导出，无旧 artifacts / 新 RL；新建 venv 安装 `.[smt,test]` | 成功；Windows / Python 3.12，pytest 9.1.1，z3-solver 5.1.0.0 |
| 干净导出的 `tools/check_architecture.py` | 139 模块，0 违规 |
| 干净目录重新 `build_demo_bundle.py` + `check_demo_bundle.py` | 132 文件，哈希/尺寸/链接通过；重导出 manifest 逐字不变 |
| 干净目录 environment_boundary / row_column_aod / visualization / readout_placement_policy | 38 passed，97.27 s（与主回归部分重叠，不相加宣称独立测试数） |
| 干净目录 qec_ordered_comparison | 6 passed，39.82 s，含独立 SMT 约束和编辑 H/测量/复位/条件 X 的两策略真实执行/重放 |
| `node tests/qec_editor.cjs demo/qec/reference/input.json` | 离线编辑器分页、9 对横向 CZ、选中/编辑/插入/删除及配置隔离通过 |
| `node tests/qec_axis_hold_replay.cjs demo/qec/reference` | 两动画逐段三次插值/轴保持、物理及关键帧模式 32× 到终态通过 |
| HTTP 新启动器检查 | 四首页、动态 QEC 链接、483 槽与外部测量默认值、JS/两动画哈希、错误输入结构化 400：10 项通过 |
| `git diff --cached --check`、暂存文件/新文档链接及常见凭据格式扫描 | 通过；无新增 RL 路径暂存 |

HTTP 首次检查因验收脚本错误假定 JS 导出名 `QECEditor` 而失败，产品响应为 200；修正为响应与维护源文件 SHA256 比较后通过，未改变产品实现。可重复运行的版本为 `python tools/check_demo_http.py`，失败时亦关闭本脚本创建的服务。

本地完整证据在 `artifacts/stable-release/`（干净目录内含验收 JSON、启动日志）；新克隆可依照版本说明重新运行检查。没有运行全仓测试；没有重新编译完整 483 槽 GHZ。仓库动画与 24337.381 / 24975.219 μs 指标来自前轮完整执行，导出哈希未变。

## 决策与限制

- 不修改已有物理条件，不新增 RL 依赖；完整仓库而非单独安装 wheel 是当前运行单位。
- 最新 GUI 的真实浏览器交互仍未补验；HTTP/离线替身不冒充 GUI。旧工作台、当前 QEC 实验和历史 GHZ4 的支持范围分别注明。
- 有限候选、每批归还、完整服务串行与固定 QEC 平台仍限制性能；不把此轮整理宣称为通用最优编译完成。

## 发布核验

待推送到 `https://github.com/physics-Yu/QEC-schedule.git` 的 `main` 并核对远端 SHA；未使用强制推送或额外分支。

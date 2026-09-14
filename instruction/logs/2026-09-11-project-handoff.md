# 2026-09-11 · 项目总览与文档交接

- 状态：COMPLETED（文档交接完成；M3 里程碑仍未完成）
- 用户要求：汇总现有全部内容，完成文档交接与记录。
- 本轮范围：核对源码/规范/历史验收、汇总当前能力/用户决策/缺口/复现与下一步，整理导航。只做文档交接，不新增运行时功能、不把历史 PASS 当成本轮重跑。

## 完成内容

| 文件 | 交接内容 |
| --- | --- |
| [项目总览快照](../../docs/project_status_2026-09-11.md) | 用户决策、当前 pipeline、M0–M6 状态、物理/状态不变量、源码入口、工作台/随机线路/回放能力、已知限制、历史验收与跨机器复现 |
| [当前 handoff](../handoff.md) | 更新为 2026-09-11 简短入口，区分本次文档完成与 M3 未完成，明确下一项 M3-B 独立任务 IR |
| [项目首页](../../README.md) | 补随机按钮与总览入口；修正旧 schema 9、七类统计、动态 masks 未实现、所有参数化门不支持和默认 rigid-parking 六门全成功等过期描述 |
| [规范索引](../README.md) | 增加有日期的能力/证据快照导航，领域规范继续各自维护 |
| [日志索引](README.md) | 增加本次记录，补齐遗漏的历史 GitHub 同步入口，把 motion planner/trap spacing 恢复到完整表格；同日主题排序不冒充精确执行顺序 |

保留所有已完成日志正文。首次尝试替换 handoff 时 apply_patch 拒绝同一补丁中对同文件同时 delete/add，未应用该批修改；随后改为单次文件写入及正常 update，最终文件均检查通过。

## 核对范围与验证

先读 agent/handoff，按文档交接任务选择 workflow、milestones、model_audit；按链接核对工作台、动态光阱、固定 pipeline、随机按钮和历史发布记录，没有全量重读 references 或原架构。

| 命令 / 检查 | 本次结果 | 可解释范围 |
| --- | --- | --- |
| `rg` 与定向源码读取 | schema 11、八类 + 条件 Raman、固定 1 μs、32×、工作台规模/随机链路、串行与单 gate plan 限制和下一阶段要求一致 | 实现/规范核对，不是重新物理执行 |
| Python `urllib.request.urlopen('http://127.0.0.1:8766/', timeout=5)` | HTTP 200，11835 bytes，含 `random-circuit` | GET 只读可用性，不证明用户当前浏览器已刷新或外观验收通过 |
| Python pathlib/re 检查六份改动文档 | 全部相对链接目标存在，代码围栏成对，无尾随空白；日志索引覆盖所有日期日志 | 本次新增链接无锚点；未访问外部链接 |
| Python json 解析总览中的随机输入并比较本地 `artifacts/random-circuit-check/input.json` | 完全相同；标准 mixed 输入也已核对 | 固化实际历史输入，跨机器无需依赖被忽略的 artifacts 或再次随机抽样 |
| Python hashlib 对 src/configs/examples/tests 文件计算前后聚合 SHA-256 | 四组均相同，见下表 | 没有运行时代码、配置、示例或测试变更 |
| `git status --short` / `git log -1 --oneline` | 项目整体未跟踪；master 没有提交，log 返回该说明 | 不以空 `git diff` 当作完整变更检查；本次未提交或发布 |

本次没有运行 pytest、Node 控制测试、物理示例编译或真实浏览器验收，没有刷新草稿、重启服务或触发编译 API。Python 仅用于文档/JSON/哈希/HTTP 检查，不能记为“Python 测试通过”。现有 mixed/random 产物存在，但不据此认定本次新生成。

### 运行源码指纹

无本地提交可供定位，因此记录本次未改动的工作源码。算法：每组递归收集文件，排除 `__pycache__` 和 `.pyc`，按 Path 排序，逐项向 SHA-256 写入“仓库相对 POSIX 路径的 UTF-8 字节 + NUL + 文件原字节 + NUL”。不包括 artifacts；这些是本机字节指纹，跨机器换行改写也会改变结果。

| 目录 | 文件数 | SHA-256 |
| --- | --- | --- |
| src | 77 | `a8817f286ad59e4f5210fbaf5b982e3de05b26c1a79ccd3eb06bdd49f21596fe` |
| configs | 9 | `c56c4478b09c96d4e1cd08494fc8d22ebe0cbbef381177eea3c3da4397d7717d` |
| examples | 12 | `ede2c8459fe45fc115861209e534491445417a3bf62e1336fe056a2389fa6475` |
| tests | 26 | `bba69349a6f4826cc372596bd197dfa0457c0384afac1fb4b048c4c2c5bc8915` |

## 历史证据、决策与边界

- [首版工作台](2026-09-10-circuit-workbench.md) 的 254 passed / 1 warning 是固定 1 μs 和随机按钮之前的全套结果；[固定 pipeline](2026-09-10-workbench-standard-pipeline.md) 的 90 passed / 1 warning 是之后的相关回归。不能将它们合并成最终源码的新全套结论。
- [随机按钮](2026-09-10-random-circuit-button.md) 有临时 Node VM/DOM 200 组检查和实际 8 门编译记录；临时脚本不在仓库，总览保存精确 JSON 输入及 CLI 重建方法。布局 seed 73 仅控制初态，按钮的 Math.random 不受该 seed 控制。
- 1 μs、初始条件优先、最高 32× 和默认 pipeline 来自已确认用户要求；本次不改变物理参数或验收判据。
- CUA 在固定 pipeline/随机按钮两轮连接失败，真实浏览器视觉补验仍待做；512 原子显示样本不代表实际混合运输、并发或 FPS 完成。
- [历史 GitHub 同步](2026-09-10-github-sync.md) 记录 105 文件程序发布和提交 `dcc849f7729bab38d4263b4cd31ea04fd5f4f29b`，内部资料未公开。本次未查远端，不声称后续工作台变更已发布；修正此前 handoff 对“没有发布”的无时间范围表述，不改写历史日志。

## 未完成与下一步

M3-A 已验收，GAP-004 仅覆盖串行 1Q；GAP-003、005–009 仍 OPEN。无 gate 任务、prepare/pulse/cleanup、通用持久续接/退出、1Q 与运输重叠、两个实质不同混合 compiler、完整失败契约及数百原子端到端证据均未完成。本次不改变任何运行时问题状态。

继续 M3-B：读取 milestones/compiler_contract/state_circuit，从 domain/operations.py、motion/program.py、validator 和 Executor 实现独立目标任务/操作 IR。完成条件为真实零门运输不改变 DAG、拆分后唯一门效果、可验证终态/资源、失败原子性和边界恢复，且保留既有 Raman/M3-A 正负例；再推进 M3-C、M3-D。

启动、标准混合输入、相关/完整测试及精确随机输入见 [总览复现段](../../docs/project_status_2026-09-11.md)。`artifacts/` 被 Git 忽略，跨机器需重建或另行保存；浏览器草稿无自动持久化，刷新前导出 JSON。文档交接已保存在本地，不包含对外发布。

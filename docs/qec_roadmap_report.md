# 四阶段持久验收看板

2026-09-12 最新用户审批边界：测试脚本、界面交互、序列化和一般工程缺陷可自主修复、记录并重新验收；不再因这类失败请求审批。只有物理模型/物理事实可能出错、需要改动物理硬约束，或整体架构需要调整时才暂停相关方向，给出事实与方案并请求用户批准。不得放宽物理条件、掩盖失败或以改断言冒充通过；保留每次尝试证据。此规则取代此前“任何正式失败都需审批”的规定。 下文旧尝试的统一暂停措辞仅记录当时流程。

入口：`python examples/qec_roadmap_report.py --port 8782 --directory artifacts/qec-roadmap`。
它与原 8781 编辑器独立，不会运行实验。主执行流程唯一维护 `status.json`；
看板每 10 秒及点击刷新时只读该文件。POST/PUT/PATCH/DELETE 均返回 405。
`--write-only` 仅生成 HTML/JS，不新建或修改状态文件。

状态 schema 为 1，包含 `updated_at` 和四个 `stages`。每阶段包含 `id`、
`title`、`status`、`attempts`。阶段状态为 pending/running/passed/failed/
awaiting_approval。尝试包含递增 `number`、显式 `formal`、status、开始/结束
时间和 `evidence=[{label,path}]`。证据路径只展示，不提供任意文件读取接口。

正式失败必须包含 `failure.facts`、`hypotheses`、`proposed_retry_scope` 三个
字符串列表及 `approval={status,user_message}`。事实与尚未核实的原因假设
分别展示。审批状态为 pending/approved/rejected；approved 必须附用户原文。
schema1保留该兼容字段。一般工程失败可将approval记录为approved，并附用户本次长期授权原文及工程分类，无需再次询问；涉及物理事实/约束或整体框架的失败必须另行取得针对性审批。时间经过不算审批。
通过阶段必须有实际正式通过的 attempt 与证据，否则服务拒绝该状态记录。

失败阶段自动弹窗且保留尝试历史。关闭只隐藏当前弹窗，不修改文件、不批准、
不重试；新的失败记录会重新弹窗。未通过阶段不能由局部检查或候选拒绝
推断为 PASS。局部搜索拒绝可记录为 `formal=false`，不会触发正式失败弹窗。
主执行流程负责保存失败证据和分类；工程问题自行修复重验，只有物理/框架问题暂停相关方向等待审批。看板不替代该职责。

2026-09-12 验证：`pytest tests/test_roadmap_report.py -q` 一次通过 7 项，
含真实 headless Microsoft Edge 的隔离预期失败弹窗检查。测试状态文件位于
临时目录，不写真实 ledger；结果 `artifacts/qec-roadmap-display-tests/browser-report.json`
明确 `formal_stage_acceptance=false`。另真实 8782 只读展示检查无页面错误，
结果为同目录 `live-browser.json`，截图 `live-roadmap.png`。当时读取状态为
step1 passed、step2 running、step3/4 pending；这些状态来自主执行流程，
不是看板自行评定。测试期间没有发生意外失败或修复重跑。

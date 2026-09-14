# 2026-09-13 · 工作台配置分层与界面精简

- 状态：COMPLETED
- 用户目标：删除重复容量、杂乱策略与自动编译；策略独立于电路；区分平台管理和线路配置；编译按钮归线路层；关闭 SLM 视觉降噪。
- 开始基线：四步及4A/4B/4C按声明合同通过，8787保存完整四块1868槽实例。没有重新扩大物理里程碑。
- 相关规范：agent.md、handoff、visualization、compiler_contract、workflow。

## 完成内容

- workbench.py 增加 `circuit_profile` / `compilation` resolver，legacy 精确兼容，nested 预算权威，temporal baseline明确拒绝；server恢复按实际运行策略标记。
- workbench.html/js 分为线路与回放、配置管理；行列派生容量，平台和编译配置单独命名/导入导出，模板保留编译配置；删除自动编译与定时触发；主编译按钮在线路卡片。
- viewer.js/shell 关闭 SLM 改淡点，空/关闭 SLM 独立筛选，消除重复grid叠点，原子/活动AOD/真实坐标保持。
- 更新相关Node控件与浏览器验收脚本，新增配置隔离真实浏览器验收。

## 本轮检查与尝试记录

- 后端首批120项PASS；全workbench第一轮遇到旧Node测试访问已删除auto字段；156项其他检查PASS。测试契约迁移后最终全workbench：157 passed, 1380 deselected, 1 warning in 29.64s；命令 `python -m pytest tests -q --disable-warnings --maxfail=1 -k workbench`，包含deep-link真实API短编译。
- viewer专项5项PASS，真实Edge只读六门旧recording显示检查PASS，未重新编译；证据 `artifacts/2026-09-13-slm-display/`。
- 5个现有DOM/HTTP替身控件检查PASS，记录 `artifacts/2026-09-13-ui-controls/checks.json`。
- 新browser attempt1错误地用原生document选择器访问viewer shadow DOM，等待超时，没有编译请求。改用Playwright穿透选择器；失败证据保留。
- attempt2配置载入校验返回规范输入，排序门数组，违反配置层应保留线路数组原序的预期（门语义没有改变）。修复为校验完整候选、只采用编译规范元数据并保留候选线路；失败证据保留。
- attempt3已经通过配置隔离、四H真实并行与完整保存实例读取；在 Playwright `is_disabled()` 检查 `<option>` 时失败。只读核对真实 DOM 显示 `disabled=""`，改直接读取 option.disabled（后端拒绝同样有独立测试），不是能力约束松动。
+- attempt4前述检查全部通过；六门导入的严格字典比较失败，因为规范API为门增加空 `condition`/`depends_on`。给预期补全这两个既有规范空字段，保留门ID/类型/操作数/列/报告翻转及实际物理断言。
+- **attempt5全部PASS**：`C:/python312/python.exe examples/accept_workbench_configuration_ui.py --output artifacts/workbench-cleanup/acceptance-attempt5`。真实隔离Edge，配置保存/导入导出与模板、策略隔离；打开/编辑/配置更换无自动编译；4 H真实并行1μs；完整保存68原子/1868槽未重新编译；六门CZ/MEASURE/RESET实际执行4006.6μs，G004真实0/报告1，短线路GHZ/protocol标false；1440与720视口无水平溢出；无page errors。两次真实编译请求，其他操作无编译请求。
+- 最终普通job `d5c30f3aa3414d5ea24cf228ee1c3cdd`；六门job `14043b60fbaf4feebe30b2ea68ed6bc3`。证据与全页截图在 `artifacts/workbench-cleanup/acceptance-attempt5/`，root已检查管理页、完整保存线路页和窄屏截图。
+- 3个temporal/temporal_four/resume Node检查在最终配置加载修复后再次PASS。没有重跑原小时级1868槽编译/独立物理重放，没有跑全仓库1537项；旧双32×完整验收仍是历史证据。本轮更新了该长验收脚本交互入口，未执行它。

## 决策与边界

全部是用户明确授权的配置结构和工程/显示改动，没有修改硬件参数、碰撞、支撑、CZ或读出模型。工程失败自行修复记录，不触发重复审批。

新配置合同见 [workbench_configurations](../../docs/workbench_configurations.md)。完整四块保存结果仅恢复展示，不重复小时级编译/物理重放；本次小线路真实编译用于验证编辑输入与配置连接。

## 服务

新服务8788，PID23976，输出 `artifacts/workbench-configurations`，保存实例87eef4dc58e467e0e6b423bfda158c43。旧8787及历史服务/产物保留。旧进程读新的静态UI，但其Python实现需要新进程才能启用新resolver；交付使用8788。

## 后续与已知限制

本轮用户要求已完成。配置库仅本机同origin存储，跨端口请导出JSON；线路草稿仍须导出。temporal baseline未支持并明确禁用；legacy实验实现只兼容导入。AOD动态变距、任意布局最优和大型编译性能仍不在本轮范围。交付新配置API请用8788，旧服务不具备新Python resolver。

# 新独立 QEC Scheduler Next：N0 交付

用户明确要求在 `C:/Users/86136/Documents/ChatGPT` 下新建文件夹，逐步重建 schedule/reuse/routing/placement/code generation，并参考 Enola/ZAC。交付：`C:/Users/86136/Documents/ChatGPT/QEC-scheduler-next`；项目入口及后续交接均在新目录 README、docs 内。

本轮完成完整 physical circuit DAG 与派生 2q DAG/ASAP、五模块纯函数基线、EZ SLM 驻留匹配、贪心目标分配和 AOD 兼容运输组、显式目标级指令、独立结构审计、JSON CLI、四类可编辑输入以及三例驻留/无驻留对照。旧 `strategies/ir/interaction.py` 的准备/执行合同作压缩迁移，源 SHA 和 Enola/ZAC 固定版本见新 `docs/provenance.md`。没有旧包运行依赖；不改现有 Env、工作台或 RL。

第一阶段范围在实施前已明确为结构编译闭环：连续轨迹、真实计时、Executor、量子演化/测量结果和 GUI 尚未迁移。不能把本轮称为物理执行通过、完整 Enola/ZAC 复现或新架构全部完成。

准备区位于本仓库忽略的 `artifacts/qec-next-bootstrap-20260922`，交付目录共复制并逐文件 SHA256 核对 41 文件。新目录独立运行 86 测试通过，7 份完整目标程序保存后重新载入审计通过，记录在 `reports/acceptance/delivery-verification.json`。

同输入/平台/初态/终态：6 原子换伙伴 14→12 次运输批；20 原子 60 门四输入层 49→49；5 原子三轮同一 parity check 53→38。只评价结构运输组数，不是物理时间。parity check 不称完整 surface code 或纠错。

审查修复：compare 先评分后查 CZ 构型会把有效 no-reuse 替代方案掩盖，现改为独立 endpoint predicate 在候选录取前校验，保留拒绝证据，最终仍独立全程序审计。

交付测试先遇系统临时目录权限、再遇新临时目录父级缺失，保留两次 setup-error 输出后创建独立 build 父目录复验通过；未更改断言。一次误从旧项目启动的 pytest 已立即中止，不计旧项目验收。

下一步：按新 `docs/milestones.md` 的 N1 提取最小物理 state/action/validator/Executor 依赖闭包，同初态/同操作新旧差分；连续路由和计时逐项验收后才接 viewer。未 Git 提交或推送。

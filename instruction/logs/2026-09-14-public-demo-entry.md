# 2026-09-14 · README 与可移植 Demo 入口

- 状态：COMPLETED（本地交付和核验完成，Git 发布结果由后续提交记录确认）
- 用户目标：对外重写 README，精选 SMT 与完整编辑器可视化到 demo/，跨电脑运行，并上传自己的 GitHub main。
- 基线：main b2eb16d；本地已有环境/策略拆包、配置分层、电路审计及 SMT 未提交。本轮包含这些源码，避免新入口缺少后端实现。
- 范围：文档、导出与启动包装；不改变物理规则或调度目标。

## 实现

- README 按项目目标、快速开始、能力/限制、实验与架构组织。
- demo/ 包含编辑器、12 条 SMT 参考动画与数据、四逻辑 GHZ 历史回放；新运行写 artifacts/demo-runs。
- 启动器使用当前 Python、仓库相对定位、回环地址、动态端口，无旧 job/绝对用户路径依赖。
- 服务器新增 UI/只读参考目录注入，原 CLI 保持。
- GitHub 插件确认 physics-Yu/QEC-schedule 为 public、默认 main、有 push 权限；使用 Git CLI 发布完整差异。

## 验证与发布

- 新 Git 暂存树 ZIP 解压至带空格中文的新目录、无旧 artifacts，新venv只安装 .[smt] 成功；工作台与 SMT 在新自动端口真正编译。
- 60 项相关回归与131模块架构检查通过；Edge18项通过。首次导出脚本换行转义失败保留在 browser-attempt1，修复后 browser-attempt2 全通过，无脚本错误。
- 120 个精选文件约47.3MB；原始GHZ回放仅更新外层本机链接，源/现哈希分别记录，未重编译物理记录。
- Git输出换行属性保证跨电脑清单哈希；链接/大小/常见凭据模式检查通过。源码末尾冗余空行做了无语义清理。
- 证据：artifacts/portable-check；公开摘要见 docs/demo_delivery_validation.md。
- 未验收 macOS/Linux实机，未跑全仓测试或小时级QEC重编译/重放；此前证据不冒充本轮通过。
- 发布使用普通main提交与推送，保留现有历史；不强推、不删除远端分支。

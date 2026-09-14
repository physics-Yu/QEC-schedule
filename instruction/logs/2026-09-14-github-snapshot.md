# 2026-09-14 · GitHub阶段快照

- 状态：快照内容与检查记录完成；GitHub提交结果以远端`codex/snapshot-2026-09-14`分支和本次交付消息为准。
- 用户授权：将现有项目提交到 `https://github.com/physics-Yu/QEC-schedule.git`，然后讨论下一步。
- 起点：本地master为未产生提交的仓库，无已跟踪文件、无remote。
- 范围：源码、测试、配置、文档、复现脚本与项目已有参考资料。沿用`.gitignore`排除artifacts、虚拟环境、缓存和构建目录，不删除本地产物。

## 本轮准备

- 原446个待跟踪文件约2.9MB，最大文件约101KB；常见密钥模式与敏感文件名扫描未发现命中。这是限定模式检查，不是全面安全审计。
- README修正旧门集、自动编译、M4状态和schema说明，加入受限QEC/当前schema19/未实施架构方案及生成产物不随Git上传的说明。生产源码未改。
- 配置用户指定origin；采用独立快照分支，远端已有历史时不覆盖已有分支，不强推。
- 远端main已有`dcc849f`（105文件），本地覆盖全部这些路径。快照分支以origin/main为父提交，保留既有历史。参考PDF新增`.gitattributes`二进制规则，暂存字节与原文件完全一致。

## 本轮验证

命令：`C:/python312/python.exe -m pytest tests/test_foundations.py tests/test_gate_contract.py tests/test_quantum_readout.py tests/test_replay_interaction.py -q --basetemp=artifacts/git-snapshot-2026-09-14/pytest-tmp-attempt2`。

结果：62 passed，1项dateutil依赖弃用警告，6.58秒。未运行全仓suite、完整四逻辑重编译或GUI验收。另检查248个Python文件AST、13个JSON及README本地链接，全部PASS。

首次测试因新建的basetemp父目录不存在，59 passed/3 setup errors；创建父目录后重新运行通过，未修改测试或生产代码。首次GitHub访问连接重置，保留失败事实并重试。

Git直接连接连续失败，显式使用系统现有HTTP/HTTPS代理后成功读取refs并fetch。没有更改系统代理、TLS验证或全局Git配置。`git diff --cached --check`另有3处已有空白提示（历史参考原文1处、测试EOF空行2处），本轮保留原文与测试字节，不把这些提示写成全量检查通过。

证据：`artifacts/git-snapshot-2026-09-14/{attempt1-machine-tests.json,attempt2-machine-tests.json,preflight.json}`。这些生成证据按现有规则留在本地，关键检查命令与结果记录在此。

## 后续范围

A0–A8仍待实施；建议下一阶段从统一计时与减少重复状态/审计成本开始，再评估运输感知批次与落点算法。用户尚未授权本轮启动架构迁移。

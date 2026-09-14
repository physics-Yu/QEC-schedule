# 2026-09-10 · GitHub 当前项目同步

- 状态：PARTIAL（程序发布完成；内部资料未公开）
- 用户目标：以当前 QEC-scheduler 项目替换 physics-Yu/QEC-schedule 的 main 文件。
- 最终发布范围：105 个文件，包括源码、配置、示例、测试和使用文档；排除缓存、可重建 artifacts、instruction 目录、AGENTS.md、agent.md 和根目录架构导航。
- 基线：M0/M1/M2 与 rigid parking，运行时代码未修改。
- 方式：创建全新文件树，沿用远端提交作为父提交，删除旧版独有文件并保留 Git 历史。

## 验证
- python -m compileall -q src examples：通过。
- git diff --check：通过（初始文件均未跟踪）。
- 常见令牌与私钥模式扫描：未发现匹配。
- 本轮仅上传，不重跑完整物理测试；既有测试结果见此前日志。

## 发布结果
- GitHub main：dcc849f7729bab38d4263b4cd31ea04fd5f4f29b。
- 文件树：ad5b50f5ba6d7888738e2084684c73880ca7be49。
- 发布前逐文件 Git blob SHA 校验：105 个一致；再次 compileall 通过。
- GitHub update_ref 成功，远端 main 提交回读核验。
- 当前工作区上传期间有其他更新，已纳入最终哈希校验通过的可视化文档和测试。
- 本地 Git 尚无提交，内置 Git 缺少 remote-https，故通过 GitHub 插件发布。

## 未公开资料
- 自动审批拒绝公开历史日志中的本机路径与元数据，以及内部架构迁移资料。
- 未绕过审批，内部 instruction、参考档案和代理导航文件留在本地；如需公开，需要用户额外明确授权。
- 下一步：用户确认内部资料公开范围后，再补充该部分。运行时代码不变，本轮未重跑完整测试。

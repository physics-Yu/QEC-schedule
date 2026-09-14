# 2026-09-14 · 仅保留当前完整快照分支

- 状态：COMPLETED，远端默认分支更新与其他分支删除均已成功。
- 用户要求：规整GitHub，只保留今天包含现有全部项目文件的branch。
- 仓库：`physics-Yu/QEC-schedule`。
- 保留并设为默认：`codex/snapshot-2026-09-14`，文件基线`37012c41cd7b6151d8310b8ddbe0001389cf893e`。

## 操作与依据

先fetch确认远端最新状态。main已合并今日快照，`git diff origin/main origin/codex/snapshot-2026-09-14`无文件差异。保存本地Git bundle并通过`git bundle verify`，然后通过GitHub API修改默认分支，再原子删除以下远端分支：

| 分支 | 删除前提交 |
| --- | --- |
| main | 7c4da20ed9345d21b850d7a304f04be77bf08860 |
| codex/neutral-atom-execution-refactor | 8f9d293f244790ab2780e5b9046ed01c4a2422bd |
| revert-2-codex/snapshot-2026-09-14 | b47d85372b3b71df51f8fd3c347ad9e2de0e8400 |

删除使用精确旧SHA的lease防止并发更新被误删；没有改写保留分支历史。清理本地origin跟踪引用并更新origin/HEAD。追加本条日志及handoff，仍只推送同一个保留分支。

## 核验与恢复

证据目录：`artifacts/branch-cleanup-2026-09-14/`。`before-cleanup.bundle`是本地历史备份，不增加GitHub分支或标签；`default-branch.json`与`deleted-refs.json`分别记录默认分支与删除结果。保留分支包含原完整快照，新增内容仅为本轮文档记录。代码、物理模型与生成动画未变，无需重跑上一轮已通过的测试。

如需恢复历史分支，可从本地bundle取得表内对应提交后显式创建分支；本轮不创建备份分支。下一步架构/性能工作仍等待用户决定。

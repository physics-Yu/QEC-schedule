# 第四步首次失败报告与拟议重试

后续状态：用户已批准补齐参数；attempt2的Node控件检查已通过，未修改compiler/physics，正在继续原矩阵。原attempt1失败与下面停止时的记录保持。最新状态以`artifacts/qec-roadmap/status.json`及`instruction/logs/2026-09-12-qec-step4-approved-retry.md`为准。

状态：**AWAITING USER APPROVAL**。2026-09-12，第四步4A attempt1。未重试，未开始后续完整矩阵、带噪重复纠错或四逻辑扩展。

## 已确认事实

- 前三步已正式通过，最新可编辑成功结果是 `http://127.0.0.1:8784/?job=03a43acfc3a55199bc9ce6d971d37a92`。同481槽完整物理时间19255.9μs、装卸37次，保持量子/分支/终态；旧基线22055.9μs、装卸51次。
- 第四步新布局与接口等48项pytest首次通过（3.66s），包括错开坐标、112容量匹配、默认平台精确兼容及非法配置拒绝。
- 随后主任务执行了 `node tests/workbench_qec_controls.cjs`，漏传必需的输入JSON文件路径。
- 脚本第19行读取`process.argv[2]`时得到`undefined`，Node抛出`ERR_INVALID_ARG_TYPE`并以exit1退出。这发生在任何界面断言之前。

这是**主任务调用验收入口的错误**。本次没有发现物理编译失败，也没有证据说明UI功能有错；UI控件检查尚未执行，因此也不能将它标为通过。完整矩阵仍未启动。

## 原因与尚未知部分

直接根因已由命令与脚本入口确认：缺少位置参数。补参后的控件断言是否通过仍待运行。错开布局是否能完成全线路编译、有限搜索能否找到合法路径、其他故障线路是否通过等尚未由该矩阵验证，不能借48项输入检查代替这些结论。

## 具体拟议重试（尚未执行）

已有 `artifacts/qec-ui-tests/input.json` 是480门、无预置QEC_FAULT的完整QEC模板，包含条件门和角色数据，也没有新增原点字段，符合该脚本先添加再删除故障的前提。其SHA256和字段摘要已保存在`artifacts/qec-roadmap/step4-attempt1-tests/retry-proposal.json`。

用户批准后，新建第四步attempt2并保留全部attempt1证据，首先执行：

```powershell
node tests/workbench_qec_controls.cjs artifacts/qec-ui-tests/input.json
```

不为这个入口错误修改编译器或物理规则。仅该检查通过后，继续原合同的短线路、X(Q014)/seed23完整GHZ₂、Y(Q000)/seed7错开布局矩阵及独立重放；任何新意外失败再次停下报告。尚未实施重试或默认批准。

4A的新原点控件和输入支持仍是未完成联调验收的工作区改动，旧服务未重启，不把这些新控件作为已验收交付。旧成功结果的物理记录与离线动画保持；下一次获批尝试须使用加载一致版本代码的新验收服务再验证新控件。

## 持久证据

`artifacts/qec-roadmap/step4-attempt1-tests/` 包含pytest.txt、editor-controls.txt、failure.json、retry-proposal.json和实际失败弹窗截图/只读展示记录。`artifacts/qec-roadmap/status.json` 已将第四步置为awaiting_approval；只读看板 `http://127.0.0.1:8782/` 实际显示了失败弹窗，无page error。关闭弹窗不是审批。

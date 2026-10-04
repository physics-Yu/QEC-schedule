# 2026-10-04 · 原生编译与轻量运行内核迁移

- 状态：COMPLETED（独立内核首阶段；全工厂/processor迁移继续）
- 用户目标：迁移内核以获得快速运行能力，去除探索期架构；EZ 可采用原生配对布局或 Enola 类指令加 measurement。
- 起点：本 worktree clean HEAD a8c99fc；原主 checkout 有并行工厂修改。本轮只编辑本附属 worktree，工厂对话继续有预算兼容小例，不恢复旧六个长跑。
- 相关规范：agent.md、handoff、architecture、qec_factory_pipeline，新增 native_kernel_migration 为最新授权方向。

## 实施

新独立运行包、原生操作 lowering、离线物理 reviewer 和完整 d=3 小例并行开发。冷启动、原生编译、IR 转换、运行推进、录制/导出、离线审核分开计时。

## 决策

不把旧 ENV trusted 分支作为最终架构；旧 ProgramBuilder/SimulationState/完整 trace 只保留离线或显式兼容。平台版本化；原始身份、报告提交、位置续接和操作语义不丢失。首轮 native 使用单 AOD，不虚报双 AOD 原生调度。

## 验证与未完成

最终 `d3-two-rounds-attempt2` exit0，17原子/218源门/1123ops/2261journal/25报告；48CZ pairs→8 pulses/max6，82,554.391522μs。两native调用合计9.7216ms；cold native入口含导入0.3875s，lowering0.01584s/fullRF0.06457s，clean录制on0.26091s/off0.15415s，离线audit0.11921s，export0.36819s。恢复probe另0.40131s，wall_before_export1.77047s含两个fair run及恢复证明，不能与单productionrun或模型时间相混。

独立工具重建canonical源：66source/14artifact SHA、两native mandatory请求与原源segment、7block前态hash、实际196alignment ops/16,027.920070μs、inflight/finalcheckpoint与2261journal全部exact；离线全RF/Cartesian/CZ/MZ审核PASS。最早attempt0找出checkpoint原完整性缺口与lowerer可选SHA门禁，两项修复后attempt1 PASS；为factory小写角色兼容再跑attempt2。原三attempt均保留。checkpoint终态idlecursor字节保持、声明报告次序/Bernoulli恢复已测；空manifest、源gate改写并更新artifact hash、报告/checkpoint/native请求篡改均明确拒绝。

本轮123不同pytest/no skips/5.92s（15runtime、40lowerer、35独立audit、6viewer、1kernelboundary、12旧包边界、14旧视觉）；277modules0violation。两Node实际recording：六对CZ/XZ/同比缩放/无未来报告/倒放不可变、320/390/desktop fit均PASS。真实浏览器最终8780绑定attempt2，1280/390px无horizontaloverflow、主要统计展开/逐项折叠、首M完成前无位/结束后提交、六并行CZ与角色、console errors0。截图在同目录browser-qa。首轮子进程测试2fail是未设置PYTHONPATH，补测试环境及独立kernel子进程env后通过；未安装/修改共享venv。

新增工具 `tools/audit_native_kernel_memory.py` 不调用native，读取不可修改原产物、重建原canonical协议并独立几何及精确runtime重放；回执输出到run同级保持manifest封闭。小摘要 `references/qec_pbc_validation/native_kernel_2026_10_04.json` 存源码LF与原始产物指纹、复现及边界。新路径无legacyENV execution/candidate calls；Python运行器不是C++，C++只负责实际native编译；未进行同输入旧kernel墙钟speed ratio对照。

完整factory/injection/processor、native多AOD及physicalShor/噪声容错仍未由本轮验收。core/API/source-freeze-v2白名单12files已交工厂协作任务，旧source-freeze-v1只差offline converter小写role处理；不覆盖原并行checkout。下一步由其原W4协议全M→R barrier、143身份、二维buffer/fullRF接新core，先warm native小块与连续MZ资格，再S1–S3，旧六长跑保持停止。

RAG新增K70/L47；schema/source核对70chunks/59sources，76/76检索通过。既有L40/L41/L45的当前viewer LF摘要更新，历史raw producer指纹保持。GitHub阶段发布与独立fetch精确核对后追加回执；不merge。

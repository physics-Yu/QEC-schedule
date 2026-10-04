# 双 AOD 模块化运输

- 状态：限定纯运输组件、实际执行、浏览器与文档/RAG验收完成。阶段发布沿用draft PR#3，独立fetch回执见 `references/qec_pbc_validation/modular_aod_publication_2026_10_05.json`。
- 用户授权：设计独立data/resource AOD运输模块，资源可以自行归还并与data同时移动，不再人为错开。
- 基线：managed branch `codex/d3-shor15-stages`，HEAD `52d36a69c3cb73814f2bff942b83542d68b592c9`；原工作区、工厂冻结运行和8778旧录制只读。
- 实施：新增策略侧单设备模块＋依赖/资源协调器，调用已有scheduled KernelExecutor；独立dual-device连续RF/Cartesian几何review；实际34原子纯运输小例及相同操作串行对照；共用viewer显示两设备重叠与resource独立完成。
- 保护：不改冻结kernel四核心/旧single reviewer/env、物理阈值或共享viewer；不把运输演示称syndrome/magic/fullShor；RESET区域修正上一问尚未选择，本任务不隐含切换该权限。

## 验收

新增策略模块 `AODTransportModule.compile → coordinate_aod_modules → bind_block(geometry_guard)`；完整初态/holder/profile/RF绑定与审核input SHA精确匹配，只有status=PASS或旧input收据会拒绝。同设备END链、原子和显式shared资源在协调器安排，不加跨设备归还等待。一个scheduledBlock/唯一KernelExecutor，不在移动中动态追加Block。只支持分離device envelopes、载荷union全Cartesian RF。

实验入口 `examples/run_modular_aod_demo.py` 与 `experiments/qec_pbc/modular_aod_demo.py` 运行34原子/68有限5μmSLM位、左右各17原子、每台5×5RF/8空活动交点。14操作/31真实journal，data140μm往返+dwell30μs，resource100μm往返+dwell10μs。正式attempt2共541.260859854213μs，完全相同primitive/初终态/profile串行992.6458955524499μs，减少45.472916%。resource451.385035698237μs回原位/SLM时data return MOVE仍在途，提前89.875824μs；双带载MOVE重叠190.692518μs。初始外部制备成本未知，0门/0报告，无native调用、旧ENV执行或量子制备。

独立 `tools/audit_modular_aod.py` 使用精确Fraction和Bezier/Bernstein凸包有限细分，按实际START/END切分连续段，无法证明则拒绝；完整备用RF、全部实际atom pair和activeCartesian（含空）对旁观者、LO​​AD未来union/STORE旧union至END保守handoff、全部身份/holder/SLM/ULP时长/依赖/资源都审核。42时间分区、51,612证书（23,562 atom +28,050 Cartesian-spectator）、实际最小保守10μm，运输阈值仍1μm。并行/串行actual journal、轴delta、checkpoint摘要及原初态公开kernel全重放均PASS；两处coldrestore精确最终journal/状态，recording off/on语义相同。资格不是empty-empty RF干涉模型，不含光脉冲、M/RESET、报告或factory。

报告归 `app/modular_aod_report.py`，复用冻结共用payload builder/viewer，只改三项观察器元数据（报告源为空、puretransport scope、独立设备名），完整frames/positions/ops/metrics与原builder字典完全一致。没有改四个kernel、旧ENV、旧single-AOD reviewer或共用viewer；baseline与manifest SHA已核对。

## 实际命令与检查

本机使用显式Python3.12，`-B`，测试 `PYTHONPATH=src;artifacts/lean-kernel-pytest-deps;artifacts/shor15-publication-deps`，不修改共享venv。

- `python -B -m pytest -q tests/test_native_kernel_runtime.py tests/test_native_kernel_audit.py tests/test_native_kernel_view.py tests/test_native_kernel_boundary.py`：85回归PASS。
- `python -B -m pytest -q tests/test_aod_modules.py tests/test_modular_aod_audit.py tests/test_modular_aod_demo.py tests/test_environment_boundary.py`：最终81PASS/6.20s（26+40+3+12）；不同case总数166，不把代理重复运行加入。
- `python -B tools/check_architecture.py --output artifacts/modular-aod-2026-10-05/architecture-check.json`：281modules、0违规。
- `python -B examples/run_modular_aod_demo.py --output artifacts/modular-aod-2026-10-05/attempt2`：真实完成，runtime与独审分开PASS。
- `python -B tools/audit_modular_aod.py artifacts/modular-aod-2026-10-05/attempt2 --output artifacts/modular-aod-2026-10-05/attempt2/independent-artifact-audit.json`：读五份原始产物独审PASS，auditor SHA `107a66755b70022952b7b64f87b49320be002da89ee781af894d065dc2c9f242`。
- `python -B -m http.server 8782 --bind 127.0.0.1 --directory artifacts/modular-aod-2026-10-05/attempt2`：实际loopback服务，共用回放。真实CUA四书签、resource已空/data17在途、自然32×终态双空、主统计展开/明细折叠、原子/trap同步zoom、390/320px文档无溢出、console0错误；截图和 `browser-qa/verification.json` 保存同attempt。
- RAG新增K73/L52及3召回case；最终73chunks/64sources/93queries，当前路径指纹刷新，原raw/historical证据字段保持，`--check`与`--self-test`另记本轮实际输出。

## 失败与修复

首集成72PASS/2FAIL的JUnit保留：实验层错误导入app报告模块，迁到新增app模块，boundary不放宽；安全Bezier测试fixture实际已可证明却错误期望拒绝，修正为确需细分的曲线，证明器不为fixture改变。最终81通过。

正式attempt1物理/恢复通过，浏览器发现共享默认caption错误称QMAP编译与声明测量；新报告adapter改展示元数据并加入全payload一致测试后正式重跑attempt2，新manifest绑定最终source；attempt1及截图不覆盖。总类别tooltip按包含时间区间选首标签的旧行为保留为已知界面限制：设备lane和journal身份准确，不用它代替设备完成证据。

## 发布、限制与下一项

使用授权的GitHub Gitdata能力＋独立git fetch核对parent/tree/全部staged blobs，保持origin pushurl=DISABLED，沿用draft/open/unmerged PR#3，不publish大型run资料，不覆盖原并行工厂目录。本日志与小验收随能力阶段发布，回执另行追加。

本任务只完成可复用独立运输链和global资源协调；尚无交叉域路径求解、midflight新增Block、额外空活动轴、CZ/MZ服务并发或factory资源补产闭环。RESET位置/是否原位服务上一问仍未选择，不在此暗改。下一可执行项是在共享S1–S3 controller接缝用真实entry/exit状态/RF/global依赖/原报告及同token唯一载体，逐项组合服务和运输并独立验收；完整Shor不是本轮完成条件。

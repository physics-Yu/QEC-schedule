# QEC 编译器四步发展与逐阶段验收

状态：AWAITING USER APPROVAL，停止在第四步4A attempt1控件测试入口失败。前三步正式PASS，尚未重试。用户授权按前述四步顺序实施，并明确要求：遇到不能完成或阶段验收失败，要及时弹出失败报告，说明事实、可能原因和拟议重试范围，由用户审批后才能新尝试。不得自行改变策略后重跑掩盖失败。正常搜索候选被排除、预期负例不属于正式阶段验收失败。

1. 固定正确基准与公平对照。冻结现有481槽正式输入、布局、硬件、原始SLM终态、测量分支和验证证据。
2. 持续状态与装卸复用。新增独立策略，保留旧基线；同一输入必须量子/物理合法、完整时间与装卸次数改善。
3. 门批次、运输、读出联合优化。限定预算及候选规则后正式验收，不静默修改基准、终态或物理条件。
4. 泛化验证与纠错扩展。先多线路/非对称布局及故障测试，再按明确噪声模型加入连续纠错与时域解码，最后四逻辑实例。

阶段状态与尝试账本：`artifacts/qec-roadmap/status.json`。失败展示为只读弹窗，不提供自动批准或自动重试；用户审批以本对话明确回复为准。成功阶段可继续下一阶段，失败阶段及依赖它的后续阶段停止；只读诊断和报告允许继续。

## 步骤1：PASS，首次尝试

`C:/python312/python.exe examples/qec_baseline_audit.py` 完成冻结与恢复核验。产物 `artifacts/qec-roadmap/baseline-input.json`、`baseline-contract.json`、`baseline-manifest.json`。研究agent另以只读方式核对保存原始worker/browser文件一致、481效果依赖与顺序、32测量和32RESET的真实随机投影以及终态。合同明确同seed仍须核对分支；阶段正式PASS。

## 步骤2：PASS，首次尝试

新 `motion/qec_persistent.py` 和 `simulation/qec_persistent.py` 与旧基线并存。同组保持AOD捕获，CZ后回捕获位置且SLM关闭；换组、读出和终态显式释放。未改核心物理条件。

首次最小2项 `tests/test_qec_persistent.py` PASS（7.83s）。首次完整 `examples/run_qec_persistent_acceptance.py` PASS：481槽同输入/同投影分支/同条件纠正/同终态，20885.9μs、LOAD/OFFLOAD各45；较基线省1170μs，编译墙钟326.401s较慢。六次复用减少1200μs装卸，AOD单比特资源串行多出30μs；不能声称CZ并行改善。物理和程序正确性检查无意外失败。

`examples/verify_surface_qec.py artifacts/qec-roadmap/step2-attempt1` compiler-free独立重放150plan PASS（203.952s），481效果exactly once、checkpoint精确一致，纠正前XX/ZZ −1/−1、后+1/+1。真实产物和verification在该目录。详细比较见 `docs/qec_persistent_acceptance.md`。

工作台独立 `qec_persistent` 可编辑策略与8783入口已通过，明确区分保存的真实全电路结果和短线路新编译；完整保存结果两种32×播放及实际编辑4门编译PASS，无page error。证据`step2-attempt1/ui-subcheck/browser-acceptance.json`。8783 PID27364，完整保存job `38839edeb9eea6eae376020ca54c7662`，全481未重复编译。步骤2正式PASS。

## 步骤3：PASS，首次尝试

预先合同 `docs/qec_joint_attempt1.md`：同型RAMAN原生批处理、MZ保留AOD的测量复位/运输联合服务选择。核心、候选runner和观察器分别并行实现；首次正式74项测试全部PASS（8.94s），覆盖批光物理/条件/逐事件恢复/负例、读出同分支省装卸/启用SLM后备/内部错误传播、实际recording+Node画光及旧QEC/AOD/CZ兼容。命令与输出见 `artifacts/qec-roadmap/step3-attempt1-tests/pytest.txt`，未跑全库suite。

源码冻结后，`examples/run_qec_joint_acceptance.py` 首次完整481槽对照PASS，同冻结输入/分支/终态；19255.9μs/37轮装卸、Raman33μs、编译206.696s。八次MZ访问各省200μs，加上批光恢复30μs，比步骤2再省1630μs，较原基线总省2800μs（12.70%）。未改变历史AOD_busy排除RAMAN统计口径，AOD真实资源锁保留；详见`docs/batch_raman_contract.md`。

独立`examples/verify_surface_qec.py artifacts/qec-roadmap/step3-attempt1`重放120plan PASS（151.323秒），481效果各一次，checkpoint精确一致；8784（PID28316）真实浏览器首次验收PASS，保存job `03a43acfc3a55199bc9ce6d971d37a92`，全481没有重编译。四移动原子同时H，MZ移动holder读出/复位与无预读、三批混合条件逐目标画光、physical/keyframe两模式32×到终态，以及实际编辑6门编译（1247.6μs）均通过。源码未变、无page errors。

## 步骤4：首次尝试，4A实现中

合同`docs/qec_generalization_attempt1.md`按4A泛化→4B两逻辑带噪重复纠错→4C四逻辑顺序。当前仅实现4A：显式两patch原点输入，新增错开(0,0)/(45,5)、AOD8×14=112布局；首次顺序矩阵为短Clifford线路、X(Q014)/seed23完整GHZ₂、原Y(Q000)/seed7错开布局。脚本`examples/run_qec_generalization_acceptance.py`单次每份编译/独立重放各600s预算，失败保存部分状态并更新待审批账本，未跑矩阵。

4B只读设计记录：推荐显式readout_flip字段、默认false省略的兼容序列化，量子真实投影与报告位分离；三噪声轮+真实完美闭合轮、受限单事件稀疏history译码表（含无需纠正的支持历史），decoder仅读report，未知历史报错。4C需68原子、32码稳定子+XXXX+3条ZZ，不能只验XXXX/ZZZZ或忽略196矩形交点超128容量。两者尚未实现或测试。

## 进度与失败弹窗

只读看板 `http://127.0.0.1:8782/`，PID26780。`examples/qec_roadmap_report.py` 服务只读状态；七项报告/预期负例检查首次PASS，真实Edge显示验证通过。预期失败弹窗测试使用隔离账本，未触发正式阶段失败。关闭弹窗不是审批，页面无批准或执行API。

## 最终停止点：第四步4A首次入口失败，等待批准

`python -m pytest tests/test_qec_layout_origins.py tests/test_workbench_qec_origins.py tests/test_workbench_qec.py tests/test_qec_joint.py -q -x` 首次48 passed /3.66s。随后主任务运行 `node tests/workbench_qec_controls.cjs` 漏传该脚本第19行需要的JSON文件参数，ERR_INVALID_ARG_TYPE，exit1，发生在界面断言前。是主任务命令调用错误；不是物理编译失败，完整矩阵尚未启动。

已立即停止并通知全部agent，不修改代码、不重新执行该检查。只读核对 `artifacts/qec-ui-tests/input.json` 为480门无预置故障模板，适用补参命令；保存hash和拟议命令，待用户批准后才建attempt2。详细[失败报告](../../docs/qec_step4_attempt1_failure.md)，证据在`artifacts/qec-roadmap/step4-attempt1-tests/`。正式账本step4.awaiting_approval，前三步passed。8782实际失败弹窗只读检查已显示且无pageerror；这是报告展示，不是实验重试。

4B/4C未实现，完整4A矩阵未运行；不得把输入测试PASS当全线路可编译证明。所有旧成功服务/动画保持，内存文件未修改。

# 四逻辑比特多轮 QEC 工作台

2026-09-12，4C 开发。当前完成界面接入与控件工程测试，尚未运行本阶段完整物理或真实浏览器验收。旧4B结果及其输入未改写。

新配置为 `compiler=qec_temporal_four`、`layout=surface_qec_ghz4`，68原子包含 Q000–Q035 data 和 Q036–Q067 ancilla。模板按钮及 `?example=surface-qec-temporal-four` 从对应API读取实际电路。四个默认原点为 `(0,0)/(40,0)/(0,40)/(40,40)`；新控件仅在四patch配置显示，旧两原点的缺省与JSON语义不变。

原点编辑只改变明确的几何输入，保持线路、条件、报告翻转及AOD配置。四patch使用独立扩展的SZ平台，AOD仍按模板显式7×14=98配置并分组运输，不扩大128容量限制。跨两/四patch配置的选择明确载入相应模板；同配置内的门编辑不重建协议。

继续支持任意受支持Clifford门、MEASURE/RESET和逐测量 `readout_flip` 编辑。旧单轮故障控件在多轮配置禁用，避免覆盖新协议。结果根据实际报告字段显示 `verified_logical_ghz4`、`logical_xxxx`、`logical_zz_pairs`（AB/BC/CD），并区分160位读出、128位报告历史、真实投影、报告位、实际纠错与译码建议。任何改写不保证仍处于受支持的单事件模型。

工程测试：`node tests/workbench_temporal_four_controls.cjs` 通过，包含四原点修改/撤销、68角色、160/128结果标签、XXXX与ZZ、测量翻转、JSON及其他门/AOD保持。旧两patch `workbench_temporal_controls.cjs` 和 `workbench_qec_controls.cjs` 在本次接入中通过。以上为明确标注的DOM/HTTP替身测试，不是物理或浏览器验收。

已准备但未运行 `examples/accept_temporal_four_qec_ui.py`。待完整编译与独立重放通过后，从新8787服务恢复真实结果，检查双32×完整终态与读出无预读，并真实编辑一份包含报告翻转与RESET的六门短线路编译。短线路预先声明不是完整GHZ₄协议，物理完成与协议正确分别报告。

Python接口也已接通：68原子、四块布局和新策略必须严格配对；四原点经独立四块normalizer处理。构造、角色、运行和结果分别分派至现有四块模块；共享默认AOD保持7×14=98。两个temporal配置允许真实报告翻转，旧三个QEC配置仍明确拒绝。代表模板API固定为seed7、round2_X0_0报告翻转，保存结果恢复允许新策略。

聚焦接口回归：`python -m pytest tests/test_workbench_temporal_four.py tests/test_workbench_temporal.py tests/test_workbench_qec.py tests/test_workbench_qec_origins.py -q`，**51 passed in 4.90s**。新检查涵盖严格配对负例、真实68角色/位置预览、旧SZ未变化、临时端口GET代表模板（不编译），以及零门真实执行→四块summary→无worker保存恢复。没有运行完整四块物理线路或浏览器验收，原运行服务未重启。

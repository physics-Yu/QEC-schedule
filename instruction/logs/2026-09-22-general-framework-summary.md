# 2026-09-22 程序框架系统总结

用户要求：梳理整个程序已实现内容、可复用模块、认识过程中的修改，以及可信基座，形成 general 框架总结。

## 本轮工作

- 根任务检查当前入口、配置与源码；三个只读子任务分别核查环境基座、策略与初态、应用/协议/交付。
- 新增 [程序框架总览](../../docs/general_framework_summary.md)，按当前本地工作区说明四包边界、实际执行链、能力矩阵、演进、配置归属、验证范围与统一接口缺口。
- 校正“当前仍只有整片搬运”的过时概括：该限制属于旧 ordered 控制器；zoned 已按需入区并支持 EZ SLM 驻留；Studio 当前默认 qmap_native。
- 区分作者原生编译、本地完整 Env 执行、Parking portable 运动学与 RL 离散模型，禁止相互替代性能或物理结论。
- 说明没有“绝对正确”的整套软件；可长期保持的是单一状态真值、显式操作、唯一提交、逻辑/物理分离、全部活动交点检查、终态与追溯合同。物理参数须保留模型版本。
- 独立重放与 runtime 共享部分 transition/backend，不能作为独立物理 oracle；特权 env.state 也不是不可信算法隔离沙箱。
- 记录配置说明滞后：原生默认需要额外运行环境，旧 README 安装入口尚未完整说明；未测试新克隆安装失败。

## 本轮核验

1. `C:/python312/python.exe tools/check_architecture.py`：当次216个扫描模块、0违规。
2. `C:/python312/python.exe -m pytest -q tests/test_environment_boundary.py tests/test_foundations.py tests/test_atom_statistics.py tests/test_serializer_equivalence.py tests/test_runtime_prefix_cache.py`：74 passed，24.87秒；1个第三方日期API弃用警告。
3. 交付审查子任务 `python tools/check_demo_bundle.py`：134文件完整性PASS。

没有重跑全部实验、大规模原生编译、QEC全矩阵或真实GUI。其他实验数字和通过记录来自已有产物/专项文档。本轮不修改源程序、模型、默认配置或策略行为，也不提交推送。工作区原有大量未提交改动保持；本总结不是GitHub发布声明。

## 后续建议

优先统一能力与结果合同、evaluator适配和作业入口，区分每个入口的默认策略及验证层级。interaction IR、初态/动态落点、驻留和原生适配的局部进展不表示已完成统一调度循环。多轮syndrome周期优化仍为后续策略工作，不应成为环境固定行为。

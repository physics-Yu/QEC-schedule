# Canonical QEC 层与中性原子后端合同

`neutral_atom_experiments.qec_pbc.backend_contract` 是纯接口与静态审查模块，不修改实时环境或平台参数，不生成运输计划。

## 已实现

- `CouplingLayer` 保存有向 CNOT 配对；一层要求各原子至多出现一次。
- `layer_requests` 绑定 physical IDs，输出有向配对、无向 CZ 配对、H target 与前驱层。`canonical_layer_requests` 通过结构读取 canonical memory couplings，不修改其协议或编号。
- `lower_coupling_layers` 生成现有 `PhysicalCircuit` 耦合片段：H(target) → CZ → H(target)，相同阶段允许并行，阶段/层边界保留全部前驱。该片段不含完整制备、测量、RESET 或 detectors；完整协议仍由 canonical frontend 提供。
- `AncillaLifecycle` 区分 reuse 与 fresh。单块 d=3、R 轮最低角色数分别为 17 与 9+8R，不含备用原子和其他 blocks。
- `preflight` 审查容量、measurement zone、reuse RESET、global CZ 能力。通过只说明能力条件满足，不证明可路由或容错。
- `validate_global_cz_pairs` 枚举所有 eligible EZ live atoms，包括 spectators，严格要求实际距离作用集合等于请求集合。半径来自调用者，不内置论文/项目数值。仍需现有 backend 检查支撑、运动与资源。
- `validate_aod_rectangle` 核对启用行×列的完整交点捕获集合，拒绝只选对角原子而忽略附带原子；显式提供刚性 offset 时拒绝形变。空交点合法不代表可跳过空 trap sweep 校验。

## 边界与下一步

四个逻辑耦合层不等于四个全局物理 pulse。每层有六对 CZ 的 d=3 模板必须先获得可执行 placement，再经全作用对审查；需要拆批时也必须保留原协议的 wire 顺序。接口无任何 duration 估计，不声称批量运动或完整 canonical memory 物理执行成功。

下一步由策略层消费 `LayerRequest`，生成有界 placement/运输候选，交给现有独立 validator 和 Executor；逐 pulse 记录 intended/actual pairs 与状态版本，最后与完整 canonical physical DAG 的 gate IDs 对齐。现有稀疏串行 memory 是执行链路对照，不代表新并行模板已完成物理验收。

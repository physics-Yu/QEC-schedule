# d=3 码块布局、码内并行与 Enola 初始放置

本阶段已把 d=3 码块的同层 CZ、初始化 RESET 和综合征读出编译为真实合批操作，并完成单块及 12 块的原初态完整重放。标准布局的单块在相同初态、相同线路上，实际模型终态时间从 **84,684.130701 μs** 降到 **40,504.465183 μs**。冻结的 Enola 初始放置加本项目物理适配，单块与 12 块均得到 **33,409.196973 μs**；这组改变了初始布局，应作为另一种布局与编译组合比较。12 块已完成 3,006 门、413 次投影和两层独立物理审计。

这是保存的 Shor15 线路中“编码初始化与第一轮标准综合征提取”的物理前缀。本文不表示完整物理 Shor、magic factory、带噪质量或容错验收已经完成。后续主线继续遵守[工厂供应与逐周期质量协议](../instruction/qec_factory_pipeline.md)。

## 线路与平台范围

每个算法码块使用 9 个 data 和 8 个 syndrome 辅助原子，辅助角色分为 X0–X3、Z0–Z3。单块输入保留 249 个算法 native gates；右侧资源区保留同一保存源中的 17 个 RESET 和 1 个 H，并停在其第一个 T 前。因此本阶段单块对照都是 **267 个 native gates、50 次投影、34 个原子、两台 AOD**：

| 项目 | 数量及含义 |
| --- | --- |
| CZ | 68 个 authored gates：44 个 CSS 编码 CZ、24 个标准提取 CZ |
| H | 149 个 authored gates：算法 148、资源前缀 1 |
| MEASURE | 8 个 syndrome native readouts |
| RESET | 42 个 native resets：算法 25、资源前缀 17 |
| 投影 | 50 次，包含 8 次 MEASURE 和 42 次 RESET |
| 资源状态 | 一个未编码物理 `|+>`，其他 16 个载体为零态；尚不是 magic state 或可消费库存 |

算法和资源共用一个全局状态与时间线。算法 AOD 为 `AOD_0`；右侧资源使用独立 `AOD_MAGIC`，工作 envelope 分离。资源区的 X/Z 角色标签来自源模板，不表示这些原子已构成编码资源块。

本阶段采用显式研究模型：统一 COMPUTE 权限区和独立 MZ；固定 **5 μm SLM 候选格点**；实际 home 间距至少 **10 μm**。仅实例化实际使用的 home SLM 支撑，其余候选点不启用。算法码块按 80 μm pitch 复制；单块使用 3×3、20 μm 相对轴偏移的 rigid AOD。12 块按 3 列×4 行复制，对应 **9 列×12 行、108 个 AOD 交点**，包含空交点和关闭的备用行列。

物理时间使用项目配置：MOVE 为 0.5 μm/μs，LOAD/OFFLOAD 各 100 μs，开关 1 μs，CZ 0.3 μs，Raman 1 μs，MEASURE 500 μs，RESET 100 μs。它们是模拟假设，不是设备标定。预先安排初始布局的制备成本未计入；本阶段开始后的全部开关、空载定位、装卸、运动、读出和归还计入终态时间。编译程序的 wall seconds 与这些物理 μs 分开记录。

## 标准协议保持，合批由真实几何决定

协议来自固定的 canonical d=3 模板。四个 syndrome 交互层分别有六个互不共用原子的 authored CZ，共 24 对；每层的目标 H、CZ、目标 H 和层间屏障保持，CSS 编码门序保持。改变的是合法调度批次和物理路径，不改变 hook 次序、稳定子支持、native ID 或测量报告 ID。

标准布局按 canonical 坐标乘 10 μm，data 位于 odd/odd 坐标，辅助原子位于 even/even 坐标。AOD 只能开启整行与整列，活动交点是两组轴坐标的 Cartesian 积。因此两个请求原子能分别对齐，并不保证它们可以一起装载：例如 X0/X1 的两行两列会同时开启 Z0/Z1 所在交点。编译器必须拒绝额外捕获，再选择闭包完整的较小子组。

| canonical 层 | 标准布局实际 CZ 脉冲 | 标准布局每脉冲对数 | Enola 布局实际 CZ 脉冲 | Enola 每脉冲对数 |
| --- | --- | --- | --- | --- |
| 1 | 1 | 6 | 2 | 3、3 |
| 2 | 4 | 2、2、1、1 | 2 | 3、3 |
| 3 | 4 | 2、2、1、1 | 2 | 3、3 |
| 4 | 1 | 6 | 2 | 3、3 |
| 一轮合计 | 10 | 共 24 对，最大 6 对 | 8 | 共 24 对，最大 3 对 |

表中的 2、2、1、1 是层内批次大小统计，不表示任意重新排列协议门。每一实际批次仍需从 READY frontier 选取。

`--intra-patch` 开启同层、同 rigid 位移的闭包完整 CZ 合批；`--intra-services` 另行开启同类型 MEASURE/RESET 合批。服务选取器分别枚举至多 9 个 data 类的 511 个非空子集、8 个 ancillary 类的 255 个非空子集，选择受限策略内 native gate 数最大的合法子集。一个 local role 在所有已 READY 的码块中的 gate 始终整束选取，data 与 ancillary 不混合；输入状态、gate 身份和显式依赖保持。

标准布局的初始化算法 RESET 可分为 data9、aux6 和两个 boundary 单角色，即四次算法 MZ 访问；最终辅助测量分为 aux6 和两个 boundary 单角色，即三次访问。Enola 布局对应 data5/data4/X4/Z4，辅助测量对应 X4/Z4 两次访问。首批算法 RESET 可与右侧 17 个资源载体真实同步运输，待两台 AOD 都静止于 MZ 后执行一个联合 RESET。MEASURE 后已经具备依赖的同载体 RESET 可在同次 MZ 访问真实执行，再卸载回原 SLM。

## Enola 的使用范围与冻结来源

本阶段只调用作者未修改的 **初始 SA placer `place_qubit`**。输入是相同 canonical 四层的 24 对 syndrome 耦合、17 个角色、5×5 放置格、10 μm home pitch、seed=0、`l2=False`。未调用作者完整 scheduler 或 code generator。实际门配对、rigid AOD 捕获、路线、服务合批和物理执行由本项目适配。

官方来源固定为 [UCLA-VAST/Enola 的 placer.py](https://github.com/UCLA-VAST/Enola/blob/2944dbf4e163e8d2eeeec607add0d9139edce689/enola/placer/placer.py)，commit 为 `2944dbf4e163e8d2eeeec607add0d9139edce689`，源码按 BSD-3-Clause 使用。冻结提案见 [enola_patch_proposal_2026_10_04.json](../references/qec_pbc_validation/enola_patch_proposal_2026_10_04.json)。

| 冻结对象 | SHA256 |
| --- | --- |
| 官方 placer.py 原始字节 | `d256c84490bd72d525515f24acb081d7b21bcd5f7bbc31302a3bbf79a16997cf` |
| 提案 JSON 原始字节 | `b04b39ba29e6345c26404d289b6d3b441e1f3a92d9fb7ab249cd1b9b2d1b68ae` |
| 规范化输入 | `5e2230100c4e8afd78b64d438631e779bdee338946a85c962d5dcdce9a4011ed` |
| 角色到 μm 坐标映射 | `49a2c2d531af2bad5e77d8d368c6809dd8386ffe19c3fe166c7e23882b44337c` |

适配器验证协议模板 hash、role 顺序、全部 24 对及分层、site/SLM/μm 坐标一致性、间距、官方版本声明和 placement hash。新增记录功能后的物理运行另保存 `producer-source.json`，绑定调用选项与实际 Python 生产模块字节；此前 standard baseline/CZ-only 的历史运行明确 not recorded，不倒填当前代码身份。冻结提案自身仍只是放置证据。

作者的距离目标与实际物理时间要分开：

| 提案比较 | 顺序填格初始映射 | 官方 SA 提案 |
| --- | --- | --- |
| 加权 site 距离 | 50.6052672685 | 20.4 |
| 24 对无权重距离总和 | 596.2475012515 μm | 240 μm |
| 该提案字段中的执行时间/质量 | null | null |

加权规则为 `max(1 - 0.1 × zero_based_layer, 0.1)`。这两项是 placement 距离指标；其顺序填格映射也不是下文 canonical 物理基线。距离下降不能换算成物理 μs 或 fidelity。下文的物理时间来自独立运行的 Executor 与完整 replay。

Enola 物理适配通过 `--pair-search` 在原 authored CZ 的两端中选择移动端，并枚举八个明确偏移：`(±3,0)`、`(0,±3)`、`(±3,±3)` μm。故实际伙伴距离为 3 或约 4.243 μm；同 rigid 位移、精确捕获和全局非配对间距均合格时才允许成批。CZ 的物理作用距离始终为 **6 μm**。

## 已完成的单码块对照

下列四组均保留相同 267 个原门与 50 次投影，已通过源身份、原生效果恰好一次、原初态完整重放和独立前缀审计。终态时间包含最后归还。物理脉冲数量与 authored gate 数量分列：

| 运行 | 布局及选项 | plans | 全部 CZ 脉冲 | 一轮 syndrome CZ 脉冲 | 最大同批 CZ 对 | 终态时间 μs |
| --- | --- | --- | --- | --- | --- | --- |
| `single-baseline-attempt3` | interleaved；逐角色服务 | 196 | 68 | 24 | 1 | 84,684.130701 |
| `single-intra-attempt3` | 同布局；`--intra-patch` | 182 | 54 | 10 | 6 | 79,207.855129 |
| `single-all-intra-attempt1` | 同布局；加 `--intra-services` | 164 | 54 | 10 | 6 | 40,504.465183 |
| `single-enola-attempt1` | Enola；两项合批及 `--pair-search` | 161 | 52 | 8 | 3 | 33,409.196973 |

前三组 `initial.json` 原始字节 SHA256 均为 `d6680c959427e2c5ecc9639c4342508ef45c429eef83921b88c9c2fcda60def5`，`prefix-circuit.json` 均为 `98aa857a1abf155c28413b2eec8af99487f768e0c6f9a41b2af010b4d6541b16`。因此 CZ 合批单独减少约 6.47% 时间；再合并 MZ 服务后，相对同初态基线减少约 52.17%，约为原时间的 1/2.09。

Enola 保留相同线路字节，但初态 hash 为 `2e238fd478942bfb687f2c8db505f48078c1d443e65c6fcd4cc837f51ecb99f6`。其时间比标准布局全合批少约 17.52%；这一差异同时包含布局与配对策略变化，不能称为同初态加速或归因于官方 placer 单独执行更快。

| 占用类别 | 逐角色基线 μs | 标准布局全合批 μs | Enola 全合批 μs |
| --- | --- | --- | --- |
| MEASURE 忙时 | 4,000 | 1,500 | 1,000 |
| RESET 忙时 | 2,500 | 700 | 600 |
| Raman 忙时 | 103 | 103 | 103 |
| CZ 忙时 | 20.4 | 16.2 | 15.6 |

表中的忙时是实际脉冲占用，不包括各类往返运输。主要时间改善还来自减少装卸和 MZ 访问；native RESET/MEASURE 均未被删除。并发资源 busy 时间不能直接相加当作 wall time，应按实际区间并集及终态时钟解释。

## 复现与审计

在仓库根目录使用已安装本项目测试依赖、可导入 `src` 的 Python 环境。Windows PowerShell 可先设置 `$env:PYTHONPATH='src'`；NumPy、Stim 等依赖按项目既有环境配置。每次 `--output` 使用不存在的新目录，不覆盖历史成功或失败证据。

从已提交的小型保存源 packet 运行单码块四组：

```powershell
python examples/run_parallel_shor15_prefix.py `
  --source references/qec_pbc_validation/shor15_native_prefix_seed0_2026_10_04 `
  --output artifacts/my-patch-baseline --patches 1 --layout interleaved

python examples/run_parallel_shor15_prefix.py `
  --source references/qec_pbc_validation/shor15_native_prefix_seed0_2026_10_04 `
  --output artifacts/my-patch-cz --patches 1 --layout interleaved --intra-patch

python examples/run_parallel_shor15_prefix.py `
  --source references/qec_pbc_validation/shor15_native_prefix_seed0_2026_10_04 `
  --output artifacts/my-patch-all --patches 1 --layout interleaved `
  --intra-patch --intra-services

python examples/run_parallel_shor15_prefix.py `
  --source references/qec_pbc_validation/shor15_native_prefix_seed0_2026_10_04 `
  --output artifacts/my-patch-enola --patches 1 --layout enola `
  --proposal references/qec_pbc_validation/enola_patch_proposal_2026_10_04.json `
  --intra-patch --intra-services --pair-search
```

默认运行包含实际右侧资源前缀，并进行完整 replay。`--algorithm-only` 改变输入及成本范围，不能与本表直接混比；`--skip-replay` 留下明确未验收项，不能用作通过证据。

独立审计后再打开共用空间回放：

```powershell
python tools/audit_native_parallel_physical.py artifacts/my-patch-all `
  --output artifacts/my-patch-all/independent-audit.json
python tools/audit_patch_parallel_layout.py artifacts/my-patch-all --mode layer `
  --baseline artifacts/my-patch-baseline `
  --output artifacts/my-patch-all/patch-parallel-audit.json

python tools/audit_native_parallel_physical.py artifacts/my-patch-enola `
  --output artifacts/my-patch-enola/independent-audit.json
python tools/audit_patch_parallel_layout.py artifacts/my-patch-enola --mode enola `
  --proposal references/qec_pbc_validation/enola_patch_proposal_2026_10_04.json `
  --output artifacts/my-patch-enola/patch-parallel-audit.json
python examples/serve_native_parallel.py --run-dir artifacts/my-patch-enola --port 8773
```

逐角色基线审计使用 `--mode role`；CZ-only 使用 `--mode layer`。`--baseline` 比较要求 `initial.json`、源和线路的原始字节全部相同。Enola 对标准布局不使用该同初态比较参数。

浏览器书签定位真实初始 placement、MZ RESET、共同 H、并行 CZ、MZ 综合征读出、双 AOD 带载运输、四个稳定子层和最终归还。共用 viewer 继续使用[同步缩放与统计层级合同](qec_viewer_presentation.md)：原子仅比 trap 稍大，X/Z 标识持久显示，主统计和类别/设备时间优先，逐项详情默认折叠。

如需重新调用作者 placer，可使用新的输出目录；源码目录须包含固定版本的 `enola/placer/placer.py`：

```powershell
python tools/propose_enola_patch_layout.py --source PATH_TO_PINNED_ENOLA `
  --output artifacts/my-enola-proposal --width 5 --height 5 --seed 0
python tools/audit_enola_patch_proposal.py `
  --proposal artifacts/my-enola-proposal/proposal.json `
  --output artifacts/my-enola-endpoint-audit
```

提案可重新生成规范化 input/placement hash，但 wall time 等元数据会改变原始 JSON 字节。端点与捕获审计仅用于筛选；完整运输与物理通过证据仍需实际 Executor 和原初态 replay。

## 安全与证据边界

实际执行保持有限全局 CZ：每个 pulse 全部存活 COMPUTE 原子的实际作用对必须精确等于 authored batch，包括右侧旁观载体。驻留及每个 CZ pulse 的非配对原子间距至少 10 μm；这个设计条件不会把 CZ 距离扩大到 10 μm。运输过程使用物理底座的连续 1 μm 碰撞/SLM clearance 校验，不声称所有运动段始终保持 10 μm 间距。

活动空 AOD 交点也参与连续 sweep；装卸必须覆盖全部实际捕获集合并保持双支撑。关闭的备用轴仍受世界边界、envelope、轴序和间距约束。Raman 寻址保持 5 μm separation，MEASURE/RESET 在真实 MZ、稳定 SLM 或静止 AOD 上执行。只有 Executor 提交 holder、量子投影与报告。

单块独立前缀审计验证 native ID/效果、50 次源投影、799 条依赖区间、真实 MZ 几何、Raman 分离、全局 CZ pair set 和独立 signed Stim 态。单块布局审计另外固定 canonical 16 个 phase、488 条提取依赖边、136 个 CSS native gates，以及每层脉冲数、真实 row/column 运动、初态与 recording hash。连续碰撞/支撑正确性由 Executor 与完整原初态 replay 验证，不能由抽样动画或端点检查代替。

运行保留 `initial.json`、平台/placement、原线路/phase、已接受 plans、trace、终态 checkpoint、decisions、recording 和独立审计，新增记录功能后的运行还保存 `producer-source.json`。历史 `attempt1/2` 等失败或中间尝试保留，表格只引用上述已通过目录。观察器重新生成不改变实际物理记录；报告必须匹配独立审计绑定的 recording 字节。

## 12 码块扩展：实际执行、重放与独立审计

最终本机[8774空间回放](http://127.0.0.1:8774/)已逐项验证11书签、四真实稳定子层与双AOD带载运输；390/320px无水平溢出，主统计展开、细项折叠，临时viewport已恢复，console无错误。同步缩放/fit两项Node检查对本次完整12块recording通过；旧8773页保留。

`full12-enola-attempt1` 已按同一冻结提案与同一物理适配完成 **3,006 个 native gates、413 次投影、221 个原子、两台 AOD、161 个 plans**。算法 AOD 为 9 列×12 行、108 个交点，右侧资源 AOD 独立。所有 producer 检查均为 true，包括全部门效果恰好一次、DAG 完成、事件队列清空、终态 code/logical/auxiliary 条件、源报告 ID、资源停于首 T 前和完整原初态 plan replay。

两组 12 块运行的实际结果如下；Enola 组同时改变布局、配对选择和 MZ 服务合批，表格不用于同初态加速归因：

| 运行 | 选项范围 | plans | 全部 CZ 脉冲/原生对数 | 最大同批 CZ 对 | 一轮 syndrome 脉冲 | 终态时间 μs |
| --- | --- | --- | --- | --- | --- | --- |
| `full12-intra-attempt1` | 标准布局，CZ-only 合批 | 182 | 54 / 816 | 72 | 10 | 79,207.855129 |
| `full12-enola-attempt1` | Enola 布局、配对搜索、CZ 与服务合批 | 161 | 52 / 816 | 36 | 8 | 33,409.196973 |

Enola 四个 canonical 层各使用两个全局实际脉冲，每个码块每个脉冲各 3 对，十二块同步即 36 对；一轮共 288 个 authored syndrome CZ。44 个 CSS 全局脉冲另覆盖 528 对，合计 52 个脉冲实现全部 816 个 CZ。标准布局的层脉冲数为 1/4/4/1，最大 72 对来自十二块各 6 对同步；完整 native 线路保持。

两组 `independent-audit.json` 与 `patch-parallel-audit.json` 都为 `passed=true`。独立审计核对 3,006 次 committed effects、413 次投影、9,401 条依赖区间、192 个 canonical phase、5,856 条 canonical 依赖边及 1,632 个 CSS 原门。Enola 的 479 条 committed MOVE、16,304 个载体端点和 1,263,304 个 CZ 时非配对距离检查保持最小 10 μm；连续支撑、原子与空阱扫掠通过实际 Executor 和原初态完整重放验证。

Enola 实际 `recording.json` SHA256 为 `2ea57024eb909b045e5ddd8501491fdce2cc549fc9cfef0161f42c488aa577d8`，与两层审计绑定的字节一致；标准 CZ-only 的对应 SHA 为 `9a64e346d7da4ee1e15c50a3fa018e7d3938485e7e96caa8e57ccb8043b9835d`。本段确认物理执行和独立审计，新增布局的真实浏览器呈现验收另记其证据。

12 块与单块 Enola 恰有相同模型终态时间，来自本声明复制阵列下同角色同步装卸、rigid 位移和同脉冲服务。这不表示任意规模时间不变，也不构成完整 Shor 的十二倍加速证明。可用下面的命令复现：

```powershell
python examples/run_parallel_shor15_prefix.py `
  --source references/qec_pbc_validation/shor15_native_prefix_seed0_2026_10_04 `
  --output artifacts/my-full12-enola --patches 12 --layout enola `
  --proposal references/qec_pbc_validation/enola_patch_proposal_2026_10_04.json `
  --intra-patch --intra-services --pair-search --wall-budget 1800
```

完成后按前文命令分别运行 core 和 `--mode enola` 布局审计，再生成共用报告。单块成功、108-cell 容量声明及此前 legacy 布局的 12 块结果，都不能替代本轮新几何的实际执行与原初态重放。

## 后续跨码块中心配对的受限几何条件

冻结的 Enola 布局中，中心 data `d4=(20,20) μm`，四个相邻辅助原子为 `X0=(30,20)`、`X1=(10,20)`、`Z0=(20,30)`、`Z1=(20,10)`，各距中心 10 μm。如果中心保持原 home、四个辅助原子也保持原 home，只有一个外部伙伴移动来与中心执行 CZ，则有限 6 μm 作用距离与非配对 10 μm 条件不能同时满足。

令外部伙伴相对中心为 `(x,y)`，`r²=x²+y²`。四个非配对距离平方为 `100+r²±20x`、`100+r²±20y`；要求它们都至少为 100，得到 `r²≥20|x|` 和 `r²≥20|y|`。因此 `r²≤2(r²/20)²`：非零 `r` 必须满足 **`r≥√200≈14.142 μm`**，超过 CZ 上限 6 μm。`r=0` 则是两个原子重叠，被碰撞/clearance 条件排除。

这是一条固定中心、固定四旁观辅助位、单移动端的必要条件，不是整个布局或所有跨码块协议无解。后续中心到中心等跨 patch 耦合需要显式 interaction staging、移动中心载体或搬移并归还必要的旁观辅助原子，再重新验证全部捕获、连续路径、支撑、旁观作用对和依赖。不能靠放大 CZ 距离或在动画中隐藏辅助原子处理。

该限制不影响本阶段已通过前缀：syndrome 配对时对应辅助原子自身移动，腾出其方向；CSS 编码可选择中心 data 作为移动端，使用合格 data 作为锚点。局部解析证据保存在 ignored `artifacts/patch-parallel-2026-10-04/enola-center-pairing-bound.json`，其中明确记录冻结提案/placement/初态 hash、上述假设与推导；它本身不是物理执行尝试，也不替代未来 staging 的实际验收。

本阶段范围仍为理想 Clifford 物理前缀。按最新[共享协议v2](../instruction/qec_factory_pipeline.md#当前任务目标纯调度模拟)，后续主线是完整工厂调度模块→同token单injection闭环→完整processor按需接入（S1–S3）；报告源明确声明并在合法读出完成后由Executor提交，不要求运行时量子态/Born后端。独立量子参考、噪声/decoder/质量、MSC与完整Shor工作负载分别验证；本轮没有新增工厂、库存交付或injection完成证据。

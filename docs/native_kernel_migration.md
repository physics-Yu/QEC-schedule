# QMAP 原生编译与轻量运行内核

2026-10-04：独立内核首阶段完成；完整工厂接入和完整物理 Shor另行验收。

新主路径是 `冻结协议/controller → QMAP C++ → Operation流 → KernelExecutor → 增量journal/反馈`。QMAP负责酉块的排布、分组和路由；Python轻量运行器负责持续位置、holder、时钟、完成集合和声明报告。日常推进不调用旧 NativeProgramAdapter、ProgramBuilder、SimulationState、候选搜索或全trace审核，也没有静默旧策略fallback。

实测两轮218门、1123操作、25报告完成，48对CZ组成8个脉冲、每脉冲最多6对；独立几何与原初态逐block重放PASS。相同操作流录制关闭/开启推进分别0.154/0.261秒，离线审核0.119秒；两次C++调用合计0.00972秒，首次库加载0.36秒左右。物理模型总时间82.554毫秒，不能与Python墙钟时间混用。123项测试及277模块架构检查通过。

## 接口与职责

| 层 | 入口 | 职责 |
| --- | --- | --- |
| 原生编译 | `strategies.native_kernel.compile_native` | 调用真实QMAP C++，保留原门ID、完整依赖、版本化请求与NAViz |
| 指令转换 | `lower_native` / `finalize_operations` | 对齐原源门、原生端点及作用对，显式补空设备/备用RF轴定位与计时 |
| 执行 | `neutral_atom_kernel.KernelExecutor` | bind_block、run、observe、activate_fragment、wait_until、checkpoint/restore |
| 离线审核 | `neutral_atom_kernel.audit.audit_operations` | 固定初态和指令流的连续几何、全Cartesian活动交点、作用对及时长 |
| 观察器 | `app.native_kernel_view.export_native_kernel_view` | 只读提交增量，导出共用回放；不构造旧环境状态 |

Block绑定当前版本与滚动摘要。错误身份、未就绪依赖、过期提交、重复效果、错误carrier和提前报告继续拒绝。MEASURE结束时才提交声明位；RESET保留历史报告及原子身份。Checkpoint独立摘要绑定全部内容；恢复还重现声明报告、核对测量完成绑定、时间、源游标与有记录部分，不在热事件路径重扫历史。完整性checksum不是外部真实性签名。

Controller继续拥有库存、token、carrier、epoch、frame、接受拒收和processor请求。它只读Observation并激活后续fragment。旧ENV仍留在历史工作台/兼容入口；新内核不导入它，离线导出只复用原共用viewer。完整工厂入口迁移由协作工厂任务接入，不将内核资格例宣称为工厂资格。

## 首个资格例

标准rotated d=3、9 data + 8 X/Z syndrome辅助原子，完整两轮Z memory，包括初始RESET、四层CSS/H边界、读出RESET、跨段实际衔接和终端data读出。原始canonical源门和依赖保留，不把该17原子demo的局部服务模式当作任意factory协议；工厂显式全测量barrier必须保持。

平台 `native-kernel-d3-paired5-sz10/v1` 为单native AOD_0，有序8×16 RF轴与显式selective transfer。SZ节距10μm；EZ配对SLM距离5μm、列节距20μm/行10μm；SLM候选格点5μm。有限CZ为6μm，非伙伴至少10μm，Raman寻址至少5μm，运输连续间距1μm。10μm用于非作用伙伴；实际CZ伙伴必须进入有限作用距离。

时间采用项目声明模型：装卸15μs、CZ0.36μs、1Q1μs、搬运 `200*sqrt(max_full_RF_axis_displacement/110)` μs，M500μs、RESET100μs。关闭轴也保留实际位置并计时。MZ在y130–180，逐原子选最近合法5μm点，显式2.5μm偏移服务通道。参数是实验profile，不是普适硬件测量。

QMAP当前公开接口没有live初始placement；两段之间必须执行实际buffer permutation并支付运输成本。它目前不分配多AOD；IR设备ID不等于原生双AOD已实现。报告源为`canonical-scheduling-zero/v1`，仅验调度报告语义，quantum_projection=False、fidelity=null。

## 复现和证据

在装有QMAP3.5.0/Bench2.1.0的Python环境中运行：

```powershell
python examples/run_native_kernel_memory.py --output artifacts/native-kernel-2026-10-04/d3-two-rounds-attempt2 --rounds 2 --wall-budget 120
python tools/audit_native_kernel_memory.py artifacts/native-kernel-2026-10-04/d3-two-rounds-attempt2
```

输出initial原协议、两份native请求/NAViz、operations、blocks、journal、inflight/final checkpoints、严格离线audit、共享replay.html、增量recording.json及完整源码/产物SHA manifest。严格审核失败会使CLI非零退出。回放X/Z角色、同比缩放、主要时间统计、逐项默认折叠保持，报告随时间只在读出完成后出现，倒放不泄漏未来位。

实测、测试和浏览器回执见 `references/qec_pbc_validation/native_kernel_2026_10_04.json`；详细日志见 `instruction/logs/2026-10-04-native-kernel-migration.md`。原attempt0保留为审核发现修复前证据，不覆盖。

## 当前边界

已交付独立执行内核、版本化native请求、显式MZ服务、持续状态/恢复、增量观察及固定profile离线资格。完整143原子factory、持续库存/injection/processor默认入口、native双AOD、完整physical Shor和含噪容错质量仍按S1–S3单独验收。新内核执行快不等于更短的物理模型时间；录制和严格审核单独计时。

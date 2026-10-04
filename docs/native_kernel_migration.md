# QMAP 原生编译与轻量运行内核

本文记录 QMAP/freeze-v4 的已验收组件与复现 API。当前用户目标已改为[Enola＋MZ 同区协议](qec_enola_mz_design.md)，新 backend 未实现；下述分离 SZ/EZ 的 memory 回放不能当作该目标的 demo，也不能直接循环为纯 syndrome。

2026-10-04 当前资格为 `d3-global-ez-attempt5`、平台 `native-kernel-d3-global-ez-paired5-sz10/v2`。全 x EZ、显式事件起止、共同三次运动及独立审核已通过；完整工厂、injection/processor 和完整 physical Shor 继续分别验收。

路径是 `冻结协议/controller → QMAP C++ → Operation流 → KernelExecutor → 增量journal/反馈`。QMAP负责酉块排布/分组/路由；Python紧凑内核维护真实位置、holder、时钟、依赖完成与声明报告。推进不调用旧NativeProgramAdapter、ProgramBuilder、SimulationState、候选搜索或全trace重审，无静默旧策略fallback。

## 当前资格与历史

实际17原子、两轮canonical Z memory有218源门、1123操作、25完成报告；48对CZ组成8个脉冲、max6同步，模型终态 **82,554.39152192436 μs**。独立核对66source/14artifact、原源GateSpec与2native段、7blocks、196alignment操作/16,027.92007011722 μs、inflight/finalcheckpoint和2261journal精确重放，全RF/Cartesian/有限作用对/MZ审核PASS。t=0为声明初态，外部制备成本未知。

recording off/on同流推进 **0.226291/0.377402 s**，strict离线 **0.148458 s**；两次C++ compile合计 **0.008824 s**、cold import **0.365402 s**单列。native入口整体0.382874 s，lowering0.017355/fullRF0.137625/export0.372532 s。这些墙钟与μs模型时间不混算，未测同输入legacy加速比。最终171pytest/5.95 s、277modules/0violations通过。

[可移植摘要](../references/qec_pbc_validation/global_ez_kernel_2026_10_04.json)与[追加日志](../instruction/logs/2026-10-04-global-ez-scheduled-kernel.md)保存实际来源、失败和边界。旧v1/123tests/attempt2保持当时局部EZ/串行组件快照，不作为当前平台资格。首能力[ff9ab421](https://github.com/physics-Yu/QEC-schedule/commit/ff9ab421a6450eff5610aabe11aabf6f304f3000)已独立fetch核对parent/tree/32blobs，[历史回执](../references/qec_pbc_validation/native_kernel_publication_2026_10_04.json)保留；当前v2发布由root另验。

## API、并发与原生批次

| 层 | 入口 | 职责 |
| --- | --- | --- |
| 原生 | `compile_native` | lazy加载QMAP3.5/core/Qiskit，缓存bindings/architecture，每request实际compile |
| 转换 | `lower_native` / `finalize_operations` / `schedule_operations` | 原源ID/参数/完整依赖对齐；原生端点不改；补空AOD/fullRF后绑定起止 |
| 执行 | `KernelExecutor` | bind/run/observe/evaluate/fragment/report/checkpoint/restore |
| 审核 | `audit_operations` / `tools/audit_native_kernel_memory.py` | 独立连续几何、完整源与精确block/journal重放；不调用native求解 |
| 观察 | `export_native_kernel_view` | 只读增量、当前轨迹、完成报告与共用viewer |

Operation携带block-relative `start_us/end_us`、operation-ID `depends_on`、附加`resources`与`motion_profile`；`bind_block(..., execution_mode='scheduled')`执行明确并发。核心atom/AOD/光资源强制派生，不能省略。独立同型SLM1Q与无关运输、MZ读出与另一原子LOAD/MOVE重叠、多个inflight冷恢复由专项测试验证。Controller继续拥有token/carrier/epoch/frame/库存，只通过Observation和fragment续接。报告仅MEASURE完成提交，RESET保留历史报告和身份。

NAViz `@+` 在上一instruction END后开始，`[]`目标共享start/end，不能拆为逐原子串行。[官方格式](https://raw.githubusercontent.com/munich-quantum-toolkit/naviz/main/docs/file_format.md)、[固定3.5 codegen](https://raw.githubusercontent.com/munich-quantum-toolkit/qmap/v3.5.0/src/na/zoned/code_generator/CodeGenerator.cpp)。本例每native段180instructions：56单目标u、24LOAD/72MOVE/24STORE/4CZ，19LOAD/57MOVE/19STORE为[]同步batch，maxMOVE9atoms，没有multi-target1Q。原生END链不等于一般并发；不伪改独立@+u同时，也不虚构native多AOD。

先finalize完整CONFIGURE/fullRF时长，再`schedule_operations(operations, start_us=0.0)`；helper显式end精确复用于下一start。blocks保存原relative payload，flatten分别加epoch到start/end，不能从absolute减回源payload。attempt3一ULP加法关联导致假依赖未完成已修复；duration仅允许IEEE-754表示误差，zero duration端点相同，不给物理或依赖加宽容。

mandatory原请求schema/version/compilerSHA、manifest、NAVizSHA、原源GateSpec/mapping/architecture/barriers/routing/config与schedule/illumination/motion合同独立重建。缺manifest、只改SHA、重算摘要后的伪源、非法同批依赖拒绝。跨wire依赖sidecar保留，不把1Q-only barrier当native强CZ层边界。校验和是复现完整性，不是外部真实性签名。

## 全 x EZ、trap与共同运动

[全带合同](qec_global_ez_contract.md)为权威：world x −20…200 μm、EZ y50…80 μm，profile/QMAP/lowerer/reviewer/viewer一致。CZ核对带内所有存活原子及全部有限距离对，任何holder、算法/工厂/缓存或named box都不豁免旁观者。原生rectangle保留provenance，有效照明全带由profile独立核对。

SLM sites另按显式inventory/site regions声明，5μm格点不自动填充world/compute，隔离带不能从宽照明推trap。原生SZ10μm，paired EZ x=0/5+20k、y60/70，伙伴5μm；单AOD_0为有序8×16全RF/selective-transfer。完整活动Cartesian空交点及关闭spare轴保留位置与计时。

项目实验时间：LOAD/STORE15μs、CZ0.36μs、1Q1μs、MOVE/CONFIGURE `200*sqrt(max_full_RF_axis_displacement/110)` μs、M500μs、RESET100μs。row_column所有轴/载体共同进度`3u²−2u³`；explicit rigid线性保留。当前pose、纯evaluate、恢复、独立轨迹审核和viewer一致。finiteCZ6/nonpartner10/Raman5/运输1μm保持。MZ y130…180，最近合法site与2.5μm偏移运输/服务显式计时。

QMAP公开接口不接live初始mapping，段间真实buffer permutation计时，不按门启动进程；原生输出不分配多AOD或一般并发时间线。报告源canonical-scheduling-zero/v1，fidelity=null，无量子质量资格。

## 复现、回放与阶段边界

编译需QMAP3.5.0、mqt.core3.3.3、Qiskit2.2.3；新compiler不依赖Bench/author evaluator/legacy adapter。写新目录复现，保留attempt5：

```powershell
python examples/run_native_kernel_memory.py --output artifacts/native-kernel-2026-10-04/d3-global-ez-reproduce --rounds 2 --wall-budget 120
python tools/audit_native_kernel_memory.py artifacts/native-kernel-2026-10-04/d3-global-ez-reproduce --output artifacts/native-kernel-2026-10-04/d3-global-ez-reproduce-independent-review.json
```

输出原源/初态、native请求/NAViz、relative blocks/absolute operations、journal、inflight/final checkpoint、独立audit、共用replay/recording与SHA manifest。review写run同级保持manifest封闭。当前8780绑定attempt5，真实default视窗及请求390×844窄屏全EZ/caption可见，console0；两Node按replay.html通过报告/倒放/六pairs/XZ/zoom/immutable和320/390/desktop fit。旧attempt2的1280检查不计本轮。

attempt3实际失败；attempt4 memory/独审真实PASS，保留最终batch-report identity修复前范围，不能代替attempt5。source-freeze-v4取代v3并已交协作工厂。完整143工厂、库存/同token injection/processor、native双AOD、含噪FT和完整physicalShor均未由本例资格化；下一步按共享S1–S3原完整依赖接薄controller，先有界warm-native、持续holder/fullRF/MZ与报告续接证明。

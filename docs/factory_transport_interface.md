# 工厂与双 AOD 运输的最小对接合同

2026-10-05。状态：**DESIGN_ONLY；接口建议，未实现 factory transport adapter，未新增物理运行资格。** 本页补充 `processor-physical-fragment-contract/1`，不替换工厂共享协议。现有资格仍为 [34原子独立双AOD纯运输](modular_aod_transport.md)；143原子冻结工厂、221原子兼容前缀、34原子运输例是三个不同profile。

审阅输入是工厂工作区保存的 `artifacts/factory-kernel-port/rag-collective-interface-readonly-attempt0/design.md`，SHA256 `341f1dd94c2e0a674cf073ad8a162f68b9a7dc733facc8820a98ca4a04c9c36f`。小型[静态审阅回执](../references/qec_pbc_validation/factory_transport_interface_review_2026_10_05.json)记录所读源码指纹。未运行新native、Factory、Executor或大产物重放，未写原工厂工作区。

## 已有能力与必须保留的边界

`AODTransportModule` 是绑定具体完整起态的不可变运输实例；`coordinate_aod_modules` 在一次schedule中编排各设备END链和真实资源冲突。两个已知模块可以共用一个scheduled Block并分别完成，resource无需等待data归还。`device_completion_us` 是计划相对完成时间，实际完成必须另用END及postcondition确认。

**resource完成并不开放一个新的Block提交入口。** 当前模块在idle边界绑定，在途绑定先以 `MODULE_ORIGIN` 拒绝；直接提交仍有效绑定的新Block时，KernelExecutor对active Block拒绝 `BLOCK_BUSY`，过期绑定则先拒绝 `STALE_BLOCK`。因此现API能在同一预声明时间窗里重叠两条运输链，不能在data仍MOVE时根据新的工厂报告动态追加生产/服务Block。不要创建第二个Executor、修改队列或伪造WAIT绕过这个限制。对应实现：[模块绑定](../src/neutral_atom_strategies/scheduling/aod_modules.py)、[Kernel提交](../src/neutral_atom_kernel/runtime.py)。

工厂侧公共 `FactoryProcessorContext.execute_processor` 当前也要求实际kernel drain，并检查预声明fragment、外部原gate完成及raw报告。`committed_kernel_inputs` 绑定当前FactoryKernelRuntime，并核对全局完成IDs、原始报告、时间/version/state hash及报告完成时刻/cursor。现新运输模块没有接入这个公共port，也不能在context之外直接写它持有的kernel。

模块默认终态检查要求本device已无承载原子；STORE须落在声明SLM，**不自动证明回到原home或初始RF位置**。工厂返回目标、holder、全RF与slot lease应在调用方exit合同中明确声明；实际34原子例有额外home/SLM断言，不能推广为所有模块的自动保证。

## 三个最小版本化对象

以下schema名是提案，没有对应的新Python类或公开adapter实现。

| 对象 | 最小字段 | 职责 |
| --- | --- | --- |
| `aod-transport-template/1` | template/strategy/compiler版本与SHA、profile完整SHA及RF mask语义、role集合、不可变primitive/本地依赖、entry/exit约束 | 可缓存结构；不存live state、报告值/cursor、RNG、token或epoch。 |
| `aod-transport-request/1` | request/instance namespace、run/owner/authority、template/profile SHA、全局ready门禁、token绑定、唯一carrier map、完整entry snapshot、目标/exit合同 | controller在唯一writer边界创建请求；实例化时从实际状态重新生成或验证物理坐标、完整轴与时长。 |
| `aod-transport-completion/1` | request/block/device/operation IDs、actual全局START/END、journal version/state hash、input review SHA、实际positions/holders/RF及exit检查、token/epoch原值 | 只描述物理运输完成；不产生测量位、原gate完成或新的可用magic库存。 |

entry snapshot至少含当前global `time_us/version/state_hash`，全世界存活原子 `positions/holders`，所有devices完整有序row/column坐标及active masks、声明SLM与slot reservations。不能只传移动资源的九个载体而遗漏工厂/data旁观者。当前mask合同为 `occupied-row-column-union/full-cartesian/v1`：空Cartesian交点也审核；不能由模板声明额外空活动轴。实例的额外参数不能覆盖profile硬阈值或容量。

token绑定单列 `token_id/carrier_ids/carrier_epoch/type/phase/code/distance/owner/run`。运输保存同一载体/epoch；STORE不代表factory重新接受了资源。已消费token的载体归还后进入cleanup/reprepare生命周期，不重新入可用库存；新的epoch与再接受由唯一inventory/controller在实际协议完成后提交。普通syndrome RESET与新资源epoch不可混淆。

## 时钟、源依赖和报告门禁

模块 `release_us`、Operation `start_us/end_us` 和device completion全部是**Block相对时间**，Kernel在提交时加实际当前global时刻。合同应显式保存 `time_origin_us`：

```text
relative_release = max(0, known_global_ready_us - time_origin_us)
actual_END = time_origin_us + relative_END
```

`global_ready_us=null` 表示未知/pending，不转为0。若controller在实例化与提交之间推进kernel，更新 `time_origin_us`、重新计算相对release/start/end，再检查起态/version并绑定Block；仅重新绑定不会调整旧schedule的相对时间。不能分别推进data/resource私有时钟再相加。

模块 `depends_on` 当前只能引用同次schedule的operation IDs；它没有消费外部gate/report/token门禁的接口。controller必须先验证实际原gate完成、全部必需raw/alias报告、资源接受与slot lease，再准入纯运输请求。报告位只从所属实际MEASURE完成导入；alias等待自己的完整raw集合。预计时间、计划END、预设轨迹中的未来位都不能开放请求。

若必要依赖在同个未来时间窗内尚未完成，不能把外部ID硬塞进transport-only `depends_on`，也不能用shared WAIT声称已实现M/RESET/CZ。需要之后的service-aware composer，保留原gate occurrence IDs、raw reports、测量轴/符号和原M→R/cohort屏障；完整审核后由同一个kernel执行。运输完成ID单独进入typed transport receipts，不伪装成原source gate或raw report。

## immutable模板与实例绑定

缓存key至少绑定canonical source/protocol、code/distance/orientation、编译器版本、profile完整几何/RF mask语义、primitive variant及结构依赖。current `AODTransportModule` 已是物理起态绑定实例，不能把它直接当通用role template跨恢复/跨profile套用。

角色重命名须唯一映射到实际carrier，重新绑定所有原operation/gate/report IDs并检查碰撞。实际全轴有差异时重新计算整台轴移动与时间，显式生成alignment或使用不同variant；不能只替换token或把坐标平移后覆盖live state。缓存只命中作者/native不可变模板不等于已命中合法物理计划。gate-less transport实例没有report IDs，但未来service实例必须各自分配原始报告身份和RNG/source cursor。

运行前 `geometry_guard` 的PASS须绑定精确 `input_sha256`；随后Block绑定kernel实际version/state hash。上述证据不能代替controller的logical/token资格。冷恢复保存kernel真实在途状态、module/request的原/相对时刻与完成事件游标、profile/模板SHA、slot leases和token/controller/public状态；验证全部层与唯一writer retirement后才继续。不能从模板恢复库存或复制旧报告。

## MZ和全x CZ之前仍缺什么

| 边界 | 对接时需要的实现/资格 |
| --- | --- |
| 全空间运输 | 新profile真实初态的全部载体、full RF/spares/Cartesian空交点、跨设备连续间距及捕获闭包；当前v1相交device envelopes直接拒绝，不会自动重排交叉路线。 |
| MZ readout/RESET | 声明允许holder/稳定支撑、MZ支持和服务容量、共享光资源、完整source cohort及报告END门禁；与正在MOVE的其它设备是否兼容，服从该profile真实物理合同。当前纯运输PASS没有放行这一并发。 |
| 全x EZ/CZ | 对整个pulse区间检查全world所有SLM/AOD原子及实际有限作用对，包括右侧resource和移动旁观者；x方向分离不等于退出全x照明。只有target AOD/laser锁不证明旁观安全。 |
| 可开始后继 | physical exit/END、原源gate完成、全部required raws、库存与lease分别验证；只等待本请求的必要条件，不额外等待无关device归还。 |
| 一般持续运行 | service-aware跨模块操作图和global leases、逐request完成门禁、恢复与去重，另有动态midflight admission资格；当前Factory公共API和transport v1都未提供这一能力。 |

保守的新适配可以先在真实无光脉冲的时间窗协调纯运输。在未审核光服务并发前，保留既有profile的静止/共享资源要求，不从“resource可以独立回家”推导出“可以同时任意CZ或MZ读出”。用户对RESET原位区域的后续选择不在此次审阅中替其决定。

## 最小接入与验收顺序

1. 增加controller拥有的transport request/receipt接口，保持现公共context单writer；先在idle稳定边界用同profile真实accepted载体映射执行完整返回，核验entry/exit、原token/epoch、无新报告/库存及原初态重放。新34原子未编码模板不能替代实际W4资源。
2. 在新profile同一预声明Block中合并ready的resource和data**运输**链，验证resource END/exit先完成、data仍在途；只开放该运输receipt，新的生产Block仍pending到合法提交边界。
3. 对service-aware composer单独验收全x CZ、MZ完整依赖/原报告、共享光资源与移动旁观者。分别证明safe overlap与必须等待的反例，保留完整15工厂成本及原协议。
4. 若需要按新测量结果在data在途时触发下一生产，新增versioned动态admission/branch与恢复能力。先小例跨device添加/拒绝/原子资源冲突/冷恢复/去重，再进入accepted→同token injection→多需求processor资格。

这是最小接口路线，不是已经实现的工厂/processor动态并行。当前已交付运输组件继续使用原资格；新方案逐项验收，不能热换143冻结工厂或用221兼容前缀的服务回执覆盖新profile。

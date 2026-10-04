# 2026-10-04 恢复并行码块自动 MZ 测量选点

用户指出测量位置选点消失，明确要求编译器自动选择 MZ 内最近合法测量位置。已有有序 `ReadoutPlacementPolicy` 未删除，但 `parallel_patch.compile_readout_group` 绕过选点，直接使用固定 translation；恢复策略调用属于工程接入修复，不改物理模型。

## 实现与默认

- 新设备感知 `scheduling/rigid_readout_placement.py`：从实际载体和 registry 轴偏移求 MZ 原点可行域，并扣除 world/envelope 的全轴跨度；关闭备用轴、外国设备及全 world 旁观者保留。
- nearest clamp 加 ±2.5/±5 μm 候选，预算16、至多3个合法完整服务按实际μs和AOD路程选择。端点不等于路线合法，LOAD→标准routing→真实M/RESET→重新寻路→OFFLOAD逐候选完整验证；失败不提交live state。
- `parallel_patch` 单服务/两设备共享RESET/run入口接回策略；_bindings只要求选中的设备空，外国设备载体照常参与物理检查。日志保留原门ID、设备、候选拒绝、完整成本和最终位置。
- CLI标准routing默认nearest_mz，显式fixed_translation恢复旧测量端点；legacy默认fixed。新summary明确历史-400是comparison值；旧单块实际生产源码仍保留修改前的显示字段与原hash，不能重写旧文件。
- 共用报告默认折叠选择/候选/载体坐标详情，按实际提交脉冲定位。原子同比缩放、X/Z角色、主要统计默认展开保持；旧无选点metadata的报告保持旧功能入口数。

范围与命令见[选点合同](../../docs/qec_rigid_readout_placement.md)。routing阶段已独立发布011d361/回执9a111846，其30.055938ms保持固定MZ端点，不倒填新选点身份。

## 分层验证进度

正式policy14＋integration9新测试覆盖最近位置、所有载体MZ、全轴/spares、外国已载设备、真实障碍换点、源对齐容差、预算/失败日志，以及实际Executor与原初态replay。包括旧routing/码块/设备/有序readout回归的159项不同pytest通过，267模块架构零违规；新report11项另外已通过，最后合并计数在完成后记录。

单块新attempt1已完整267native/50projection/34atoms/2AOD/161plans，模型终态22195.93818301007μs（旧标准routing固定MZ为30055.93818301007），完整原初态replay及source/Stim/几何、patch协议和新增选点独立审计均通过。7次设备选点覆盖50投影，每次尝试3个合法服务；算法首源原点(0,0)几何nearest(0,-80)、实际(-2.5,-80)，magic为(170,-70)。微小x通道偏移让完整服务更短，不称严格连续空间最近/最优。实际去回MOVE314，旧338。

12块独立新attempt1已启动，尚待完整执行、原初态replay、三层独立审计、UI验收后追加结果；不能由单块PASS推断多块已完成。所有运行保留在ignored artifacts/auto-mz-2026-10-04，正式源仅managed checkout，未写原目录并行factory工作。

## 审计修复与限制

新只读 `tools/audit_rigid_readout_placement.py` 不导入选点/router，按原初态轴、区域和实际源位置独立重算可行域/clamp，核对选择成本及实际脉冲位置。初审发现录制pulse可为空的vacuity，在正式验收前补齐全部原投影恰一次和row实际pulse覆盖；实际lane duration加共享效果与MOVE轴距离独立核对。源偏移按硬件alignment tolerance映射到实际捕获轴，避免把允许的SLM对齐误差当成MZ越界。对应portable tamper测试继续验收后追加。

一次只读小探针未指定UTF-8而遇Windows GBK decode错误；补显式encoding后重读成功，未改物理文件。全局最优、任意holder驻留、完整factory/injection、noise/FT和完整physical Shor不由本次Clifford前缀证明。后续共享S1–S3按工厂协议v2复用选点与标准router。

新增portable audit夹具初次误用不存在的 `Executor.run(on_event=...)`，改用真实逐 `step()` 返回事件交给VisualRecorder；并行pytest共享临时目录曾造成夹具目录被清除，随后各自采用独立 `--basetemp`。这些是测试夹具/运行隔离错误，没有改ENV或放宽断言。只读audit补单设备snapshot的`aod`/多设备`aods`兼容后，最终15项audit与整组185检查通过。子agent最早口述canonical字节长度实际是Unicode字符数，已更正为UTF8 bytes14672/17487/18572/24369，旧新SHA与字节相等判断保持，ignored可复现proof使用真实bytes。

## 最终完成验收

185不同pytest全部通过（0skip，36.23s），267modules/0违规。两组完整执行/replay及三层独立审计均PASS；单块22195.938183010μs，12块27955.938183010μs；相同固定端点baseline的减少分别26.1512%/6.9870%。原门/effect批次顺序与六份输入byte相同，每组7次设备选点覆盖全部投影。模型μs与run wall seconds分列，小型receipt保留源码、录制、trace、审计与原生产hash。

实际8777的7个选点表定位按钮/候选表及12功能书签、390/320px、主统计与缩放/XZ/console0errors通过。初次对临时single tab做viewport检查返回1016px，明确未当作窄屏PASS；切到capability所绑定主tab后真实375/305px内容宽与scrollwidth一致，恢复正常视口；最终full12另外重新验收。旧无metadata的12/11书签报告保持，原历史recording/decisions不被覆盖。

自动MZ绕过问题由rigid_readout_placement/parallel_patch/CLI修复并由完整multi-run、portable反例及实际浏览器证明，状态FIXED。未放宽物理阈值；S1–S3、noise/FT及完整physical Shor不由本轮新增完成声明。GitHub精确发布及独立fetch核对后追加回执。

RAG最终69chunks/58sources/178本地paths，schema/source指纹检查、73/73检索及11/11换行与路径可移植检查全部通过；新K69/L46保留旧routing固定端点历史与实际生产hash。最终full12截图保存于ignored `artifacts/auto-mz-2026-10-04/full12-auto-mz.png`，浏览器receipt绑定该run的实际recording SHA。最终receipt保存时第一次DOM探针误在外层读取shadow中的主统计，改用已验证shadow节点后成功；仅影响只读证据保存，不修改页面或物理运行。

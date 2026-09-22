# 2026-09-21 随机20原子四层与统一编译入口

用户先要求至少20原子/约4层随机复杂线路，随后要求纠正“普通编译再优化”重复流程。本轮同时完成实验与入口调整，无物理模型/RL改动、未提交推送。

生成器examples/random20_depth4_studio.py，seed20260921；两层随机完美匹配、不重复且整体连通，中间随机1Q，总60门/20CZ。生成时逐层检查20条线路不重叠且全部占用，递推每qubit深度严格4。configs/workbench/random20_depth4.json和artifacts/random20-depth4/circuit-audit.json固化。

原63410服务提交任务638cdce7248a4773befa6c68310731f9，输出仍在artifacts/studio-placement-delivery/runs/workbench/placement。使用grid20/8×8AOD、guard=true、256池/16评估/4进程/180s/stable。355.8777s完成，2/16有效；基线11255.340057μs，trial12=11366.456956μs，选中0，无提升。8次ORDERED_STAGING_EXHAUSTED、6次PATCH_EZ_CAPACITY保留。基线门60完成、CZ15批、装卸各16、路程2426μm。不得把搜索完成说成所有候选通过。

界面：去掉placement-compile和placement-cancel独立操作，线路区compile-mode选择fixed/optimize后共用唯一compile/cancel。预算details移入原编译配置卡；统一状态显示基线/候选/录制；结果区域不再带独立启动按钮。placement_search.enabled保存选择；旧普通输入缺对象默认固定，旧优化报告缺enabled仍视为优化。动画由已有计划重放；未重新规划。完整同输入/配置在同一服务器生命周期复用已完成任务，失败/取消不缓存；变更输入使key变化。

测试：test_studio_placement.py 11通过/13.25s（包括cache同合同复用、门修改失效）；ordered_workbench_controls.cjs新版固定模式显式选择后通过实际贪心/SMT HTTP编译，证明普通流程不被强制优化替代。free_placement_viewer.cjs扩展兼容Studio结果：20原子60门、两完整录制共30CZ脉冲2μm校验、两模式32×终点及不可变通过；185模块架构零违规；134文件Demo导出哈希/链接通过。

真实GUI：新版任务页载入20原子，32×自动播放至60/60；另开临时4H工作区，在平台与算法设3次评估，从唯一编译按钮运行2.3s完成，再点同按钮明确显示复用、无新搜索。新Demo服务PID26424，工作台64435/首页64438/SMT64436/QEC64437。旧服务仍保留；新版本应使用新入口。产物不重新编译，直接读取既有20原子结果。

工程记录：一次HTML改写锚点缺少id属性，断言失败且未写入，核对源后修正。Win32_Process查询权限不足，未尝试绕过或终止未知进程；启动新的已知本任务服务并保留原服务。两项均不改变实验结果。

边界：当前4层是依赖深度，物理上单比特门种类/运输/装卸产生更多阶段。候选仍分别编译；同会话结果缓存不是跨版本缓存或增量编译。有效候选率低须后续改进候选与EZ入区可实现性，不在本轮放宽约束。

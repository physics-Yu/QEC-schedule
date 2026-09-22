# 2026-09-21 并行初态搜索与不归还优化

用户明确要求扩大候选池、并行搜索编译、暂时不考虑放回原layout。实现方式与范围在[合同](../../docs/parallel_initial_placement.md)。没有改变物理模型、碰撞/支撑/光门/序关系规则。每批CZ后归还未改；末尾原layout归还实际省去，不能把其时间只从统计中扣掉。

## 文件与配置

- 策略：`placement/verified.py`新增batch_size与有序批量evaluator，保留去重/失败/基线和实际时间反馈；`free.py`传递批量接口。
- 控制：`ordered_controller.run_ordered(restore_layout=False)`仅以稳定结束为终态，不额外安排恢复操作。默认True兼容。
- app：`placement_worker.py`为独立spawn进程入口；`placement_execution.py`分配独立初态、编号/目录，完整编译/校验/重放，协议回调在父进程运行。
- 工作台增加pool/workers/terminal_mode配置，旧JSON按64/1/fixed解释；新默认256/4/stable。记录两版终态是否相同，但stable不要求相同；浏览器标签随合同更新。CLI入口main保护防止spawn递归启动。
- `examples/compare_parallel_placement.py`读取此前同一完整电路，评估16次；`configs/placement/*-parallel.json`固化实际参数。

## 实际验收

命令 `python examples/compare_parallel_placement.py --evaluations 16 --workers 4 --pool 256`。12原子16/16通过，10437.797→8540.674 μs（18.1755%），装载17→17、原子路程1702→1284 μm；墙钟514.8167s。16原子16/16通过，4868.123→3949.628 μs（18.8675%），装载9→9、路程3056→1648 μm；墙钟613.3535s。无物理失败，全部候选与反例保留，未重复挑选随机种子。

`tools/audit_parallel_placement.py`独立恢复32份终态，检查dag完成、无pending、稳定、效果恰好一次、重放标志与真实时长，决策中无 `Return to initial SLM`/`terminal`。两组终态位置确实不同，全部末尾归还批次为0。每组4个不同PID，时间区间峰值均4；见 `artifacts/free-placement/parallel-summary.json`。这证明并行执行，不证明4倍速度提升。

- 18项编译/free兼容测试先通过；54项初态/边界/编译/free回归通过（`parallel-regression.xml`）。
- 3项新增测试通过（`parallel-tests.xml`）：相同波次串行/并行映射及时间一致、实际多PID、最后CZ回程计时、无末尾归还、父进程lambda协议拒绝、旧输入合同。另补固定终态跨spawn精确恢复测试1项通过（`parallel-fixed-test.xml`）。最终不同测试58项。
- 184模块架构通过，JS语法及diff whitespace检查通过。
- 两个新版目录的viewer检查通过：四份完整电路、48次CZ实际2μm距离、两模式32×结束、录制不可变；小GUI任务录制也通过。
- GUI真实手动编辑2原子H/CZ/T，256池、2进程、stable，3次候选成功；job `b9afffeaee4b40ebb97ce6183439a552`，13.9s。验证结束说明不再称共同位置。
- 12原子新优化版32×到8540.674μs、84/84；切换新顺序基线32×到10437.797μs、84/84。16原子新优化版32×自动播放至3949.628μs、96/96；聚焦原子后确认结束位置保留在EZ的稳定SLM上、AOD静止且无载原子，未追加原layout归还。已将新版16原子页面标记为交付页。

## 工程记录与限制

一次apply_patch同时删除/添加同一路径被工具拒绝，未写入；改为整文件更新后通过测试。旧浏览器tab已失效、库存读取失败，重新打开当前URL后连接恢复，不将之前连接失败当作GUI阻塞。只重启本任务已知Python服务，当前PID10072，端口60054。

整批屏障等待最慢候选；扩大实际评估预算不等于墙钟更短。未来可用安全成本下界剪枝/异步任务队列改善吞吐，但本轮未实现这些新算法。任意后端/连续几何/全局最优/大型surface量子正确性均未额外宣称。未改环境硬规则或新RL，未提交推送。

# 有序行列贪心扩展交接

用户要求核对移动是否写死，并在 AOD 序关系下扩大贪心动作维度。已确认环境已有独立行列能力，限制在固定形状 patch/SMT 实验的策略层；本轮没有改动物理事实、硬约束或环境接口。

新增策略 `scheduling/ordered_greedy.py`、实验 `ordered_axis_comparison.py`、CLI `examples/run_ordered_axis_experiment.py`，现有 SMT 应用支持服务端选择实验模块并复用可编辑前端。提供双方移动角色/四方向、共轴约束、序关系、捕获闭包、非均匀轴目标、正交通道、真实批量 CZ 及归还。默认64 beam/24物理候选/128路线，有序搜索保留同位移可行 incumbent。

入口 http://127.0.0.1:8794/，服务 PID20892；输出 artifacts/ordered-axis/attempt3。完整报告 [ordered_axis_greedy](../../docs/ordered_axis_greedy.md)。attempt1 首个三列实例保留；attempt2 无 incumbent 出现闭包性能退化，attempt3 修正后五例十次执行全部通过。三列/二维分别减少59.0%/70.5%物理时间，闭包恢复5+1，交叉依赖减少18.4%。同后端同初态同终态的策略消融，不能与旧 rigid 恒速数值直接混比。

测试：38项一次运行通过；incumbent新增专项首次夹具断言归属错误，修正后精确2项通过，共39不同测试；133模块边界检查通过。非全仓回归。真实内置浏览器成功编辑H并双策略编译（interactive/19928325e6ab438190204e74a86976d0），32×自然终点、6原子SLM、4门完成；rows=0错误弹窗；二维四CZ同脉冲画面核验。原8793服务当前连接拒绝，未改旧记录。

范围：2–16原子/1–16无条件HXYZTCZ/初始10μm网格/单台行列AOD；每批归还、有限beam与正交通道、没有跨批驻留/辅助腾挪/移动–移动CZ。候选穷尽不是物理无解；保留incumbent也不是整条电路不退化保证。

下一条可执行任务：缓存共用几何与闭包，让同位移incumbent和变距beam共用候选构造，测量相同物理成绩下的编译时间；再独立评估短窗口前瞻。未提交/推送Git。

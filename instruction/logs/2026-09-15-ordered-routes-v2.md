# 连续直行与2.5μm占据格路线交接

用户先指出直行不该停顿、拐弯应停，再澄清“关格点”指路径障碍标记而不是关闭SLM光阱。按此落实，没有改变原子支撑或光阱开关硬规则。

新增 `strategies/motion/ordered_routes.py`：同向轴运动合并、2.5+2.5k离散路线、post-load静态占据格与安全间距预筛选；全部活动交点含空trap均检查，后续仍完整连续校验。`ordered_greedy`复用只读准备、按合并后的真实路线时长排序。仍有限候选，不宣称完整高维A*。

直行新路线触发通用ProgramBuilder浮点时长ULP错误，实测614.448961784611与interval末614.4489617846111不同，导致PLAN_COMPLETED过早、pending timeline mismatch。将scheduled estimated_duration精确取interval末端，未加容差或放宽验证。

五例双策略真实执行全部成功，独立checkpoint重放一致。新版有序时间为1019.75/1263.59/649.70/1890.22/2250.64μs；旧attempt3保留。十份计划的所有MOVE正交且不存在多余同向直行停点，证据 `artifacts/ordered-axis/attempt4-discrete-grid/route_audit.json`。

测试主批次70PASS、1新fixture错误（从执行后状态恢复）；修复初态保存后4路线测试PASS，合计71不同测试通过。另先执行8有序策略全PASS。134模块架构检查PASS。非全仓回归。新UI手动加H后真实双编译，job eb046141b57c440c905215acfca58e2a；两个回放模式32×终点检查。

入口沿用 http://127.0.0.1:8794/，已重启至PID21508，新数据根attempt4-discrete-grid，页面ROUTES V2。先前内置tab3已失效，连接用户当前tab6并刷新；原始三CZ草稿与模板一致，没有丢弃用户自定义线路。

完整报告 [ROUTES V2](../../docs/ordered_routes_v2.md)。下一步：若仍遇到有限拐点族找不到的绕障，再以占据格作快速边检查扩展配置空间图搜索；增加复杂障碍矩阵，保留预算耗尽与物理无解的区别。未提交或推送Git。

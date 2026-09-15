# 测量支撑与落点策略

2026-09-15。对应用户清单第12–14项；新工作台 http://127.0.0.1:8798/ ，默认配置在 `configs/strategies/readout_placement.json`。

## 分层接口

`ReadoutPlacementPolicy` 位于 `neutral_atom_strategies/scheduling/readout_placement.py`，不依赖GHZ门ID、原子编号或协议阶段。

```text
READY测量组
  → ReadoutPlacementPolicy.candidates：支撑方式、目标位置、低成本评分
  → 有界候选列表
  → realize：请求movement到达已选目标，安排测量/复位/返回
  → OrderedTransfer.move_loaded / transfer_group：具体路线与完整物理验证
  → 少量合法计划的实际时长反馈
  → 选择一个完整计划交给Executor
```

上层先评分，下层再规划。没有对所有MZ落点全部完整编译，也没有让movement自行挑选测量落点。`readout_service(..., placement_policy=policy)` 支持注入替换策略；当前有序QEC工作台显式注入，旧调用未注入时保留历史SLM服务兼容路径。

## 替换的三项规则

1. **支撑方式**：`adaptive` 比较静止AOD与SLM卸载支撑，另有 `aod_only`、`slm_only`。AOD目标到位、停止后测量/复位，随后运回源SLM卸载；不在MZ强制卸载和重新装载。已在MZ稳定SLM上的组可直接原位测量。
2. **目标候选**：AOD使用区域内靠近来源的可容纳批次位置及附近离散偏移，包含原有间距和保持序关系的压缩间距；当前EZ→MZ通常把最靠EZ的一排放在y=-150附近。SLM保留原平移候选，增加不同有序行列坐标窗口的映射，要求使用真实存在的空闲交点。不是只复制整组形状。
3. **评分及反馈**：先估计空AOD定位、正交移动时间、读出/复位、装卸次数和简单射线障碍引起的脱离代价；运动估计使用当前速度/加速度/jerk参数。movement负责真实通道、停点、捕获与连续扫掠验证。默认最多尝试16个目标，收集至多3个合法服务，按实际完整时长、AOD路程比较；首个合法者不再自动结束。

自适应模式在预算允许时为另一种支撑方式保留一个后备位置。候选失败不会提交实时状态；失败原因记录后继续尝试。无合法目标时报`READOUT_TARGETS_EXHAUSTED`，超时明确报告，若已有完整合法方案则可保留该方案。现有上层仍可改试更小测量组。

`readout_log`记录生成数量、构造约束拒绝数、尝试的支撑/目标/评分分项、物理拒绝原因、实际时长及最终选择。评分是估计，不是可行性证明或最优下界。

## Q019原场景的独立对照

运行 `python examples/audit_readout_policy.py`，复用先前保存的Q019/5241μs服务前状态。三种方案分别经真实Executor执行和独立重放，量子态、测量结果、placement、AOD与SLM开关终态一致：

| 方案 | 完整服务 / μs | LOAD / OFFLOAD操作数 |
| --- | ---: | ---: |
| 旧SLM首个合法落点 | 2146.543079 | 2 / 2 |
| 新策略，仅SLM | 2119.838668 | 2 / 2 |
| 新策略，自动选择AOD | 1662.379001 | 1 / 1 |

自动方案：Q019先从(15,-45)到(12.5,-45)，再进入MZ的(12.5,-150)；同列Q020位于(12.5,-170)，另一列在x=52.5。四个目标均在MZ内，静止且支撑开启。该次选择保持原行列间距，尽管候选也包含变距方案；不是强制所有批次压缩。

产物：`artifacts/qec-readout-policy/q019/comparison.json`、各模式决策日志及完整局部动画。

## 整体交付与复现

完整相同34原子/483槽QEC双策略编译与独立核验产物：`artifacts/qec-readout-policy/attempt1/qec_ghz2/`。最终指标及核验状态由 `comparison.json`、`analysis.json` 记录，不能用局部对照替代完整验收。

| 完整运行 | 原8797方案 / μs | 新策略 / μs | LOAD / OFFLOAD操作数 |
| --- | ---: | ---: | ---: |
| 贪心 | 27990.466904 | 24337.380746 | 35/35 → 27/27 |
| SMT | 28628.305195 | 24975.219036 | 35/35 → 27/27 |

两者都在8次测量服务选择AOD，均减少3653.086159 μs。每原子累计路程之和分别为13252/13270 μm（各减少2000 μm），原子次装卸237→205。17批CZ、最大9对并行以及105CZ/32测量/32复位不变。66计划独立重放checkpoint逐字一致，483效果各一次、终态、XX/ZZ与16码稳定子、完整测量协议全通过。

编译墙钟贪心238.184 s、SMT179.990 s，独立重放108.228/113.484 s；开发机有其他校验任务，不作隔离性能结论。43项不同Python检查最终通过，另重验8项新策略测试；139模块架构0违规。两份导出动画的逐运动段三次插值、双模式32×完整终点及编辑控制器的测量配置隔离通过离线验证。

```powershell
python examples/run_qec_ordered_experiment.py --output artifacts/qec-readout-policy/attempt1
python examples/analyze_qec_ordered_experiment.py artifacts/qec-readout-policy/attempt1/qec_ghz2
python examples/run_qec_ordered_experiment.py --serve --port 8798 --output artifacts/qec-readout-policy/attempt1
```

界面配置与电路独立，切换策略不改门，编译仍由电路区域按钮手动触发。结果显示实际AOD/SLM服务数，详细候选在诊断中。HTTP验收另编了H、MEASURE、RESET、条件X的编辑电路，两个CZ选择器均通过完整执行与重放；见 `attempt1/api-acceptance.json`。

## 范围与未改变项

- 没有修改环境物理核、测量时间或支撑条件。使用的是现有理想、非破坏性测量/复位模型，不代表真实设备的光学串扰、加热或损失已验证。
- 当前服务从SLM源位和空AOD开始，测量后返回源位。未实现跨服务驻留、占用AOD时同时为别的组调度运输、任意混合holder起点。
- 目标生成、评分和路径搜索均有界；不枚举任意行列排列，也不保证全局最短路径或全电路最优。
- 第7/8/11/15等原有规则（整体进EZ、调度优先级、CZ往返、测量后返回）没有被这次12–14项替换隐式改掉。
- 本轮浏览器连接仍报 `nodeRepl.fetch request failed`。真实点击验收未完成；HTTP和离线DOM/Canvas验收不能称为真实GUI验收。

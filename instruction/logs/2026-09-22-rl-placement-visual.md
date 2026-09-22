# 2026-09-22 · RL初始placement交互式离散对照

- 状态：COMPLETED；实现、数据核验、Node回放检查及真实浏览器交互/窄屏/自动终点验收完成。
- 用户目标：查看当前RL初始placement框架的可视化展示。
- 范围：读取既有 `pilot-20260922-attempt2` 产物，展示完整CZ线路、初始映射、离散事件、训练和对手诊断；不重训，不变更生产UI、Env或物理约束。
- 相关instruction：visualization；研究范围继承 `docs/rl_initial_placement.md`。

## 完成内容

新增 `src/neutral_atom_app/visualization/placement_rl_inline.html` 和 `.js`，对话内展示可筛选的基线/RL同尺度回放。可选择adversarial/uniform、seed 11/29、六条6原子测试线路或四条8原子外推线路，以及五个固定评价场景；左右分别为交互启发式与验证选中actor的一次greedy推理，不把八布局候选搜索收益冒充单次推理。

保留每条完整CZ线路、Q编号和gate标识，点击门定位RL侧对应脉冲，基线显示同一模型时间的实际事件；支持模型时间定位、事件定位、初态和末态，显示操作及完成状态。训练区域展示两种训练方式的验证曲线、实际选模点与逐场景诊断，保留无稳定RL优势的结果。最终对手为第16轮，actor可能为第4轮，页面明确这不是同轮联合checkpoint。

新增 `tools/export_placement_rl_visualization.py`：逐份读取并独立审计见证，检查冻结源码/线路摘要、评价时间、mapping与终态，再无损共享事件payload与重复回放。最终内联fragment为836,444字节，无API/后端请求或训练依赖；D3使用固定CDN静态script加载。读取已有数据不需要torch。

## 核验证据

```powershell
python tools/export_placement_rl_visualization.py --run artifacts/placement-rl/pilot-20260922-attempt2 --output artifacts/placement-rl/visualization-20260922/rl-placement.html
node tests/placement_rl_viewer.cjs
python tools/check_architecture.py
```

- 数据导出审计PASS：400份源见证去重150份回放，29,530源事件和5,440次CZ完整保留；事件压缩/恢复精确相等，全部评价duration与见证精确一致，独立离散审计完整门、SLM/AOD承载与终态；六个冻结源码哈希已核对。报告 `artifacts/placement-rl/visualization-20260922/data-audit.json`。
- `tests/placement_rl_viewer.cjs`：178,780次状态检查通过，包括44,959次反向定位；直接从原始见证构造独立账本，对照浏览器使用的replayState，不使用编译器生成预期状态。
- `tools/check_architecture.py`：213模块通过，无生产环境反向依赖。
- 真实浏览器已核验：seed 29 / `size_holdout-000` / 场景4的第一CZ定位120.1626模型μs，RL处于第一层4对脉冲而基线仍在卸载；这保留双方在同一模型时间的实际事件状态。6/8比特线路完整显示12/16门。
- 真实浏览器训练与对手面板已截图核验；seed 29选中actor第4轮与最终对手第16轮清楚分开。
- 320/360px窄屏采用堆叠布局，无水平溢出；320px检查时内部clientWidth/scrollWidth均273。
- 默认seed 11 / `test-000` / nominal自动播放到414.46模型μs后停止并恢复播放按钮；两侧均完成12个CZ、AOD空载。浏览器控制台error为0。
- 真实浏览器核验记录保存于 `artifacts/placement-rl/visualization-20260922/browser-qa.json`。导出器显式使用LF换行，Windows落盘后字节/哈希与 `data-audit.json` 一致：836,444字节，SHA-256 `13ac0b126c58a1843706c0a2e5df4b14d21ef7c165e9782ca97a2aeba7d1a88b`。

## 模型与展示边界

源点—终点连接只表示一次MOVE运输意图，不代表已规划或验证的连续轨迹。显示的坐标在离散事件完成时提交；LOAD/UNLOAD结束才改变holder。播放速度只影响展示，不能改变模型时间或图中真实几何。

这是快速离散编译的只读见证检查器；未计入空AOD定位/trap switching，未执行连续扫掠、碰撞、量子态和QEC验证。既有生产UI、Env及共用物理viewer保持原状；后续真实物理实验仍须完整编译→Executor→VisualRecorder。

训练、选择checkpoint和评测数字沿用冻结实验，未因可视化重新训练、调参或挑选有利线路。当前结果没有证明可训练对手稳定胜过uniform或退火。

## 下一条可执行任务

据用户选择增加新训练实验，或进行固定几何/终态下的真实物理抽查；两者均不由本次展示成功自动推断。

未提交、推送或修改长期memory。

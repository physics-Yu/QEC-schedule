# 2026-09-21 · 作者 QMAP 原生内核接入

- 状态：普通电路原生接入及五例物理验收 PASS；端到端性能、原几何公平比较、原生 QEC 测量 OPEN
- 用户纠正：直接复用作者架构/实现，通过兼容层接入本地环境；要求与作者 benchmark 接近，不接受另写启发式后只使用相似命名。
- 本轮合同：先按作者 eval 锁定 `mqt.qmap==3.5.0`、`mqt.bench==2.1.0` 与作者参数/架构复现，再保留原生调度、复用、IDS 和路由决策进行本地兼容。作者计时、适配计时、本地执行/验证计时分别记录。
- 物理条件不静默放宽；实际不兼容必须报告。先前 `zoned_ids` 只是独立实验实现，不再作为作者移植的交付。
- 代码工作区有既有未提交改动；本轮不推送、不清理无关文件。

## 进度

从作者 pinned 源码 eval 确认实验依赖为 QMAP 3.5.0 / Bench 2.1.0；建立项目内隔离 Python 环境，避免改变现有 Qiskit 0.45.2 及本地服务依赖。

## 完成范围与证据

- `src/neutral_atom_strategies/qmap_native`：原生 subprocess 协议、NAViz 严格解析、有序轴绑定/容量拆批、本地物理 adapter。`neutral_atom_app/qmap_native.py` 接原 editable Studio，`neutral_atom_experiments/qmap_native.py` 实验组合。
- 固定作者 eval、architecture、MIT 及 SHA256，发布 wheel3.5.0 与源码 main commit 明确区分；隔离环境锁及安装命令位于 third_party/qmap 和 tools/setup_qmap_native.py。
- 作者原生 benchmark、逐阶段耗时及五组原有电路表见 [报告](../../docs/qmap_native.md)。五例保持门 ID/类型/依赖和原 AOD 容量；几何明确改变，不能给旧布局加速比。输入哈希、失败、原生 NAViz、计划、录制及独立重放结果在 artifacts/qmap-native。
- 原有 grid16 完整54.707192693ms、96/96门、CZ8层/最多8门；partners12 24.193726ms、84/84；random20-depth4 25.299383ms、60/60、最多10CZ；sparse20 8.338414ms、12/12；repeated16 8.007195ms、32/32。
- 实验表中的内核计时与本地物理编译/录制、独立重放分别记录。GUI重编grid16与pytest并发，原生21.904ms、本地68.21s，仅验证同序输入的物理结果相同，不作为独立性能重复样本。

## 失败与修复记录

- 首次依赖解析/下载慢、uv缓存目录权限问题：改用项目缓存和明确镜像完成安装，保留日志。安装环境独立；未替换主项目依赖。
- 原子声明顺序不等于逻辑编号：按 atomN 后缀映射，加入回归。
- 初版相邻驻留2μm后H失败 RAMAN_NEIGHBOR_TOO_CLOSE；增加实际分离→脉冲→恢复，保留 reuse-h 失败与 reuse-h-fixed 成功。
- random20 原生第580行连续扫掠失败：部分STORE后未关无载荷AOD轴，空交点在后续变距时扫过SLM原子。关掉仅无载荷轴后完整通过；random20-strict/strict-fixed/masks 三份证据保留。不是删碰撞检查。
- 有序 partial PARK 原本仅开放 rigid；本轮在已有 explicit selective_transfer_enabled 下开放 ordered partial，保持共享轴支撑与误捕获校验。默认能力未开放。
- 原 AOD 容量不足：按原抓取顺序投影拆组，保持每原子各端点与CZ边界，重新物理验证。原random20末尾一组、repeated16两组发生拆分；不是分组最优证明。
- 回归最初4失败（旧默认/未给native显式平台），更新目录断言和有效测试平台；随后1项新增routing默认缺失，补枚举选项校验后最终55/55。没有降低物理断言。
- HTTP验收输入最初使用了不合法 strategy/general、recommended+implementation、缺column、缺adaptive EZ，均在提交前拒绝。最终用标准 legacy+implementation 显式native选择和editor列格式。中间ASAP展示列改变了独立门的提交次序（同每比特DAG），得到另一合法63.440ms结果；最终按原始输入顺序保存展示列，精确复现54.707ms。该差异说明 native 搜索受独立门输入顺序影响，不能把两者当同一次编译。

## 验证与交付

- `pytest tests/test_qmap_native.py tests/test_studio_config.py tests/test_studio_config_files.py tests/test_ordered_workbench.py -q`：55 passed；覆盖原子身份、未知指令、轴交叉、容量投影逐原子轨迹、partial store、5μm隔离、普通编辑和旧QEC回归。
- `tools/check_architecture.py`：205模块、0违反；env不导入策略。
- `node tests/qmap_native_viewer.cjs`：五例每门一次、每CZ实际配对与2μm、两播放模式32×到终点全部通过。更新背景显示后复跑通过。
- `tools/build_demo_bundle.py`：134文件55.4MB；源模板导出，未手工覆盖生成源。
- 真实浏览器恢复后：原工作台载入16原子96门，32×播放到54707.19μs、已完成96、AOD静止且空载；1059.72μs显示8CZ/16原子打光。另开QA页从4个H手工加CZ，点击编译5/5成功、1561.305μs，无console error。不是仅DOM替身验收。
- GUI发现1μm内部候选网格过密；只给native显示10μm参考线并隐藏未配置候选点，真实SLM/坐标和物理数据不变。旧录制仅补显示提示再导出，未重写轨迹。
- 服务 `http://127.0.0.1:50860/`，PID11320，正式job `8ea7313ccedd45d3a9f24f542fbd30c8`；原60054旧实验保留。本轮未提交或推送GitHub。

## 明确未通过/未执行

原native层不支持QEC测量/复位/反馈；锁定协议留在原策略。未做同一旧几何和同一终态的性能对照，未做完整千比特Env物理执行，未达到论文墙钟速度。下一步主要是量化兼容层增加的装卸/1Q隔离/正交路径，以及减少等价重复物理验证；不能删硬约束或用原生毫秒数替代端到端秒数。

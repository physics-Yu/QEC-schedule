# 2026-09-14 · 环境、策略与控制应用分离

- 状态：COMPLETED
- 用户授权：大规模包边界重构；neutral_atom_env 保持纯物理模拟环境，算法移到 src 下独立策略包，控制程序通过环境接口操作实验平台。
- 起点：main 工作区包含前轮未提交的配置/UI分层与JSON外置；不覆盖、不回退这些修改。
- 保持：物理约束、唯一 Executor、checkpoint schema19、输入兼容和执行语义。
- 本轮目标：迁移算法与应用；建立环境操作接口和外部可替换策略入口；通过依赖约束、代表性执行与恢复测试验证。
- 本轮不引入：新RL、联合落点求解、动态变距搜索或物理模型变化。

## 完成内容

- 迁移67个模块，拆开3个同时承担物理验证与算法/应用职责的混合模块。当前四包：env（58个Python模块）、strategies（34）、experiments（28）、app（8）；迁移明细保存在证据目录的module-map.json。
- `NeutralAtomEnv`拥有唯一Executor，提供create/observe/validate/submit/step/run/fork/snapshot/restore；环境不自动选择门、落点或路线。
- `Strategy`、`FunctionStrategy`、`ControlProgram`统一外部控制接口。六种通用策略，以及row/patch/QEC控制循环都通过env提交和推进；特定时域QEC历史guard属于experiments.runners。自定义Python策略可直接注入，不需要修改环境。
- 工作台、studio配置、HTTP作业和算法派发移到app；电路生成、布局demo、fixtures和实验验收工具移到experiments。env仅保留无算法依赖的通用recording/viewer和逐原子统计。
- 更新仓库内Python/JS引用、前端资源位置、package data和现行文档导入路径。旧CLI、输入JSON和schema19保持；不在env留下反向导入算法的兼容壳。
- 新增[边界合同](../../docs/environment_strategy_boundary.md)、[src职责表](../../src/README.md)、`tools/check_architecture.py`和12项接口/隔离测试。

## 验证

证据根目录：`artifacts/environment-separation-2026-09-14/`（忽略的本地产物）。

| 检查 | 结果与范围 |
| --- | --- |
| `python tools/check_architecture.py` | PASS；128个Python模块，零逆向包依赖，策略无直接Executor构造/import |
| `pytest -q tests/test_environment_boundary.py` | 最终12 passed in 1.45s；屏蔽外部包后独立执行物理H、冻结观测、非法/过期计划拒绝、fork/中途恢复、自定义策略注入、六策略统一接口 |
| 配置/M3/M4/单trap等专项 | 85 passed in 161.73s；与其他测试有交集，不相加 |
| M0及两/四块时域恢复guard重验 | 56 passed in 6.17s；一条第三方dateutil弃用警告，与物理无关 |
| 六种策略迁移前后完整checkpoint | 六项逐字一致；同seed7、两原子H→CZ→T输入，比较包含事件/状态的完整SHA256；见baseline.json/equivalence.json |
| 真实HTTP编译与历史结果对照 | 四原子4门、84事件、38操作、954.3μs；job526d214eb69a4aff990e4a58621cab96与原job679c19d84cd444c680517fdd71dedec9 checkpoint逐字相同；所有前端资源和catalog接口可用 |
| 真实浏览器 | 32×播放到954.3μs终点，4原子均SLM；放H、撤销、线路按钮手动重编4/4、38操作、954.3μs；实际编译7.056s（并行回归负载下的单次观测），零console errors；见browser-acceptance.json |
| wheel | `python -m pip wheel . --no-deps --no-build-isolation --wheel-dir artifacts/environment-separation-2026-09-14/wheel`成功；四包与前端package data包含，工作台仍按既有仓库configs路径运行 |
| 全仓suite | 1585项全部执行：首次1572 passed / 13 failed / 1 warning，2694.71s（44m54s）；最终源码精确重跑13项，13 passed in 1.92s。不是一次全绿；原日志pytest-all.log、修正前补验pytest-failed-rerun-attempt1.log与最终regression-summary.json分别保留 |
| 最终受影响文件复核 | `pytest -q tests/test_workbench_large.py tests/test_environment_boundary.py`：27 passed in 4.06s；与上方重叠，不相加 |

## 失败与修正记录

1. 初次新增边界测试发现实验布局辅助函数反向引用工作台；将相对AOD几何读取抽到`experiments/input_geometry.py`，工作台复用。另修正测试中误写的recording字段名。最终12项通过。
2. 全仓首次执行发现旧M0集成fixture在EZ把原子按5μm排放，与后加的四邻停驻保护矛盾。使用before.zip的原始源码复现相同`EZ_NEIGHBOR_OCCUPIED`，证据baseline-m0-failure.json。仅将fixture改成EZ内10μm的2×2布局；不改硬约束、不改预期门执行。
3. 时域guard旧测试使用SimpleNamespace模拟预检查，首次迁移过早将其包装成env导致类型拒绝。修正实验适配器先执行原guard，再把真实执行交给策略；正式Strategy接口仍强制NeutralAtomEnv。两/四块guard重验已通过。全仓进程在修正前已加载这些模块，其首次失败应与最终独立重验区分。
4. 自动审批拒绝删除迁移后旧目录中的`.pyc`缓存。未绕过重试；env/motion、planning、experiments、testing只剩忽略的缓存，无Python源码。依赖审计与独立导入执行通过。
5. 全仓首次13项失败具体为M0旧fixture 1项、四块guard旧适配器11项、工作台深链接测试1项。最后一项是前轮配置分层后的测试替身未加载catalog/model脚本、缺少body/查询DOM接口，仍假定8门默认、3600秒预算、历史输入可编辑，并未等待编辑后的preview校验。将测试按真实页面脚本顺序启动、使用显式custom输入、比较配置中的预算/默认线路、等待真实preview后手动编译；保留2→3门实际API编译断言。生产UI与物理代码未因此改变。首次重验12过1败，修正后13项全部通过。
6. 最终整理现行instruction/architecture.md，替换过时的“当前目录/schema13”导航；model_audit登记ARCH-001和TEST-001为FIXED、完整PlanningView隔离ARCH-002为OPEN。文档链接和git diff --check通过。

## 边界与未实施项

- 保持项目声明的几何/时序/Clifford模型；本轮不修改物理条件，也不等于真实光场仿真。
- `env.state`仍是旧编译器使用的特权冻结视图，含量子态/RNG/trace；新的Observation排除这些字段，但本轮不是不可信策略沙箱或完整RL信息隔离。
- 策略可替换已经落地；各策略内部搜索循环仍独立。Frontier→Intent→Move/AOD batch→候选池→RL、通用二维动态变距、状态/历史存储优化仍待后续。
- 未重新完整编译/重放历史1868槽四逻辑GHZ。现有QEC回归与本轮完整小线路对照不冒充大型性能提升。
- Python旧算法导入路径发生有意变更；外部调用方应使用新包，已运行旧服务不会自动加载新Python模块。

## 交付与复现

- 新可编辑入口：http://127.0.0.1:8792/?job=526d214eb69a4aff990e4a58621cab96 ；服务PID14084，命令`python examples/circuit_workbench.py --port 8792 --output artifacts/environment-separation-2026-09-14/runs`。旧服务保留。
- 浏览器手动重编job为0c5b69767391484fad3e11d606224b65，独立保存input/result/checkpoint/recording。
- Python3.12，Windows，main工作区。本轮未提交/推送，保留前轮配置/UI改动。迁移前src/tests/examples/pyproject存档before.zip；migrate.py是一次性脚本，不可在已迁移树重跑。
- 后续先收紧PlanningView、定义统一决策点与候选合同，再将现有算法作为可比基线逐层接入新策略流水线；不能通过修改环境物理行为补偿策略失败。

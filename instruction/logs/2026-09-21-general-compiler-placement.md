# 2026-09-21 用户指定 layout 的通用初态优化

## 目标和范围纠正

用户明确要“任意选定一种 layout 后，针对不同电路优化初态分配是否降低时间”，不是 surface GHZ 整体平移专用实验。本轮维持已有包分离与硬件规则，只做算法/API及非可视化验收。未改UI、环境物理模块、RL，未提交或上传。

## 实现

- 新 `strategies/placement/verified.py`：固定允许站点的有界 compiler-in-the-loop 搜索；默认在用户占据站点间交换qubit，显式允许空位、锁定、种子/预算。小空间且预算足够才穷举，否则按交互距离排序+定期探索+全局重启。实际通过的时间更新搜索父映射；全映射去重，失败保留，原布局先评估并在持平时保留。
- 新 `app/placement_execution.py`：绑定完整电路、平台、种子、量子初态、固定编译选项和共同绝对终态；仅改变准备好的初始holder。每候选运行普通有序控制器，检查完整门效果、终态与可选协议判据，再独立snapshot重放。
- `run_ordered` 增加可选 `terminal_target`；原调用默认行为不变。`PlacementProblem` 去除代理特有的正交限制，限制移到实际使用该公式的成本模型。
- `examples/optimize_compiled_layout.py` 接收现有工作台JSON，保留所选ordered_greedy/smt_ordered及预算。不隐式用demo替换输入；固定平台Python接口可接任意合法 PhysicalCircuit。
- 新跨布局实验和审计工具，文档 `docs/compiler_initial_placement.md`。

## 验收与原始证据

```powershell
C:/python312/python.exe examples/check_compiler_placement.py
C:/python312/python.exe examples/check_compiler_placement.py --rounds 3 --output artifacts/initial-placement/general-three-round
C:/python312/python.exe examples/check_compiler_placement.py --rounds 3 --layouts irregular --output artifacts/initial-placement/general-irregular
C:/python312/python.exe tools/audit_compiler_placement.py
C:/python312/python.exe -m pytest -q tests/test_compiler_placement.py tests/test_initial_placement.py tests/test_surface_initial_placement.py tests/test_environment_boundary.py --junitxml=artifacts/initial-placement/general-unit.xml
C:/python312/python.exe -m pytest -q tests/test_compiler_placement.py --junitxml=artifacts/initial-placement/general-search-final.xml
C:/python312/python.exe tools/check_architecture.py --output artifacts/initial-placement/general-architecture.json
C:/python312/python.exe examples/optimize_compiled_layout.py --input artifacts/initial-placement/general/row-crossed/input.json --output artifacts/initial-placement/general-cli-smoke --evaluations 1
```

- 14例×8候选=112份完整物理执行和独立重放全部通过；全局审计PASS，电路/硬件/几何/初始AOD/SLM开关/随机种子/共同绝对终态一致，选中实际最小值。报告 `artifacts/initial-placement/general-acceptance.json`。
- 三轮4原子电路（6CZ、非对易H插层、T收尾）：行交叉3602.440→2611.197 μs（−27.52%）；二维交叉4123.286→2974.438（−27.86%）；打乱另一配对图4123.286→3050.545（−26.02%）；不规则交叉4300.759→3629.873（−15.60%）。另外10例保留基线。
- 短电路保留负例：CZ并行批数减少并不一定覆盖重新分配后共同终态恢复的成本。完整分段时间在审计文件，不用路程代理冒充加速。
- 54项初态/边界测试PASS；新增小空间预算不足转入反馈搜索断言后，相关搜索文件15项PASS。旧有序工作台14项PASS。新API含测量、条件X、RESET的双原子协议完成、两原子Z=+1且独立重放通过。180模块依赖审计PASS，CLI smoke PASS，git diff --check无空白错误。
- 8次真实评估含重放墙钟约23–30秒（短例）、56–87秒（三轮例）。同时运行回归会影响墙钟，不作为严格性能基准。

## 开发失败及处理

1. 一处测试错误地将“初态映射对列表的顺序”当作映射语义，算法按qubit顺序规范化是正确的。改为实际反转位置分配来验证保留用户基线；未改选择规则以迁就断言。
2. 小型读出测试首次走工作台旧输入校验，被其“非QEC profile禁MEASURE”限制拒绝。改成直接提供 PhysicalCircuit 给本次headless API，平台仍由既有工厂产生；随后真实测量/反馈/复位/量子判据通过。失败保留于 `general-ordered-regression.xml`，其中14项原工作台回归已通过。

## 边界和下一步

通用指搜索不依赖电路/布局特例，不保证任意硬件可编译、每个原布局都能加速或全局最优。当前真实adapter限普通有序贪心/SMT，结果是112份小电路证据；未重新执行34原子全surface GHZ的自由分配搜索，不把先前保形试验写成这次已加速。原始制备成本不计，不能当作免费运行时重排。

下一步可执行任务：在相同 API 上，用明确小预算对完整surface QEC电路做自由分配搜索并提供其量子协议验证器；如果单次完整编译过慢，先研究增量评估/可复用子程序缓存，不能用静态代理分数代替结果。每qubit不同区域domain约束、动态placement新算法、可视化接入仍未实现；用户要求先算法验收，UI保持不动。

# 2026-09-22 · 全量工作区整理与 GitHub 发布

- 状态：COMPLETED
- 用户目标：整理目前全部内容，更新 README、日志与交接，上传 `physics-Yu/QEC-schedule`。
- 起始版本：`main` / `0e8821c`；本轮 fetch 后与 `origin/main` 无分叉。
- 范围：本仓库累计的源码、配置、测试、说明和精选 Demo；实验 RL 一并收录并标明研究状态。忽略的运行产物、训练权重、安装环境不上传；独立 `QEC-scheduler-next` 不属于本仓库。
- 相关规范：[workflow](../workflow.md)、[architecture](../architecture.md)、[compiler_contract](../compiler_contract.md)。

## 整理内容

1. 根 README 统一当前入口、原生内核安装、四包职责、策略能力、验证边界与复现导航。
2. 当前版本说明覆盖 Parking、初态 placement、QMAP/ZAC、分层驻留、交互 IR、QEC 和研究实验；历史性能结果不冒充本轮测试。
3. 记录 constraint/placement 审计，区分现有调用链与尚未实施的重构方案。
4. 旧 handoff 原文归档；新 handoff 保留短的当前状态、未完成问题与证据索引。
5. 检查第三方许可、发布文件、打包资源、Demo 导出和适用回归，再提交并推送 main。
6. 补齐 `parking_template.js` 的 wheel package-data；默认 QMAP 的独立安装提示同步到根 README、Demo README、首页和离线工作台提示。同步初态搜索默认关闭及当前四算法目录，历史算法说明显式标注版本。

## 验证与发布

| 本轮检查 | 结果 / 范围 |
|---|---|
| `tools/check_architecture.py` | 216 模块、0 违规 |
| `tools/build_demo_bundle.py` + `check_demo_bundle.py` | 134 文件，哈希/大小/链接/GHZ 保存交付哈希通过 |
| `tools/check_demo_http.py` | 11 项通过，首页/编译服务/静态动画/非法输入响应；不是浏览器视觉验收 |
| 主要整理文档链接 | 10 文档、118 个本地链接目标存在 |
| `git diff --cached --check` | 暂存检查通过；无删除文件 |
| 第三方与文件检查 | QMAP 三份 vendored 来源哈希吻合、MIT 保留；原始新增约 1.72 MB，既有最大动画约 41.05 MB；常见凭据格式有限扫描 0 命中，不等于完整安全审计 |
| Wheel 构建与资源检查 | 无缓存构建通过，包含 Parking JS、IR、工作台 HTML；完整应用仍按源码 checkout 运行，不宣称 wheel 单独包含配置/演示 |
| `examples/interaction_ir_demo.py --output artifacts/release-2026-09-22/interaction-ir` | 6 原子/2CZ 同批、13 操作、效果各一次、2 旁观原子全程不动、完整独立重放相同；总物理时间 1016.452414676 μs |
| 全量 pytest 首次尝试 | 收集 1889 项；约18分钟后主动收束历史大规模压力运行，stdout记录717通过/1失败/0跳过，未完成整套且无完整JUnit，不宣称全量PASS；后续用有界发布分组验证修复 |
| IR / lowering / zoned / 环境边界修复后分组 | 58 passed / 16.02 s，新进程加载最终修复，含缩小前沿回退、真实执行/重放及环境隔离 |
| RL 摘要兼容与原失败复验 | 2 passed / 2.88 s；独立字节预期及完整小训练报告输出通过 |
| 工作台/QMAP/ZAC/placementRL/共享轴分组 | 171 passed / 94.93 s，0 fail/skip；包含上述RL两项。与58项合计229个不同专项用例，不与初次717项简单相加 |
| 无旧 artifacts 的源码归档检查 | 源树 `38861ce308cf65a4ded480621a85878e63f47bc8` 的 957 文件归档：独立导出134文件、bundle校验、11项HTTP检查、216模块架构均通过；复用现有解释器依赖，非全新venv安装验收 |

原有 GUI、大型 benchmark、训练与完整 QEC 成绩分别引用专题日志，不全量重新执行。证据目录 `artifacts/release-2026-09-22/` 被忽略，关键结果在此保留，命令可重建。

修复后最终架构审计仍为216模块0违规，bundle仍134文件通过；12份相关文档150个本地链接目标存在。完整测试状态 `full_suite_pass=false` 明确保留在 `verification-summary.json`；中止记录不被专项 PASS 覆盖。

专项复现（在已准备研究依赖的现有 Python3.12 环境执行；首次安装依赖按各专题说明）：

```sh
python -m pytest tests/test_interaction_ir.py tests/test_interaction_lowering.py tests/test_zoned_compiler.py tests/test_environment_boundary.py
python -m pytest tests/test_studio_config.py tests/test_studio_config_files.py tests/test_studio_placement.py tests/test_workbench_compilation_config.py tests/test_qmap_native.py tests/test_zac_reuse.py tests/test_zac_initial.py tests/test_zac_benchmark.py tests/test_placement_rl.py tests/test_row_column_aod.py tests/test_axis_hold_routes.py
python -m pip --disable-pip-version-check wheel --no-cache-dir --no-index --no-deps --no-build-isolation --wheel-dir artifacts/release-2026-09-22/wheel .
```

### 本轮工程失败与修复

- 首次 wheel 已生成但 pip 写本机缓存的 `origin.json` 被拒绝；改用 `--no-cache-dir --no-index --no-deps --no-build-isolation` 后成功。未修改系统缓存权限或依赖。
- 沙箱不允许写 `.git/index.lock`；按用户明确发布授权申请 Git 元数据写权限后暂存与远端 fetch 成功，未删除锁或覆盖 Git 历史。
- IR-001：两个 READY CZ 请求在有限 EZ 站点下，IDS 可能返回一个门的合法前缀；严格 IR 绑定拒绝该前缀后，控制器没有进入已有的缩小前沿回退。已修复内置 resolver 适配，只延后精确前缀并重新建立较小显式请求，保留 IR 完整合同与物理判据。直接调用新增回归已验证：首门实际执行、第二门仍 READY、独立重放一致；极小 EZ 并不承诺整条线路都能编译，测试显式在一次服务后停止。
- 全量发现的1个失败位于实验 RL 训练报告：`model_digest` 经 PyTorch→NumPy 桥取参数字节，本机 Torch 与 NumPy2.5.3 ABI 不兼容。已用 PyTorch 连续字节视图计算相同哈希，未修改全局依赖、训练模型或物理环境；增加非连续张量、标量负零和禁用 NumPy 桥的独立字节预期回归。原失败与长 traceback 保留，2项修复后复验通过。

### 保存和发布

- 发布前 handoff 原文为 `instruction/handoff-2026-09-22-archive.md`，SHA256 `0a63398557722ed0b1e6a94c511552b44a6e9695efbd48b76b4898dd8f8dcb00`；放在原目录层级以保持相对链接有效。
- 主变更提交 `8cb547b6b524413b5231117e5734da76e2edf130`：311个变更文件，已成功推送 `origin/main`。`git ls-remote origin refs/heads/main` 返回同一 SHA；推送后工作区干净。发布前 fetch 与 `0e8821c` 一致，无 force push、无分支删除。
- 本次完成状态指代码/文档整理及 GitHub 发布完成，不表示全量压力测试、constraint重构或所有研究目标完成。本段为发布后的确认补录。

## 物理与范围

本轮不更换物理判据，不把原生离散指令、Parking 浏览器模板或 RL 离散模型作为完整连续物理验收。约束重构仍是待实施项。

# 主要演示

这里收录线路工作台、Parking、SMT 对照、有序 AOD 的两逻辑 QEC 对照和历史四逻辑 GHZ 回放。2026-09-22 当前自定义默认为 QMAP 原生编译器；本地分层驻留、有序贪心与 SMT 保留为对照。开发过程和失败尝试留在 `artifacts/`；运行 demo 不需要旧机器的产物。完整能力见 [版本说明](../docs/current_version.md)。

## 直接分享 Parking Lab（无需安装）

打开 [Parking Lab](parking/index.html) 即可编辑 10×10 图案、生成逐行/逐列动作并播放。只把这个 HTML 文件发给别人也能用，不需要仓库、Python、编译服务或联网。页面的“下载可编辑分享版”包含当前配置、完整编辑器和动作，可以继续修改并再次分享。

这是隔离规则 patch 的构造式方法演示，不是完整环境物理审计；参数、边界和动作解释都在页面内。完整 Executor 工作台仍保留在 `python examples/parking_workbench.py --port 0`，详见 [范围与验证](../docs/parking_portable.md)。

## 启动其他可编辑版本

安装 Python 3.11+，在完整仓库根目录执行（建议先创建并激活虚拟环境）：

```sh
python -m pip install -e ".[smt]"
python tools/setup_qmap_native.py
python demo/launch.py
```

浏览器自动打开首页。保持终端运行，Ctrl+C 关闭四个本地服务（首页与三个编译服务）。默认首页端口 8800 被占用时用 `python demo/launch.py --port 0`。编译服务总是自动分配端口，无需修改 HTML。Parking Lab 使用静态页面，无单独服务。无桌面环境时加 `--no-browser`，读取终端地址。

原生安装器创建隔离运行时，当前默认编译器需要它。仅使用有序贪心/SMT 时可跳过 setup，并在自定义模式明确选择相应算法；不自动回退。初态优化目前可用于 ordered_greedy / smt_ordered / zoned_ids，默认关闭，不叠加到原生 QMAP 的作者映射。

除独立 Parking Lab 和保存回放外，完整仓库是运行单位：`demo/` 使用同仓库的 `src/`、`configs/`、`examples/`。只复制线路编辑器 HTML 不能运行 Python 编译。首次安装需要网络获取依赖，之后本地编译和回放不需要外部服务。

## 从哪里开始

| 入口 | 可以做什么 | 是否需要后端 |
| --- | --- | --- |
| [Demo 首页](index.html) | 选择主要演示 | 离线可看，启动器注入当前电脑的编译链接 |
| [线路工作台](workbench/index.html) | 平台与初态、编辑门、手动编译、回放、逐原子统计 | 是，从启动后的首页进入 |
| [Parking Lab](parking/index.html) | 编辑 SLM 占据与目标，逐行/列拾取与集体搬运，含方法讲解和可编辑分享导出 | 否，独立 HTML、浏览器本地构造标准动作 |
| [SMT 实验](smt/index.html) | 编辑小电路，对照贪心、单步 SMT、多阶段 SMT | 是，离线打开会转到保存结果 |
| [SMT 已编译结果](smt/replays.html) | 四组案例 × 三策略，动画与 CSV | 否，浏览器直接打开 |
| [有序 AOD / 两逻辑 QEC](qec/replays.html) | 最新两份完整动画、测量策略诊断及 CSV；从启动首页进入可编辑版本 | 保存结果无需后端，编辑编译需要 |
| [四逻辑 GHZ 完整动画](ghz4/animation.html) | 68 原子、1868 门/控制槽完整历史执行 | 否，单文件约 41 MB |

第一次建议选择工作台的“四原子 H 并行”，点击电路卡片中的编译按钮。切到“自定义”后编辑自己的电路；完整实验 demo 配套配置锁定，专用协议算法不作为通用策略。SMT 默认显示保存的矩形闭包结果；编辑不会自动编译。

GHZ 回放对应 [原始输入](ghz4/circuit.json)。当前工作台模板后来做过等价 HH 化简，旧回放槽数不能当作新模板重编译结果。大 QEC 电路可能耗时很长，先看保存回放即可了解完整过程。

新编译写入 `artifacts/demo-runs/`；`demo/smt/reference/` 中的对照不会被覆盖。失败会在界面显示；SMT 超时/UNKNOWN 不代表物理无解。重启会清空工作台内存任务列表，生成文件仍保留；重要回放可使用工作台导出按钮保存。

## 维护方式

维护源在 `src/neutral_atom_app/visualization/`，共用回放在 `src/neutral_atom_env/visualization/`。运行 `python tools/build_demo_bundle.py` 同步副本并生成 [manifest.json](manifest.json) 文件哈希；不要手改保存动画来改变实验结果。

新克隆已包含参考结果，可直接刷新 UI，无需旧 artifacts。维护者机器若存在正式 `artifacts/smt-batch/attempt2/` 或 GHZ 交付目录，导出器复制这些已编译记录，不重新物理编译。

## 当前 QEC 版本

有序 QEC 编辑器直接使用维护中的 `src/neutral_atom_app/visualization/qec_ordered_experiment.html`，无需另行复制 UI；新任务写入 `artifacts/demo-runs/qec/interactive/`。首次打开载入完整电路但不自动编译，保存结果在首页的独立回放入口；临时作业列表不跨服务重启恢复。

参考目录 `qec/reference/` 包含完整输入、两份动画、结果诊断、对比分析和逐原子 CSV（约 8 MB）。大型 trace/checkpoint/plans 仍由本地复现生成；不把它们的缺失隐藏为完整原始轨迹交付。导出器读取 `artifacts/qec-readout-policy/attempt1/qec_ghz2/`（若存在），否则保留仓库参考文件。更多分层、固定规则与可选配置见 [当前版本说明](../docs/current_version.md)。

## 历史接入记录：2026-09-16

“线路工作台”现在可直接选择有序轴贪心 / SMT 和行列后端，保留原子数量、布局、非均匀 AOD、随机线路与独立配置。新草稿默认新版；旧输入和旧算法不被自动改写。需要试验旧算法时同时显式选择兼容的 rigid 平台。顶部另有当前两逻辑 QEC 完整 demo。详情见 [通用接入说明](../docs/ordered_workbench.md)。启动器和已启动的服务是不同进程，更新后须重启 `demo/launch.py`。

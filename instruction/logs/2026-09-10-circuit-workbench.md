# 2026-09-10 · 可编辑线路与在线物理编译

- 状态：COMPLETED（本轮工作台与参数化串行 1Q；不是完整 M3）
- 用户目标：编辑 gate、原子数与初始 layout，重新编译驱动动画；用户明确选择同时实现 U3/单比特门真实物理执行。
- 基线：M3-A 已验收，M3-B–F 未完成；本轮推进参数化 1Q 的串行执行与交互工作台，不预先宣称完整 M3-B 或并行完成。
- 相关规范：visualization、milestones、compiler_contract、state_circuit、motion_execution。

## 完成内容

- `domain/models.py`：原参数及规范 U 效果、有限实数/角度数量；`hardware/raman.py`：稳定启用 SLM、地址区域、存活未测量资格。
- `motion/raman.py`、single_trap、program、validation：复用统一程序实现一次 Raman 效果、时长和 RAMAN_0/atom/site 资源，参数进入 fingerprint。纯 1Q 的空 capture 合法，旧 legacy cycle 仍要求 capture。
- `physical_executor.py`、runtime_validation、state/checkpoint：Raman start/end、一次门效果、独立 busy metric、全部边界恢复；schema 11 拒绝旧 1–10。
- recording、summary、viewer：原参数/规范参数、真实单比特阶段、SLM 原位红色弧线、Raman 独立类别；无虚构 partner 连线；旧 CZ 记录仍八类。
- workbench.py、server、HTML/JS：线路/layout 编辑、初态预览、确定性布局、可取消子进程、版本隔离、超时/失败/部分回放、导入导出。仅 loopback，限制 JSON/Host/Origin，无任意文件读写路由。
- 两个 example 入口、configs/workbench/mixed.json、测试、instruction/API/README 同步。GAP-004 FIXED（串行），其他里程碑缺口保留。

## 验证

| 命令/检查 | 本轮结果 | 证据 |
| --- | --- | --- |
| Raman/foundations/dynamic_traps 专项 | 当时 65 passed，1 warning，23.73 s | 参数/资格、holder、恢复和动态交接回归 |
| `python -m pytest tests/test_workbench.py -q --tb=short` | 18 passed，9.09 s | 布局/范围/冲突、实际 CZ、空线路、取消/替换/超时、HTTP |
| 首次全套 | 251 passed、1 failed | 旧 H 不支持负例与新增能力冲突，改为 MEASURE；CPHASE 旧测试另补有效角度后继续检验不支持 |
| 最终 `python -m pytest -q --tb=short` | **254 passed，1 warning，397.06 s** | 包含补充独立标准矩阵（至多整体相位）、参数指纹和损坏恢复测试 |
| `python examples/compile_workbench.py` | completed | artifacts/circuit-workbench-demo：4 gates、26 operations、60 commits |
| `node tests/raman_controls.cjs` | PASS | 当前源码和混合数据，SLM/参数/时长/类别/完成/数据不变 |
| 当前 bundle 的 single_trap、viewer_component、schedule_controls | 三组 PASS | artifacts/current-viewer-regression：旧 /2 recording 重新嵌入本轮 bundle，不冒称重跑十二 CZ 物理数据 |
| 真实浏览器 | 默认混合、U3 θ→0.75 后定位实际 5 μs SLM 脉冲、原子数 6、随机布局、H/CZ 放置、删除/撤销重做、取消与旧版本标记、自动编译通过 | 独立 QA 8767；H/CZ/U3/H 为 1175.290 μs；改成两个 CZ 后为 2514.348 μs、54 ops；应用控制台检查无报错 |
| 独立 HTML 下载/静态语法 | 下载成功，两个内嵌脚本解析通过，180698 bytes | Downloads/atom-replay-v10.html，v10 为草稿版本而非 checkpoint；file:// 浏览器打开被策略拒绝，不计离线浏览器 PASS |

warning 是 dateutil 使用 utcfromtimestamp 的既有弃用提示。六原子 mixed seed 7：wall/逻辑完成 **1175.2898987322333 μs**、Raman **15 μs**、CZ **0.3 μs**、AOD 路程 **279.99494936611666 μm**、原子路程 **181 μm**、3 LOAD/3 OFFLOAD，使用同一仿真时钟。

## 决策与物理假设

- 使用原有独立校验、Executor、VisualRecorder；编辑器不生成替代物理轨迹。
- 单比特门仅作用于已稳定、启用 SLM 承载的目标；Raman 时长使用明确标注的可配置项目参数。
- 在线编译有进度、输入版本与失败出口；有限布局与编译预算不代表任意布局完备可路由。
- 用户明确要求 U3/单比特真实执行。参数遵循已有整体相位约定，没有量子态或光场模拟。单比特固定时长含 I/RZ，不按角度改变路径/时间；默认 5 μs 为未标定项目成本。
- layout 是显式初态输入，站点距 10 μm、候选网格 5 μm；没有修改 clearance 或在失败后搬动伙伴。

## 未完成与下一步

M3-B 独立目标任务/操作 IR、无 gate 运输、prepare/pulse/cleanup 分离未完成；M3-C 通用持久续接/退出、M3-D 最小 1Q/运输重叠、M3-E 两种实质不同混合 compiler、M3-F 数百原子端到端仍待完成。界面不能作为这些能力的替代证据。

32 原子/64 门是输入上限，不保证 90 s 内任意电路完成。取消/超时未保证 checkpoint，正常完成/stalled 才落盘完整输入、记录、checkpoint/trace、诊断。草稿不自动保存，刷新需导出。未验收全尺寸、长期 FPS 或离线 file:// 浏览器。旧四原子 rigid-parking 对角 pair 共享轴限制保持。

下一项读 compiler_contract 和 M3-B，复用本轮 Raman/动态支撑与恢复语义，实现独立任务目标和操作 IR，不先做全局优化。

## 复现信息

Windows、Python 3.12，Node 用于离线控件。仓库整体仍未跟踪，无 commit/push；未修改历史已完成日志。

```powershell
python examples/circuit_workbench.py --port 8766
python examples/compile_workbench.py --input configs/workbench/mixed.json --output artifacts/circuit-workbench-demo
python -m pytest -q --tb=short
node tests/raman_controls.cjs artifacts/circuit-workbench-demo/index.html
node tests/single_trap_controls.cjs artifacts/current-viewer-regression/m3-single-trap.html
node tests/viewer_component.cjs artifacts/current-viewer-regression/m3-viewer-serial.html artifacts/current-viewer-regression/m3-viewer-row-column.html
node tests/schedule_controls.cjs artifacts/current-viewer-regression/m3-viewer-serial.html
```

current-viewer-regression 通过 visualization.viewer.write_html 读取已有 artifacts/m3-single-trap/recording.json、m3-viewer-serial/recording.json、m3-viewer-row-column/recording.json 重新生成。缺这些历史数据时，先按原示例和 M3-A 日志重建。主服务 8766 保留；专用 QA 8767 已关闭。用户页面不被验收清空或重置。

收尾检查：关闭专用 QA 服务后，在浏览器重新编译显示“编译请求失败 / Failed to fetch”，没有伪造成功；主服务仍显示正常完成。相关更新文档的本地链接检查通过。源码 SHA-256 清单保存于 artifacts/circuit-workbench-demo/source-manifest.json。

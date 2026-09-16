# 工作台配置入口

有序后端的 x/y 偏移为**初始相对偏移**，不是运行期间固定的轴间距。编译器自动重构抓取和作用行列，终态恢复初态；`rigid` 才固定间距。`nonuniform_pairs` 是仅替换门列表的 6 原子以上 CZ 示例，完整复现输入见 `../workbench/dynamic_aod.json`，见 [说明](../../docs/dynamic_aod_workbench.md)。

维护入口为 [workbench.json](workbench.json)，由 Python 读取并通过 `/studio-catalog.js` 提供给浏览器。目录、初始默认值和预算不再分别硬编码在 Python/JavaScript 中。

| 配置 | 用途 |
| --- | --- |
| `algorithms` | 自定义模式允许选择的通用算法、名称、各自默认搜索预算；只可引用已实现通用算法 ID，不能加入专用 QEC/patch 算法。 |
| `compilation_defaults` | 通用预算默认值；算法自己的 `defaults` 覆盖同名默认值。 |
| `default_algorithm` | 新自定义草稿使用的算法；切换电路示例不改变它。 |
| `workspace_defaults` | 新自定义草稿的原子数、布局、seed、AOD 行列与相对偏移、EZ 停驻保护。 |
| `circuit_presets` / `default_circuit` | 纯电路示例菜单及新草稿的默认电路。生成逻辑属于代码，示例只替换 gates。 |
| `demos` | 顶部完整实验菜单；`input_file` 引用目录内对应 JSON。 |
| `architecture` / `coordinate_mode` | 当前已接入 rigid / relative_offsets 的声明；加载器拒绝虚构能力。 |

`demos/*.json` 固定完整门列表、协议元数据、初态、AOD 和编译配置。读 demo 时直接加载文件，再执行现有输入/物理校验；不再调用实验生成器重建输入。修改某个 demo 请修改它自己的文件；下一次启动后形成新的配套锁定实验。生成器源码仍保留供科研脚本与未来重新设计实验使用。

文件只保留输入：编译预算放在 `compilation` 内；不保存重复 flat compiler/budget、`compilation_backend`、AOD 容量或运行统计。QEC data/ancilla 布局等派生结果仍由现有声明模型计算，不能通过增删 JSON 字段改变真实硬件约束。

运行进程按启动时配置快照工作，修改后**重启工作台服务，再刷新页面**。已打开的草稿不会自动套用新默认值；浏览器保存的用户配置也不会被静默覆盖。缺失文件、未知算法、重复 ID、越界预算或目录外 demo 路径会明确报错。

模式边界保持：完整 demo 配套锁定、自定义独立选算法、电路示例仅替换门、手动编译。当前通用多交点规划仍限单行 10 μm 等间距；配置文件不能使未实现的二维非均匀规划自动可用。详细归属与路线见 [架构说明](../../docs/studio_configuration_layers.md)。

2026-09-16：默认算法改为 `ordered_greedy`，平台默认 `row_column_orthogonal`；有序贪心/SMT 已接入原通用工作台。`aod_backend` 属于平台，`motion_router`/`readout_mode` 与搜索预算属于 compilation。保留旧算法与原 demo 文件，新增 `demos/ordered-qec-ghz2.json`。详见 [通用工作台升级](../../docs/ordered_workbench.md)。

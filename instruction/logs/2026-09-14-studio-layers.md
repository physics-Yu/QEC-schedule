# 2026-09-14 · 工作台配置减法与分层

- 状态：COMPLETED（配置边界、界面与本轮验收；底层后续迁移仍待实施）
- 用户授权：拆分锁定实验 demo、独立电路示例、通用算法和平台配置，明确派生字段与 AOD 相对坐标，优化界面并实际验收。
- 起点：main b2eb16d；工作台推荐策略按协议隐式切换到专用实现，模板同时替换电路/初态/平台，用户无法区分这些职责。
- 本轮保留物理核/schema19。限定在配置边界、能力目录和界面，不将 QEC 专用执行器改名冒充通用算法。
- 新模块 studio_config 提供 demo/通用算法目录及服务端锁定校验；旧输入 API 兼容保留，在新 UI 中作为只读历史载入。
- 已完成：前端、服务端能力边界、测试、[参数归属与架构路线](../../docs/studio_configuration_layers.md)、真实 GUI 验收。

## 交付与实现

- 入口：http://127.0.0.1:8790/ 。已编译且可继续编辑：http://127.0.0.1:8790/?job=679c19d84cd444c680517fdd71dedec9 。本轮服务PID19496；旧8788/8789服务与用户旧实例未动。
- `studio_config.py`：六种通用算法、五个完整demo目录，demo规范化完整锁定校验，自定义禁止专用编译器/布局混入。`studio_model.js`：纯门列表生成器。不是将原有专用代码改名为通用。
- `workbench.js/html`：顶部实验选择，自定义草稿恢复、demo锁定、独立电路示例、无自动编译；删除GHZ专用编辑控件，保存与搜索折叠。AOD相对偏移、只读容量和固定rigid架构说明明确。
- 旧无studio输入仍由原API兼容，在新UI作为只读历史展示。新自定义输入/已编译结果仍可编辑、重新手动编译；模式切换不改旧执行记录。
- 分支保持main，本轮按用户要求交付本地界面与规划；未新增分支、未进行新Git提交或推送。

## 失败与修复

- 初次专项57通过、3个fixture错误：指定的pytest basetemp父目录未创建。创建本轮artifact目录后重验，未修改生产逻辑或断言来规避。
- 真实GUI测试1×3、列偏移[0,10,30]，得到旧 `MULTI_TRAP_PLATFORM`，0门/0μs；失败产物 `runs/c6d9d84aaf6c4b2cb7c7ae4a1ffb4c05` 保留。硬件可以表示该相对几何，但MultiTrapGreedyCompiler仅支持单行10μm等间距。本轮把能力检查前移至UI与worker启动前，允许几何预览/保存、明确禁编译；没有更改物理硬约束或伪造成功。
- 浏览器自动化首次部分填值未触发表单提交，后续编译按钮保持禁用；通过真实键盘输入与Tab提交后核对生效。未将工具未提交的输入当作软件已接受。

## 验证

| 本轮检查 | 结果 |
| --- | --- |
| `pytest tests/test_studio_config.py tests/test_workbench_compilation_config.py tests/test_workbench.py tests/test_atom_statistics.py` | 76 passed / 30.59s |
| 补充锁定预算及worker启动前拒绝，重跑 `tests/test_studio_config.py` | 19 passed / 16.11s；与上一行重叠，不相加 |
| 六种通用算法同一普通H/CZ/T电路 | 全部真实执行完成；输入不变、门数/原子统计核对 |
| 五个demo规范化/配置和门更改/专用混入 | 往返一致，更改被拒绝，普通模式不能混入专用实现 |
| 非均匀相对坐标 | pose=(20,-30)、offset x=[0,10,30]/y=[0,15]，交点(1,2)=(50,-15)，六个矩形交点；规划不支持则提前拒绝 |
| 纯四物理比特GHZ示例 | 理想XXXX和三ZZ稳定子独立验证；不声称surface编码GHZ |
| 真实GUI自定义 | 关键路径、1×3等间距；载入混合电路后手工再加H；4/4门、954.3μs、38操作；32×完整播放到终点 |
| 真实GUI锁定demo | 四逻辑GHZ载入68原子、专用算法与平台均锁定；切回恢复自定义草稿。四H demo真实4/4、1μs |
| 显示 | 当前桌面视口无水平溢出、console errors为空；读保存job后仍可编辑并显示正确完成结果 |
| 语法与差异检查 | 两份JS Node语法检查及git diff --check通过 |

证据目录 `artifacts/studio-layers-2026-09-14`：test-attempt1.json / test-attempt2.json / test-final.json / test-final-boundary.json、browser-acceptance.json（含六份源哈希）及三个真实编译job。仅三个job对应三次明确编译点击；选择demo、改设置和读保存结果均未自动创建编译job。

未跑全仓suite、移动端浏览器验收、完整GHZ物理重新编译或量子重放；没有新增通用QEC、二维非均匀规划或row_column工作台支持。

## 下一步

按[架构路线](../../docs/studio_configuration_layers.md)先定义输入v2及legacy adapter，去掉flat镜像与重复配置；再让规划器自己声明能力并抽取通用矩形运输。QEC协议/译码与运输策略进一步分离后，才开放通用QEC电路组合。沿用A0–A8性能方案，不能将本轮UI分层当成整个迁移完成。

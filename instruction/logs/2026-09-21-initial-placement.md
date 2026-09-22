# 初态放置独立模块与非可视化验收

用户范围：实现策略包 placement/、自定义电路布局编译，算法/机器验收先行，界面待用户后续指定。

## 变更

- 新增 models/cost/initial/dynamic 与统一导出；有限退火、整组平移种子、整行/列互换、锁定位、小规模穷举、兼容图案缓存及代理/物理分离结果。
- app 增加 JSON 和 Platform 布局接口；CLI 保留完整电路和输入 hash，非法输入生成失败报告。
- 独立实验固定后续策略与物理 backend，只改变初态；ZAC执行适配器新增可选 explicit terminal，默认行为不变；实验工厂可显式设置区边界。
- 新增测试、规模对照、checkpoint/逐原子审计与JSON配置示例。
- 动态落点只定义接口并提供固定归还基线；现有ZAC/测量策略不迁移。环境、现有UI和物理硬规则未改。

## 验收

- `python -m pytest tests/test_initial_placement.py tests/test_environment_boundary.py tests/test_parking_compatibility.py tests/test_zac_reuse.py -q --junitxml=artifacts/initial-placement/pytest.xml`：51 passed / 9.42 s。
- `python tools/check_architecture.py --output artifacts/initial-placement/architecture.json`：177模块，0反向依赖。
- `python tools/check_initial_placement_algorithm.py`：8/100原子×3seed×2评分12份；100原子1000迭代约0.57–0.66 s，兼容分组基线10→8/6/7（仅图案代理）。
- `examples/check_initial_placement.py`：10×10 SLM；四原子3CZ 4970.426391→4494.499962 μs；八原子12CZ 18998.209060→16894.475105 μs。正式5份物理执行/独立重放全部通过。
- `tools/audit_initial_placement.py`：最终holder/masks/AOD一致、相同circuit/hardware/geometry、逐原子总路程一致。
- 自定义JSON CLI与混合H/CZ/T的已有Platform API机器测试通过。MEASURE/RESET/反馈只验证布局阶段的依赖保留，本轮未新增完整测量物理性能对照。

## 失败与纠正

- 首次 `four/` 的AXIS_BOUNDS：SLM维度误作AOD容量，关闭轴也要在视场内。修正实验参数和显式视场范围；旧失败不删除，最终见 `four-final/`。
- 原始单原子退火难以跨过拆开同排配对造成的局部障碍，加入合法整体平移与行列互换，不写死门或qubit布局。
- 八原子代理候选1真实20011.736 μs，差于基线；如实保留并由物理评分排除。该反例说明代理和实际路线仍有差距。
- 开发测试中两处fixture误设（兼容图案预期/未知qubit选择）及旧工作台输入缺column/编译配置已按原合同修正，不放宽断言和环境条件。

## 交付与后续

合同：`docs/initial_placement.md`。结果：`artifacts/initial-placement/acceptance.json`。配置：`configs/placement/initial-eight.json`。

未运行GUI，未改UI，无Git提交/推送。初态视为已准备好，不含随机装载后的组装；物理对照限2–16原子CZ适配族。下一项是根据用户指示做布局编辑/解释/前后对比的共用viewer集成；100原子完整物理编译、初态组装和新动态放置均未宣称完成。

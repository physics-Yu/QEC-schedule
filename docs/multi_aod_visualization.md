# 多 AOD 的真实执行观察

共用 `VisualRecorder` / `viewer.js` 观察同一个 Executor 状态中的所有 AOD。录制没有独立的魔态动画状态：每个移动原子的坐标由已提交 holder 的 `MobileCellIndex.aod_id` 选择相应设备，设备的真实轴配置及已开始 MOVE 决定连续采样。不同设备同为 `(row=0, column=0)` 的交点保持不同身份。

`neutral-atom-view/2` 的每帧增加 `aods`、`axes_by_aod`、`movements`、`transfers` 与 `primary_aod_id`。原 `aod`、`axes`、`movement`、`transfer` 字段继续表示主设备，以便历史单 AOD 录制回放。各 MOVE 的 `aod_id`、`moving_atom_ids`、`moving_count`、源/目标轴与资源只记录该设备；同时操作仍共享一个物理时钟。批次保留完整 `gate_ids` / `intended_pairs`，画布显示每一个实际作用对，界面以批次大小和码块数量说明并行。

场景可附加只读标签，原子、trap、区域及坐标仍来自状态。示例：

```python
recorder = VisualRecorder(state, scene_metadata={
    "aod_labels": {"AOD_0": "算法 AOD", "AOD_MAGIC": "魔态 AOD"},
    "zone_labels": {"compute": "COMPUTE", "mz": "MZ"},
    "atom_roles": {"Q000": {"role": "data-0", "patch": "L0"}},
    "patches": [{"id": "L0", "label": "L0 · d=3", "bounds": patch_bounds}],
})
```

只允许这四个元数据键，不能覆盖 `bounds` / `traps` / `zones` 等几何真值。码块框表示声明的码块分组，不参与物理校验。AOD trap 仍以相同橙色圆环表示，每台的名称、活动交点、容量和完整轴坐标分别显示，资源时序单列各设备的实际占用区间。

验收为 `tests/test_multi_aod_visualization.py` 的真实双设备同步 MOVE、各设备相同交点编号不混淆、录制只读及 Node 正向/反向定位；另有既有单台记录与 Raman 批次回归。Node Canvas/DOM 检查不代替真实浏览器验收。该观察能力不意味着完整物理 Shor、魔态工厂或含噪容错已经执行。

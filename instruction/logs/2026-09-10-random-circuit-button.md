# 2026-09-10 · 随机载入量子线路

- 状态：COMPLETED（真实浏览器检查受工具连接限制）
- 用户要求：量子线路区增加随机载入按钮。
- 范围：保留当前原子数/layout/seed，随机生成可编辑混合 gate，经既有 change/编译/回放链路；可撤销。不更改固定 1 μs 或 32× 约定。
- 默认规模：按原子数生成 4–12 门；单原子仅单比特，多原子至少有 U3 与 CZ，CZ 操作数不同，每列一门。

## 验证

- 修改 workbench.html / workbench.js：新增随机载入按钮与生成函数，经既有 change() 保留初态、撤销栈、自动编译/取消/版本隔离。无新增后端/另一套动画路径；继续保持单比特 1 μs 和最大 32×。
- 每次随机 4–12 门，门 ID/列唯一，CZ 操作数不同，1Q 角度有限。布局 seed 不改变；随机门通过导出实际 JSON 保存。
- 离线临时 VM/DOM 替身（不是浏览器）：200 组输入（1/2/4/16/32 原子），检查操作数/参数/门数、保留 layout/seed、撤销/重做及单次防抖编译，PASS。首轮替身缺 dataset、插桩未兼容 CRLF，修正检查脚本后通过，非产品故障。
- 从实际前端生成器保存 artifacts/random-circuit-check/input.json，并运行下面的编译命令：8 gates、56 operations、128 commits，completed；wall 2373.1290590000576 μs、Raman 6 μs、CZ 0.6 μs、6 LOAD/6 OFFLOAD。
- HTTP 页面与当前磁盘源码一致，新按钮和 handler 已提供。检查发现示例下拉缺少 mixed option 开始标签，修复后 body 标签平衡检查通过。
- CUA getState 仍报 nodeRepl.fetch request failed，未完成本轮真实浏览器视觉验收；没有重跑全套 Python 或把历史 PASS 冒称本轮结果。

## 复现与交接

```powershell
python examples/circuit_workbench.py --port 8766
python examples/compile_workbench.py --input artifacts/random-circuit-check/input.json --output artifacts/random-circuit-check
```

输入为本轮离线 VM 中固定 RNG 流抽取的前端线路，初始条件 4 原子、shuffled、layout seed 73、reverse。浏览器按钮实际使用 Math.random，每次点击重新抽样，layout seed 只控制初始映射。源 JS/HTML 由正在运行的服务动态读取，无需重启后端；用户保存草稿后刷新可见。

文档、visualization、handoff 和日志索引已更新；未改已完成历史日志、提交或发布。后续仍按固化 pipeline/M3 顺序推进，随机线路的逻辑合法性不证明任意物理布局可路由。

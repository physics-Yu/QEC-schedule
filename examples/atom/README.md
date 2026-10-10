# R4 原子计划示例

two_block_slice/ 来自真实 R1→R3→R4→R5→R6 软件链，fixture=false；测量返回全部为显式 fake 场景。首切片含两 Surface-17 的初始化、综合征、transversal CX、读出/reset，不是完整 Shor 或硬件运行。

复现（仓库根，共享 Python 3.12）：

```powershell
$env:PYTHONPATH='src;.'
& scripts/.venv/Scripts/python.exe examples/atom/generate.py --with-runtime
& scripts/.venv/Scripts/python.exe -m na_pipeline view --atom examples/atom/two_block_slice/atom_program.json --device examples/atom/two_block_slice/device.json --trace examples/atom/two_block_slice/trace_0.json --report examples/atom/two_block_slice/validation_0.json --out examples/atom/two_block_slice/viewer_0.html
```

profile.json 记录输入与源码哈希、Python/主机、输出字节清单、各阶段成本和检查结果。validation_0/1.json 是实际 R6 检查器输出；viewer_0.html 为 R7 按同一数据生成的离线查看器，视觉确认仍待用户。

rejected_budget.json 记录 max_ops=3 的 OP_BUDGET_EXHAUSTED，complete=false。共享轴、额外广播边、多体度数>1 和未知参数拒绝例子见 tests/backend/test_compiler.py。

接口、策略限制和 T030 前工作见 knowledge/roles/R4/interface.md、compilation.md、status.md。

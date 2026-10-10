# T404 实际策略证据

最终目录是 **qualification-v4/**，不是较早尝试。它由真实 R2/R3/R1 输入、R4 Enola函数内核/StrategyLibrary、R5 LogicalBlockController、R6 独立观察与验证、R7 查看器串接。

入口：qualification-v4/summary.json、run-report.json、syndrome-strategy.json、interface-examples.json 和 viewer.html。完整运行与Enola观察为run.json.gz、enola-observation.json.gz；gzip不删内容。binding-costs.json是纯绑定复查成本，不是另一次执行轨迹。

场景显式fake=1，非量子采样。34原子、11逻辑调用、2192实际完成动作、80结果；四策略及连续运行R6报告通过，用户视觉与R0集成确认另列。实际Enola模式是enola_function_kernel，不是完整Enola.solve或上游codegen。

v1保留缺少R2映射/并行例的未验证报告；v2/v3保留全零路径的结构检查，但其末端条件门skipped，调用重叠不作为实际物理并发证明。v4要求两侧事件均completed、原子集合不交且正重叠。

使用新目录复现：

```powershell
$env:PYTHONPATH='src;.'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONDONTWRITEBYTECODE='1'
& scripts/.venv/Scripts/python.exe examples/atom/t404/run_qualification.py --out examples/atom/t404/recheck --fake-value 1
& scripts/.venv/Scripts/python.exe examples/atom/t404/binding_costs.py --dir examples/atom/t404/recheck
```

预算、持久作业和全部来源见 knowledge/roles/R4/T404-delivery.md。binding.fixture.json 是最初故意不完整的字段拒绝例，不能用作集成成功输入。

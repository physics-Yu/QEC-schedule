# 完整 Shor PBC 对编码后端的要求

这里直接审计 `--complete-pbc` 的实际逻辑导出，不把两个 patch 的 ZZ/XX 示例当作完整算法的物理实现。默认 ε=1e-3、seed7 的完整算法每 shot 消耗 3500 个资源。下面是这些 rotation 的 data Pauli 组成；每个实际 joint observable 还包含 magic resource 的 Z。

| Data basis 类别 | 数量 |
| --- | ---: |
| X | 619 |
| XY | 526 |
| XYZ | 774 |
| XZ | 194 |
| Y | 650 |
| YZ | 375 |
| Z | 362 |

实际 joint measurements 中 **2325 项含 Y，3138 项混合不同 basis**。data weight 1–8 的数量依次为 1240、552、716、162、260、143、241、186；加上 resource 后 joint weight 为 2–9。因此只实现两 patch 的 homogeneous ZZ/XX，无法覆盖这份完整 PBC。observable 的正负号和反馈条件还需要带入编码后端。

若采用本项目固定的 weight-3 logical X/Z strings、weight-5 logical Y=iXZ string，逐项展开 data 与 resource 的物理代表元，实际最大 support 为 **37 个 data 原子**。这是 observable 的支持集大小；它不等于已通过的 cat 电路或容错资源估计。若改用运行时 Clifford frame，后续 observable 的支持可能改变，原始导出的 weight9 和展开后37都不能充当该后端的通用上界。

现有连续组合接口已经能保留 A/B 编码态、syndrome sector 与测量历史，并明确回收 C。下一项应实现任意 mixed/Y product 的 nondestructive encoded measurement，以及条件 S_P/Sdg_P 和 Pauli feedback；之后才接入 encoded magic preparation/injection、完整资源调度、解码和独立物理重放。现有 Executor 的精确量子跟踪支持 Clifford 稳定子，直接提交 tracked T 会明确拒绝；不能把理想 logical magic resource 输入当作其物理制备已经完成。

12 个算法 patch 的基础是 **204 原子**（108 data、96 syndrome）。3500 是消耗总量；它不表示3500个资源 patch 同时存在。factory、联合测量辅助、缓存、备用和实际 physical peak 需要由完整后端与 schedule 决定，当前保持 `null`。

可重新生成 inventory：

```sh
python examples/run_shor15_stage.py --complete-pbc --epsilon 1e-3 --seed 7 --output artifacts/shor15/full-pbc
python tools/audit_shor15_encoding_requirements.py --input artifacts/shor15/full-pbc/complete_adaptive_pbc.json --output artifacts/shor15/encoding-requirements.json
```

第二条只读前一条生成的文件。输出中的 `two_patch_homogeneous_shape_count` 仅说明 observable 的形状相同，仍缺 encoded magic state，不能据此宣称这些 injection 已可物理执行。

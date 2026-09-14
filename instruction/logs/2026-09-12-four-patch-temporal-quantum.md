# 4C 四patch时域量子协议专项

新增 `experiments/surface_qec_temporal_four.py` 与 `tests/test_surface_qec_temporal_four.py`，两patch协议、物理core和旧策略未修改。36data+32anc，GHZ树A→B后A→C/B→D，prepare加三噪声轮和真实closing，128位reported全局支持检查、16位CSS条件反馈；接口与范围见 [协议](../../docs/surface_qec_temporal_four_protocol.md)。

默认实际门表1868槽、507CZ、160MEASURE/RESET，421声明事件独立去重373历史。首次命令 `C:/python312/python.exe -m pytest tests/test_surface_qec_temporal_four.py -q --disable-warnings --maxfail=1` 得到 **437 passed in 1438.13s (0:23:58)**，exit0。421真量子案例、独立反对易true/reported预期、32checks/XXXX/AB BC CD ZZ、全部辅助复位及边界负例通过；无意外失败、无重试。结果/源码SHA256：[result.json](../../artifacts/qec-roadmap/step4C-quantum-tests/result.json)。

代码已冻结。未运行完整物理编译或浏览器；不得把此量子结果当作68原子联合运输通过。下一步由主任务在布局/分组物理独立重放通过后，按预算运行完整代表，再做真实可编辑重编译与双模式32×验收。本轮保持原68比特完整构造校验，没有引入量子缓存或跳过检查。handoff由主任务统一整合，避免覆盖并行物理验收状态。

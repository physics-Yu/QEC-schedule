# 2026-09-21 初态优化接入 Demo 原可编辑线路

用户要求在demo index的可编辑线路内插入并行初态优化，并亲自可视化验收。本轮直接接入Atom Studio，不替换原编辑器，不改物理规则或新增RL，不提交推送。

实现：新增app/studio_placement组装/任务服务，原workbench API增加placement路由，原HTML/JS增加参数/对照/回放切换。复用策略placement和实际独立worker，严格继承用户电路、配置及选定的有序贪心/SMT。默认256/16/4/stable与SZ空位选项在configs/studio/workbench.json固化；普通compile行为保持。Demo UI由build_demo_bundle重新导出，源文件位于src。

空位选项显式在当前SZ内增加关闭的5μm候选SLM，两边平台相同；不增加世界边界或AOD容量。已准备初态不计装配时间。不为固定QEC协议开放自动重排，避免无协议验证的重排冒充逻辑正确性。

验收命令：`pytest tests/test_studio_placement.py -q` 10通过（8.58s）；`pytest tests/test_studio_config.py tests/test_parallel_placement.py tests/test_environment_boundary.py -q` 38通过（60.44s）；`node tests/ordered_workbench_controls.cjs http://127.0.0.1:63410` 通过（实际API/JS，DOM与viewer为替身，另有真实GUI）。check_architecture 185模块0违规；Demo bundle 134文件核验通过。

真实GUI任务 `4ce7462a81ad476d8fd765c31976b677`：由首页链接进入、鼠标将四个H加上CZ(Q000,Q003)/CZ(Q001,Q002)，实际运行16候选/4进程。有效2、拒绝14：12份ORDERED_STAGING_EXHAUSTED，2份PATCH_EZ_CAPACITY；没有放宽硬约束。基线与选中均1410.940231μs，无收益，装载3、路程212μm，32.9186s墙钟。界面增加有效数量，明确通过的是基线与选中结果。32×自动到终点6门、基线切换/终点、刷新保存链接、加一个H后旧结果禁用均通过。再点击搜索和停止，任务 `4f85b968bb6d4cf9b3d481c1e8091b7b` 确认cancelled，未用旧结果替代新电路。

浏览器曾使用更新前元素索引导致点击目标已变；改用当前可访问标签恢复。一次读取UTF-8产物未指定encoding触发GBK错误，改为明确UTF-8后正常，不涉及产物损坏。上述是工程问题，无物理模型修改。

交付服务由demo/launch.py启动，PID44892；首页63413、原工作台63410、SMT63411、QEC63412。输出 `artifacts/studio-placement-delivery/runs`，旧60054服务保留。结果恢复无需重新编译。取消需等待当前波次；更高吞吐/异步搜索、专用QEC任意重排不在本轮范围。

交付前补验：check_demo_http通过首页/三工作台/动态链接/实际资产哈希/非法输入400。真实截图发现850–950px旧.settings网格影响新增卡片，已为placement面板限定单列设置和双布局卡片，重新导出后GUI截图确认修复；结果有效数2/16明确可见。交付页已标记保留。

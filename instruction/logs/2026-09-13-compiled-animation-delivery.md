# 2026-09-13 · 完整动画交付

- 状态：COMPLETED
- 用户要求：将动画编译好交付。
- 输入范围：用户当前链接的saved job `87eef4dc58e467e0e6b423bfda158c43`，四逻辑GHZ/68原子/1868槽。CUA枚举失败，未读取或改写用户页面可能存在的未提交草稿；交付明确基于链接对应的已保存实例。
- 执行方式：复用`artifacts/qec-roadmap/step4C-resumed-attempt3`已完整编译并通过515计划独立重放的记录，用当前共用viewer生成可独立打开的HTML。没有重复小时级编译，不声称本轮重新运行物理compiler。
- 生成器：`examples/export_saved_animation.py`；实际浏览器全程检查：`examples/check_delivered_animation.py`。
- 打包初次校验发现硬写十进制105285.6与原始浮点105285.60000000036不同。保留recording/result时间精确一致断言；对展示预期使用绝对1e-7μs容差，没有改recording、事件或时间。
- 产物：`artifacts/deliveries/ghz4-animation/animation.html`（内联viewer与完整recording约41MB），`circuit.json`，`delivery.json`含来源SHA256与fresh_physical_compile=false。默认关键帧32×，打开后手动播放。
- 本地动画链接：http://127.0.0.1:8789/animation.html ，静态服务PID27044，仅loopback。文件也支持离线打开；8788可编辑工作台保持。
- 验收：真实Edge全程播放PASS：124.75秒到终点105285.60000000036μs，1868槽，68原子holder/坐标与初态精确一致；无停滞、无page errors，file://离线加载PASS。证据playback-check.json、ready-to-play.png、completed-playback.png；root已检查初始交付图。manifest标ready，动画HTML约41MB，不依赖在线服务。

# 2026-09-22 ZAC 页面服务恢复

用户反馈网站打不开。检查发现 52813 与旧 49901 均没有 ZAC workbench 进程，绕过代理的 HTTP 直连超时；经系统代理的请求返回 502。旧日志最后为正常的 200 请求，未记录 Python traceback，无法确定先前进程退出原因。

`benchmark-grid` / `benchmark-large` 的 benchmark.json、汇总 HTML 及 32 原子随机回放文件仍存在。本轮不重跑实验、不改物理或前端源码、不重新生成结果。

使用 `C:\python312\python.exe examples/zac_reuse_workbench.py --port PORT` 从项目根目录重新启动原服务；通过 Windows `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`、关闭 stdin、独立日志文件启动，不占用启动命令的标准流。52813 的 PID 为 19248，49901 的 PID 为 15460（仅为本次启动快照）。日志位于 `artifacts/zac-reuse/server-recovery-20260922.log` 与 `.err`。未设置开机自启或自动重启。

验证：启动命令结束后，从新 shell 对两个端口的 `/`、`/api/demos`、`/benchmark-grid/index.html`、`/benchmark-large/index.html`、`/benchmark-grid/random-n32-d8-s20260921/reuse/index.html` 直连均返回 200。回放 HTML 为 5681954 字节。

应用内浏览器控制最初连接失败；重置当前自动化会话后恢复。实际打开复杂线路汇总，进入 32 原子随机的双版对照，点击 g0000 定位到 9048.470 μs；页面显示 16 个 CZ 同时作用，已检查完整电路、回放控制和 32 原子画布截图。此轮为页面恢复检查，没有重新声明完整物理验证或双模式全程回放。

入口仍为 `http://127.0.0.1:52813/benchmark-grid/index.html` 与 `/benchmark-large/index.html`，旧 `http://127.0.0.1:49901/?case=eight` 也可继续使用。

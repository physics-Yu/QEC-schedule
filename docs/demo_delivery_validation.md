# 对外 Demo 发布核验 · 2026-09-14

本轮验证的是可移植交付，不重新宣称已完成任意平台规划或全噪声 QEC。

## 独立目录与依赖

从 Git 暂存树导出 ZIP，解压到含空格和中文的独立目录；未复制旧 artifacts、用户虚拟环境或旧任务内存。使用 Python 3.12 新建 venv，只安装 `.[smt]`（z3-solver 5.1.0.0），运行 `demo/launch.py --port 0 --no-browser`。首页和两个后端均分配新端口。

Windows / Edge 实机通过；macOS/Linux 启动路径、进程调用无 Windows 专用依赖，但未实机测试，不能将本次独立目录验证称为三个操作系统均通过。

## 本轮结果

- 60 项环境边界、SMT、工作台配置文件/分层及工作台回归通过。
- 131 个包内 Python 模块架构检查通过，环境无反向导入。
- Edge 浏览器 18 项检查通过，无脚本错误：动态端口导航、不自动编译、四 H 真编译、导入编辑五门真编译、SMT 编辑后三个策略真编译及动画推进、离线入口/SMT/GHZ 回放、GHZ 终点定位、720px 无水平溢出。
- 首次浏览器验收发现导出提示脚本的换行转义错误，已修导出器并重跑完整本轮浏览器检查；失败证据保留，不以更改断言掩盖。
- GHZ 仅复用原有完整执行与独立重放证据，本轮检查离线加载、播放推进和终点定位；没有再次进行小时级 QEC 编译或整段独立物理重放。
- 导出器只替换 GHZ 外层的旧电脑编辑器链接，内嵌物理记录和 viewer 不变；delivery.json 分别保留源动画哈希和当前导出哈希。
- Git 导出后的 Demo 文件字节与 manifest 一致；入口文档/本地资源链接、固定本机 URL、常见凭据模式及 Git 文件大小均检查。

本地详细证据在 `artifacts/portable-check/`，不作为下载运行依赖。公开交付本身的清单在 [demo/manifest.json](../demo/manifest.json)。没有运行全仓完整测试或跨平台 CI。

## 复核命令

```sh
python tools/check_demo_bundle.py
python tools/check_architecture.py
python -m pytest -q tests/test_environment_boundary.py tests/test_smt_batch.py tests/test_studio_config_files.py tests/test_studio_config.py tests/test_workbench.py
```

浏览器专项脚本为 `tools/accept_demo_bundle.py`，另需 Playwright 和可用 Chromium（Windows 自动使用已安装 Edge）。启动 Demo 后，将 `--session` 指向启动器生成的 session.json，`--demo` 指向被测试仓库的 demo 目录，`--output` 指向检查输出目录。

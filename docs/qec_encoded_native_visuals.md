# 完整编码 Shor 的原生操作视图

此视图从已保存的完整原生电路、实际参考投影、功能索引、Pauli frame 和原生核证据读取数据。它展示门索引与数据流，不生成原子运输、物理placement或微秒时间，不宣称Executor已执行、含噪容错或真实硬件结果。

维护源码为 `src/neutral_atom_experiments/qec_pbc/encoded_native_visuals.py` 与 `encoded_native_viewer.html`。应调用 `render_viewer()` 重新生成页面；不要手改运行包中的HTML。HTTP包装由应用提供，读取同一不可变目录。

直接入口为`python examples/serve_encoded_shor15.py --run-dir RUN_DIRECTORY --port 8769`，只绑定127.0.0.1，提供下面三个只读GET接口；首页从维护模板生成。完整缓存／线路生成命令见[生成器说明](qec_encoded_shor_native.md)。当前实际完整重试包展示在`http://127.0.0.1:8772/`，页面终端数字、全部失败和功能范围来自同一manifest。

## 读取契约

`EncodedNativeView(run_directory)` 只接收 `manifest.json` 中 `complete=true` 且 `physical_executed=false` 的原生参考运行。manifest必须以SHA256与bytes绑定 `summary.json`、`roles.json`、`certificates.json`、`functions.jsonl`、`frames.jsonl`、`native_gates.jsonl`、`native_projections.jsonl`。初始化以分块方式校验全部文件，不将百万门载入内存。后续请求检查文件size、mtime、ctime、inode保持一致；任何变更使缓存通过失效并拒绝显示。

每个功能的精确原生门与投影byte span、原始index、function_id、count与SHA须相符。首次读取所选功能分别校验完整门span与投影span；所有投影还须按实际门序对应同一native ID和M/RESET类型。后续最多缓存128个span的已核对状态。每次只返回12个真实native门与64个真实投影，另附当前12门中M/RESET的实际关联报告。source IDs、依赖、条件、epoch、报告位、Born概率及source字段保持保存时的值；不存在的值显示未提供，不假补0或成功。

角色映射来自绑定的 `roles.json`。稳定子支持来自其中 `code_checks`，不另写一份UI码定义。3×3示意仅表达码结构，图中位置不代表物理placement。cat/helper身份从真实门targets与角色映射显示。kernel certificate及frame SHA必须能解析到绑定的证据/snapshot，不能通过pass标签替代来源。

## HTTP包装接口

应用只需创建一个 `EncodedNativeView` 并提供三个GET端点，默认base `/api/encoded-native`：

| 端点 | Python方法 | 有界返回 |
| --- | --- | --- |
| `/overview` | `overview()` | summary、roles、shot/kind列表、manifest指纹、明确scope |
| `/functions?shot=0&injection=4&kind=cat_joint&start=0&count=12` | `list_functions()` | 筛选后总数及最多100条紧凑功能行，页面默认12 |
| `/function?id=function.0000000&gate_page=0&projection_page=0` | `function_detail()` | 完整功能绑定、12门、64投影、引用kernel及frame snapshot |

query转换为真正非负int；布尔、负数与超限count拒绝。缺失筛选用 `None`。未知function拒绝。读取或指纹变化应返回错误并让页面停止播放，不能回退到模拟fixture或旧PASS。浏览器在每个响应核对同一个manifest SHA，API来源限制为本地绝对路径。

调用 `render_viewer(output_html, api_base='/api/encoded-native')` 生成入口。模板作为源码维护；安装包需将 `encoded_native_viewer.html` 加入qec_pbc package-data（由根级集成维护）。

## 交互与范围

shot / 注入序号 / 功能筛选定位初态编码、canonical syndrome banks、魔态RESET-H-T或7T与CSS、cat GHZ及两遍核验、XYZ耦合、cat读出RESET、资源九位X读出与RESET、frame更新与释放、终端拉回测量。子阶段按钮从完整功能span中的真实native ID前缀及门类型分组，保存首末ID、起始index和count；按钮跳到该实际范围。选中功能显示真实native circuit、目标Q身份与patch role、每个门的前序依赖和原始条件。上/下门、首/末门、slider、门表或线路图点击、每秒1–32门的演示播放均只改变观察位置；分页按需读取，不加载GB流。无新增量子门的frame功能禁用门播放。

报告页显示native_gate_id、原始bit、条件概率和来源；raw parity与frame snapshot/资源账本在同一功能绑定下显示。frame更新后可查看下一条保存的cat联合测量及其实际Pauli轴；点击时先读取该绑定function，再同步shot、功能和注入筛选、刷新左列表并选中同一ID。这是已有function的语义字段，不预测未生成的运行。实际kernel复用标注“复用已验证原生核”，不暗示每次注入重做17比特dense模拟。终端phase、order、gcd/factors、失败与retry来自summary的实际attempt记录；失败不隐藏。图中轮廓／箭头表达支持与依赖，不代表新增量子操作或光场。

独立测试重点是全局文件改写、重绑manifest后错误局部span/count/index/ID、缺证据/frame、初始化后缓存篡改、边界分页与路径逃逸。浏览器实际交互、390px窄屏和完整运行视觉验收由根级集成记录；这些单元测试不能替代GUI验收。

2026-10-04最终浏览器验收覆盖八类功能、CSS／producer／cat五子阶段／资源H-M-RESET定位、24个frame生成元与下一保存轴同步筛选、实际失败shot全部patch cleanup、phase128→64的连分数／order／gcd。资源27门以32门/秒连续播放至末门；滑块Home／ArrowRight、门表点击及12门分页均定位到真实ID；112条cat报告的1–64／65–112两页可前后核对。390px长manifest SHA最初引起溢出，修复源码换行后client/scroll宽度均375px，失败截图保留。最终页面console无error；没有帧率、运输动画或物理时间验收声明。26个新增视图测试通过，GUI记录和边界见[公开摘要](../references/qec_pbc_validation/full_encoded_shor15_native_2026_10_04.json)。

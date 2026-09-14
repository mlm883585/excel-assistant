# 整合版本本地验证记录

更新日期：2026-09-14。Windows 11、Python 3.13.5、Node 24.13.0、Qwen Code 0.23.3、Univer 0.25.1。覆盖分页工作台与内置编辑器的统一版本。旧记录中的 41 项和 69 项测试属于更早阶段。

## 功能与协议

| 检查 | 本次结果 |
| --- | --- |
| 完整 unittest | 71 项通过（64.189 秒），包含并发初始化与导出复制失败回归 |
| 真实 Qwen CLI + SDK + 本地模型模拟服务 | 完整回归设置 `REQUIRE_QWEN_CLI=1`，验证会话、工具、MCP 产物、权限、失败与取消；客户模型能力另行验收 |
| 前端检查及生产构建 | TypeScript 与 Vite 构建通过；编辑器按需加载，约 5.90 MB，保留实际包体积提示 |
| 工作台真实 RPC | 通过；千条任务、万条事件、300 列虚拟化、十万行翻页及终态停止轮询均已复测 |
| 编辑闭环 | 中文输入、真实剪贴板、撤销重做、查找替换、自动保存、历史只读查看及公式错误恢复通过 |
| 内核操作 | 字体、金额、百分比、合并、冻结、行列、工作表新增/改名/排序/删除、筛选、排序、填充、整列公共格式通过 |
| 公式及格式往返 | 16 个约定函数与跨表绝对引用，共 17 个公式场景通过；日期纪元、序列 60、编号、样式及公式缓存由 unittest 覆盖 |
| 整份核对 | 差异末页、整份采用、继续编辑和重开通过；已采用结果确认导出可达，取消不标记成功，切换视图不会重放已取消导出，继续编辑后旧确认被拦截 |
| 生命周期及故障 | 旧工作簿/任务响应隔离、保存失败阻止切换、重试保留内容、导出取消通过；并发初始化和最终复制中途写盘失败新增回归 |
| 反复打开与销毁编辑器 | 8 轮释放后显式 GC，JS heap 依次约 27、26、26、27、28、27、29、29 MB；未出现持续快速增长。此测量不等于 Windows 进程总内存 |
| 真实 WebView2 | 隐藏 edgechromium 窗口、原生 PPX RPC、17 个公式、自动保存、本机 XLSX 导出通过；资源记录未发现外网请求 |
| 容量与完整性 | 20 万有效单元格载入、末行修改、保存、导出及超限拦截通过；十万行计算和完整差异末页验证原始第 100001 行 |

测试使用独立的合成数据与任务目录。UI 脚本各自启动测试服务，结束后关闭服务和预览子进程；保留工作台与编辑器两组验证，未用新测试替换旧行为覆盖。

## Windows 便携包

| 检查 | 本次结果 |
| --- | --- |
| 最终源码构建 | 通过；桌面与 MCP 重新收集构建，附签名验证的 WebView2 离线安装程序 |
| 桌面 `--smoke` | 实际 `ExcelAssistant.exe` 启动 WebView2、完成页面脚本并正常退出，退出码 0 |
| 打包后 MCP 与固定 CLI | 实际 `DataCraftMCP.exe` 通过真实 stdio 测试，覆盖新增计算、建表等操作；随包 Qwen Code 0.23.3 与固定 Node 协议验证通过 |
| 打包后环境诊断 | 依赖探测与 Agent 探测均通过，覆盖实际 CLI 会话、产物、权限拒绝及取消 |
| 打包后十万行预览 | 实际桌面可执行文件生成后台索引；首批 0.421 秒、缓存分页后端 P95 1.425 毫秒，编号及 NA 文本保持 |
| 对应源码、前端、许可证与哈希 | `scripts/verify_release.py` 通过：3436 个交付文件、379 个源码文件、184 个运行依赖许可证、85 个前端资源；无遗漏或遗留前端文件，总体积约 669.8 MiB |

## 复现与证据

```powershell
$env:REQUIRE_QWEN_CLI = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm run build --prefix gui
.\.venv\Scripts\python.exe scripts/benchmark_workbench.py --skip-baseline
.\.venv\Scripts\python.exe scripts/benchmark_workbook_editor.py
node scripts/workbench_ui_smoke.cjs
node scripts/workbook_engine_smoke.cjs
$env:WORKBOOK_CAPACITY = '1'
node scripts/workbook_ui_smoke.cjs
node scripts/workbook_review_ui_smoke.cjs
node scripts/workbook_lifecycle_ui_smoke.cjs
.\.venv\Scripts\python.exe scripts/smoke_webview_workbook.py
.\.venv\Scripts\python.exe scripts/build.py
.\.venv\Scripts\python.exe scripts/smoke_frozen_mcp.py
.\.venv\Scripts\python.exe scripts/smoke_frozen_environment.py
.\.venv\Scripts\python.exe scripts/smoke_frozen_preview.py
.\.venv\Scripts\python.exe scripts/verify_release.py
```

UI 测试需要本地 Playwright 与 Chrome，可通过 `PLAYWRIGHT_MODULE` 和 `CHROME_EXECUTABLE` 指定已有安装。截图与 JSON/日志保存在忽略的 `build/`，筛选后的合成数据界面图收录于 `docs/screenshots/`。测量口径与结果见 [性能记录](PERFORMANCE.md)。

## 尚需外部验收

客户 Qwen 真实业务、Excel 2016 实机打开与重算、客户样本人工对照、干净客户终端安装、Windows 原生 DPI、客户断外网出站审计和业务人员试用仍需客户环境完成。COM 重算实现与本地模拟模型测试不计为客户验收。生成 Python 继续关闭，操作系统隔离未验收。

本轮仅运行本地验证。GitHub Actions 保持手动触发，未运行云端 CI；本地通过不记为云端通过。

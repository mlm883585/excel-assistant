# 本地验证记录

更新日期：2026-09-14。环境：Windows 11、Python 3.13.5、Node 24.13.0、Qwen Code 0.23.3。

| 检查 | 结果 |
| --- | --- |
| `python -m unittest discover -s tests -v` | 41 项本地通过，包含原业务基线以及环境发现、版本变化、明确 Node 路径、降级、取消、超时、报告与离线安装分支 |
| 真实 Qwen CLI + Python SDK + 本地 HTTP 模型模拟服务 | 接口连接、会话记录、工具调用、MCP 输出生成通过；无工具产物时拒绝成功 |
| 模型可见工具 | 未暴露 Shell、文件读取、子 Agent 和网络抓取工具 |
| `npm run build --prefix gui` | TypeScript 检查和生产构建通过；存在前端主包体积提示 |
| `pip check` | 无依赖冲突 |
| 全新 Git 检出与独立虚拟环境（2026-09-12） | 从官方 PyPI 安装锁定依赖、重新执行两处 `npm ci`；当时 23 项测试和前端构建通过，未借用历史项目快照 |
| 对应源码归档 | 未跟踪配置排除、已跟踪敏感文件拒绝、清单越界拒绝、无 Git 重建和无 WebView2 介质归档均通过 |
| Windows 任务关闭竞争 | 首次云端验证发现监控线程仍持有 SQLite；已修复关闭时等待线程退出，新增回归测试在本地通过 |
| 打包后的 `ExcelAssistant.exe --smoke` | WebView2 启动及页面脚本执行通过，退出码 0 |
| `scripts/smoke_frozen_mcp.py` | 打包后的 MCP 通过真实 stdio 协议生成 Excel，正常退出 |
| `scripts/smoke_frozen_environment.py` | 最终便携包组件加载、固定 Node 进程、真实 CLI 会话、MCP 输出、权限拒绝及取消均通过；显式补充动态 MCP 库打包声明 |
| 随包 Node + Qwen CLI | 输出 0.23.3 |
| WebView2 离线介质 | 已下载微软 x64 独立安装程序，签名 Valid，签发主体 Microsoft Corporation |
| 环境界面与真实 PPX RPC | 本地浏览器验证发现已有 0.21.0、提示尚未验证、真实验证内置 0.23.3、保存选择及业务状态更新；无页面脚本错误，截图已脱敏 |
| 指定 Node 与诊断 Agent | 真实 CLI 的会话、MCP 输出、权限拒绝、取消及实际 Node 进程路径均通过；仅使用临时合成数据 |
| 依赖故障降级 | 阻断 pandas、openpyxl、SDK 导入后，环境与设置 RPC 仍可用；数据目录失败不阻断检测界面启动 |
| WebView2 修复检查 | 在本机完成固定路径、SHA256 和缓存限定的微软签名校验；提权、取消和重复启动通过模拟测试；没有执行真实安装 |
| 开发诊断脚本 | `scripts/doctor.py` 复用共享检查，输出脱敏结果，未配置 Agent 返回警告而不影响基础操作 |

未完成：客户 Qwen 真实任务、Excel 2016 实机、干净客户终端安装、断外网出站审计、业务人员试用与生成 Python 的操作系统隔离。Excel COM 重算实现不计为 Excel 2016 已验收。

验证策略：优先本地编译与测试；GitHub Actions 仅允许手动触发，执行前须获得用户明确要求。首次云端运行失败后未重跑，不将本地修复记录为云端通过。

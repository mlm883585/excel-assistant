# 本地验证记录

验证日期：2026-09-12。环境：Windows 11、Python 3.13.5、Node 24.13.0、Qwen Code 0.23.3。

| 检查 | 结果 |
| --- | --- |
| `python -m unittest discover -s tests -v` | 18 项通过，包含 100000 行完整导出、编码、关联、对账、转换、模板、权限、规则及取消 |
| 真实 Qwen CLI + Python SDK + 本地 HTTP 模型模拟服务 | 接口连接、会话记录、工具调用、MCP 输出生成通过；无工具产物时拒绝成功 |
| 模型可见工具 | 未暴露 Shell、文件读取、子 Agent 和网络抓取工具 |
| `npm run build --prefix gui` | TypeScript 检查和生产构建通过；存在前端主包体积提示 |
| `pip check` | 无依赖冲突 |
| 打包后的 `ExcelAssistant.exe --smoke` | WebView2 启动及页面脚本执行通过，退出码 0 |
| `scripts/smoke_frozen_mcp.py` | 打包后的 MCP 通过真实 stdio 协议生成 Excel，正常退出 |
| 随包 Node + Qwen CLI | 输出 0.23.3 |
| WebView2 离线介质 | 已下载微软 x64 独立安装程序，签名 Valid，签发主体 Microsoft Corporation |

未完成：客户 Qwen 真实任务、Excel 2016 实机、干净客户终端安装、断外网出站审计、业务人员试用与生成 Python 的操作系统隔离。Excel COM 重算实现不计为 Excel 2016 已验收。

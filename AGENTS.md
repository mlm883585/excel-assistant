# Repository Guidelines

## 项目结构与模块组织

本仓库为 Windows 内网 Excel 助手。`main.py` 启动 PPX；`gui/src/` 为 Vue 3 / TypeScript 界面；`api/` 提供 RPC；`assistant/` 实现任务、模型适配、Excel 与 MCP 服务；`data_toolkit/` 为迁入的数据处理核心。

`tests/` 保存 unittest 测试；`scripts/` 提供检查、打包与离线介质准备；`docs/` 保存实现和验收文档。`vendor/` 是固定的 PPX、Qwen SDK 源码，`ppx/assets/` 是打包资源，均须提交。两个历史项目快照只在本地保留，不是运行依赖，不提交其嵌套仓库。

## 构建、测试与开发命令

使用 Windows、Python 3.13.5、Node 24.13.0，在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt ./vendor/qwen-code-sdk
npm ci
npm ci --prefix gui
npm run build --prefix gui
.\.venv\Scripts\python.exe main.py
```

前端构建同时执行 TypeScript 检查。运行 `.venv\Scripts\python.exe -m unittest discover -s tests -v` 验证业务与协议；运行 `.venv\Scripts\python.exe scripts/build.py` 生成 Windows 便携包。先执行 `scripts/fetch_webview2.ps1` 可附加经过签名验证的离线安装介质。

## 编码风格与命名

Python 使用四空格缩进和 snake_case；Vue/TypeScript 使用两空格和相邻代码的单引号风格。避免无关重排。保持业务模块独立于 UI，通过显式注册的 PPX RPC 和任务范围内的 MCP 接口调用。修改上游源码时保留许可证，并同步 `THIRD_PARTY_NOTICES.md`。

## 测试与验收

测试文件命名为 `test_*.py`，使用临时目录与合成数据。数据变更覆盖编码保留、原始行号、重复键、异常记录和输出完整性；Agent 变更验证工具权限、会话、失败与取消。

优先本地测试和编译，不自动触发 GitHub Actions；只有用户明确要求时才运行手动 CI，以节省配额。完整验证设置 `REQUIRE_QWEN_CLI=1` 并安装固定 Qwen CLI，不能跳过真实 CLI 与本地模拟模型的协议测试。这些测试不代表客户模型能力；Excel 2016、客户内网断外网运行与业务人员试用仍按验收清单实测。生成 Python 在操作系统隔离验收前保持关闭。

## 提交与 Pull Request

远程为 `mlm883585/excel-assistant`，默认分支 `main`。使用 Conventional Commits，例如 `fix: preserve source row numbers`。PR 说明用户影响、验证结果和剩余外部验收；界面变更附脱敏截图。提交源码、锁文件和许可证，忽略依赖、缓存、安装包与旧快照。

## 配置与安全

不得提交客户文件、密钥、内网地址、任务数据库或运行日志。密钥通过环境变量配置。保持任务文件副本、明确的路径范围和工具允许列表；源码归档使用 Git 跟踪清单，禁止扫描整目录打包本地配置。

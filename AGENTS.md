# Repository Guidelines

## 项目结构与模块组织

根目录现在是 ExcelAssistant 应用：`main.py` 启动 PPX，`gui/` 为 Vue/TypeScript，`api/` 为 RPC，`assistant/` 为任务、Agent、MCP 服务，`data_toolkit/` 为迁入的数据核心，`vendor/` 保存固定上游源码。`docs/` 的两个项目作为原始快照，新增开发默认针对根目录应用。

当前应用验证命令：`.venv\Scripts\python.exe -m unittest discover -s tests -v`、`npm run build --prefix gui`；启动 `.venv\Scripts\python.exe main.py`，打包 `.venv\Scripts\python.exe scripts/build.py`。真实 Qwen CLI 测试使用本地模型模拟服务，不能替代客户模型验收。Python 任意代码执行在隔离验收前不得开放。

以下为保留的两个旧项目；修改前先确定所属项目，避免跨项目耦合。

| 路径 | 用途 |
| --- | --- |
| `docs/office-assistant-main/` | Windows WPF / WebView2 办公客户端；`src/` 分为 Contracts、Core、Infrastructure、Desktop，`tests/` 按项目对应组织 |
| `docs/office-assistant-main/renderer/build/` | GenOffice 渲染器适配与构建脚本；文档图片位于 `docs/images/` |
| `docs/datacraft-toolkit/datacraft-toolkit/` | Python 数据工具；`src/data_toolkit/` 为核心模块，`tests/` 为测试，`examples/` 为配置及示例 |

两项目各自维护 `scripts/`、`tools/` 和 `config/`。不要编辑 `__MACOSX/` 或 `._*` 解压元数据。

## 构建、测试与本地开发

Office AI：先执行 `cd docs/office-assistant-main`。使用 Windows 和 `global.json` 指定的 .NET SDK（当前为 9.0.313）；桌面项目目标为 `net8.0-windows`。

```powershell
dotnet restore .\OfficeAI.slnx
dotnet build .\OfficeAI.slnx -c Release --no-restore
dotnet test .\OfficeAI.slnx -c Release --no-restore
.\scripts\Run-Dev.ps1
```

以上依次还原依赖、构建、测试、发布并启动开发客户端。渲染器构建另需 Node 24+ 和固定版本 GenOffice 源码，通过 `renderer/build/Build-Renderer.ps1 -GenofficeRoot <源码路径>` 指定。

DataCraft：从根目录进入 `docs/datacraft-toolkit/datacraft-toolkit` 后执行：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-database.txt
.\.venv\Scripts\python.exe src\data_tool.py --help
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

以上创建环境、安装完整依赖、查看 CLI 用法并运行测试。

## 编码风格与命名

C#、Python 使用四空格缩进；C# 类型和公开成员使用 PascalCase，Python 函数及模块使用 snake_case。C# 保持可空引用检查，构建将警告视为错误。TypeScript 沿用相邻文件的两空格、单引号风格。当前未发现统一格式化或 lint 配置，避免无关的整文件重排。

## 测试要求

Office AI 使用 xUnit，测试文件命名为 `*Tests.cs`；新增功能配套行为测试，安全校验先覆盖拒绝场景。DataCraft 使用 unittest，文件命名为 `test_*.py`。未发现数值覆盖率门槛。使用临时目录和合成样本；文档格式变更还需在真实 Office 2016 x64 中验证，单元测试不能替代兼容性验收。

## 提交与 Pull Request

根目录没有 Git 元数据；DataCraft 当前历史仅有 `Initial release of DataCraft data workbench`，不足以推断统一惯例。遵循 Office AI 的贡献指南，采用简短英文 Conventional Commits，例如 `fix: reject invalid editor origins`。PR 说明目的、用户影响、验证命令和外部验收事项；有关联 issue 时附链接，界面变更附脱敏截图。

## 配置与安全

不得提交客户文档、内网地址、凭据、证书、日志或生成产物。数据库密码通过环境变量提供。保持文件工作副本、只读查询和网络允许列表等安全边界。旧文档与源码冲突时，先核对项目文件和脚本，再同步更新说明。

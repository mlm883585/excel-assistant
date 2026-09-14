# 内网 Excel 数据助手

基于 PPX V6、Qwen Code 和 DataCraft 的 Windows 桌面原型。支持多文件合并、关联、清洗、对账、汇总、宽长表/BOM 矩阵转换和简单模板填写。无需模型也可执行常用操作及保存的规则。

## 开发启动

使用 Windows、Python 3.13.5、Node 24.13.0。以下命令仅由开发人员执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt ./vendor/qwen-code-sdk
npm ci
npm ci --prefix gui
npm run build --prefix gui
.\.venv\Scripts\python.exe main.py
```

PPX Python 源码直接从 `vendor/ppx-py/src` 加载；无需额外安装 PPX。原始项目快照仅在本地 docs 中保留，不纳入公开仓库，也不是运行依赖。修改请针对根目录应用和 data_toolkit；提交与清理规则见 [目录清理说明](docs/REPOSITORY_HYGIENE.md)。

## 使用

1. 新建任务并添加文件，确认工作表和表头行，再读取预览。
2. 不接模型时，在常用操作中选择字段执行。关联和对账使用两个输入，模板填写按数据、模板顺序添加。
3. 先在“环境检测”验证并选择 Qwen Code，再配置模型后描述要求；业务问题在界面回答。客户 IT 配置实际接口地址与 model 标识，密钥使用 `EXCEL_ASSISTANT_API_KEY` 环境变量。
4. 检查结果与异常，使用 Excel 打开结果。成功任务可保存规则，下次按同一顺序添加替换文件。

任务数据默认位于 `%LOCALAPPDATA%/ExcelAssistant`，可用 `EXCEL_ASSISTANT_HOME` 更改。导入文件会复制到任务目录；不会覆盖源文件。Agent 配置和会话与用户原有 Qwen Code 配置分开保存。

“环境检测”优先复用通过验证的已有 CLI 0.23.3；未知版本保持不变，可明确选择随包版本。检测支持后台进度、取消、模型及 Excel 测试、脱敏报告和 WebView2 离线安装。已选安装变化后需要重新验证。详见 [环境检测与离线排障](docs/ENVIRONMENT.md)。

## 验证与构建

```powershell
.\.venv\Scripts\python.exe scripts/doctor.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm run build --prefix gui
.\.venv\Scripts\python.exe scripts/build.py
```

默认在本地运行测试与编译，不因推送或 PR 自动消耗 GitHub Actions 配额。`Windows CI` 仅保留手动入口，获得明确授权后才运行；勾选 `build_portable` 可额外构建并验证便携包，该步骤不会自动创建 Release。

对应源码按 Git 跟踪清单归档，与 WebView2 安装介质是否存在无关。解压交付包内的 `corresponding-source.zip` 后，也可通过内置源码清单重新打包。开发构建请使用 Git 克隆或该对应源码包，不依赖本地历史快照。

便携包输出到 `build/ExcelAssistant`。保留整个目录，客户运行 `ExcelAssistant.exe`，无需自行安装 Node/Python。构建脚本使用 PPX 的 PyInstaller 规格生成器并添加应用专用入口和 MCP 进程。开发人员先运行 `scripts/fetch_webview2.ps1` 下载并验证微软离线安装介质，构建时将其附在 `prerequisites/`。缺少 WebView2 时可从原生提示或环境页面启动随包安装程序；权限不足时由 IT 处理。交付前执行 [离线验收](docs/OFFLINE_ACCEPTANCE.md)。

## 当前边界

- Qwen Code 0.23.3 + SDK 已接入；本机仅验证本地模型模拟服务，客户模型效果未验收。
- 任意 Python 执行尚未开放：Windows 操作系统隔离未完成，Agent 当前只能调用注册的 DataCraft 工具。
- 简单模板写入已实现；复杂 Excel 对象和 Excel 2016 实机兼容仍需验收。没有声称 openpyxl 能无损处理所有模板。
- 公式缓存缺失时要求先在 Excel 中重算保存，避免输出错误数据。含宏工作簿暂不支持。
- 规则支持原输入文件槽位替换；引用中间输出的 Agent 多步规则暂拒绝保存。
- 表格预览分页传输，但底层仍读取工作表。十万行已覆盖，性能需以客户终端实测为准。
- 单实例单任务执行；半途失败保留已完成结果和错误记录，重新执行不会覆盖旧输出。

许可证与第三方来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

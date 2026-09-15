# Excel 数据助手

<img src="assets/branding/logo.svg" alt="Excel 数据助手" width="96" height="96">

面向内网业务的 Windows 本机 Excel 工作台。支持表格编辑、公式、格式与历史版本，以及多文件合并、关联、清洗、对账、汇总、计算列、条件分级、无文件建表和简单模板填写。无需模型也可编辑表格、执行常用操作及保存的规则。

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

固定的桌面运行时已随源码提供；技术来源与本地修改见 [第三方说明](THIRD_PARTY_NOTICES.md)。原始项目快照仅在本地 docs 中保留，不纳入公开仓库，也不是运行依赖。修改请针对根目录应用和 data_toolkit；提交与清理规则见 [目录清理说明](docs/REPOSITORY_HYGIENE.md)。

## 使用

1. 新建任务并添加文件，确认工作表和表头行。可以使用分页预览，也可以打开内置编辑器；没有文件时可新建工作簿或填报表。
2. 不接模型时，在常用操作中选择字段执行。关联和对账使用两个输入，模板填写按数据、模板顺序添加。
3. 先在“环境检测”验证并选择 Qwen Code，再配置模型后描述要求；业务问题在界面回答。客户 IT 配置实际接口地址与 model 标识，密钥使用 `EXCEL_ASSISTANT_API_KEY` 环境变量。
4. 在“结果与核对”查看完整差异和异常，整份采用后继续编辑，或确认后另存为 `.xlsx`。已有文件不会覆盖。成功任务可保存规则，下次按同一顺序添加替换文件；建表规则支持零文件输入。

任务数据默认位于 `%LOCALAPPDATA%/ExcelAssistant`，可用 `EXCEL_ASSISTANT_HOME` 更改。导入文件会复制到任务目录；不会覆盖源文件。Agent 配置和会话与用户原有 Qwen Code 配置分开保存。

“环境检测”优先复用通过验证的已有 CLI 0.23.3；未知版本保持不变，可明确选择随包版本。检测支持后台进度、取消、模型及 Excel 测试、脱敏报告和 WebView2 离线安装。已选安装变化后需要重新验证。详见 [环境检测与离线排障](docs/ENVIRONMENT.md)。

## 验证与构建

```powershell
.\.venv\Scripts\python.exe scripts/doctor.py
$env:REQUIRE_QWEN_CLI = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm run build --prefix gui
.\.venv\Scripts\python.exe scripts/build.py
```

默认在本地运行测试与编译，不因推送或 PR 自动消耗 GitHub Actions 配额。`Windows CI` 仅保留手动入口，获得明确授权后才运行；勾选 `build_portable` 可额外构建并验证便携包，该步骤不会自动创建 Release。

对应源码按 Git 跟踪清单归档，与 WebView2 安装介质是否存在无关。解压交付包内的 `corresponding-source.zip` 后，也可通过内置源码清单重新打包。开发构建请使用 Git 克隆或该对应源码包，不依赖本地历史快照。

便携包输出到 `build/ExcelAssistant`。保留整个目录，客户运行 `ExcelAssistant.exe`，无需自行安装 Node/Python。便携包包含应用专用入口与 MCP 进程。开发人员先运行 `scripts/fetch_webview2.ps1` 下载并验证微软离线安装介质，构建时将其附在 `prerequisites/`。缺少 WebView2 时可从原生提示或环境页面启动随包安装程序；权限不足时由 IT 处理。交付前执行 [离线验收](docs/OFFLINE_ACCEPTANCE.md)。

## 当前边界

- Qwen Code 0.23.3 + SDK 已接入；本机仅验证本地模型模拟服务，客户模型效果未验收。
- 任意 Python 执行尚未开放：Windows 操作系统隔离未完成，Agent 当前只能调用注册的 DataCraft 工具。
- 简单模板写入已实现；复杂 Excel 对象和 Excel 2016 实机兼容仍需验收。没有声称 openpyxl 能无损处理所有模板。
- 文件数据处理要求有效公式缓存；内置编辑器可对支持范围内的公式本机重算后保存。错误或缺失结果不会替换成零。含宏工作簿暂不支持。
- 规则支持原输入文件槽位替换；引用中间输出的 Agent 多步规则暂拒绝保存。
- 分页预览使用后台流式索引与本地缓存；完整编辑器上限为 20 万有效单元格。超限仍支持全量数据处理与核对，性能分别记录。
- 单实例单任务执行；半途失败保留已完成结果和错误记录，重新执行不会覆盖旧输出。

许可证与第三方来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

应用使用自有图标。素材维护、桌面接入和打包验证见 [品牌资源说明](docs/BRANDING.md)。

## 使用与验收文档

业务界面已按“文件与处理 / 结果与核对”组织，支持后台分页预览、常用操作、中文结果指标与按需环境设置。请参阅 [工作台使用说明](docs/WORKBENCH.md) 和 [本地性能记录](docs/PERFORMANCE.md)。

已接入按需加载的 Univer 0.25.1 表格编辑器、本地工作簿版本和草稿恢复，以及计算列、条件分级、无文件建表、AI 区域编辑和整份差异核对。兼容范围、20 万有效单元格边界和导出流程见 [内置编辑器使用说明](docs/WORKBOOK_EDITOR.md)。最终整合验证以 [本地验证记录](docs/VALIDATION.md) 为准。

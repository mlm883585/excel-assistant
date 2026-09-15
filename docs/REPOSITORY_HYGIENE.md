# Git 提交与本地目录清理

## 提交范围

提交根目录应用源码、`api/`、`assistant/`、`data_toolkit/`、`gui/src/`、`tests/`、`scripts/`、固定的 `vendor/` 源码、`assets/branding/`、依赖锁文件、许可证和当前项目文档。

`vendor/` 是直接参与构建的 PPX 与 Qwen SDK 固定源码，不是可随意移除的缓存。`assets/branding/` 的图标同样参与打包。锁文件用于重建环境，须提交。

## 忽略与可清理内容

| 内容 | Git 处理 | 本地清理建议 |
| --- | --- | --- |
| 根目录 `task_plan.md`、`findings.md`、`progress.md` | 忽略 | 本地过程笔记；有效结论归入正式文档 |
| `build/` | 忽略 | 可重建；保留当前交付包时不要删除 |
| `runtime/` | 忽略 | 包含 WebView2 离线介质，删除后需要重新下载 |
| `.venv/` | 忽略 | 可重建，删除后不能直接运行 Python 应用 |
| 根目录及 `gui/` 下的 `node_modules/` | 忽略 | 可通过对应目录的 `npm ci` 恢复 |
| `gui/dist/` | 忽略 | 可重新构建，删除后需先构建再启动桌面 |
| `__pycache__/`、`*.pyc`、测试缓存、`*.log` | 忽略 | 可直接清理的生成产物 |
| `docs/office-assistant-main/`、`docs/datacraft-toolkit/` | 忽略 | 历史参考快照，包含旧代码及嵌套仓库；建议归档后再决定删除 |
| `__MACOSX/`、`._*` | 忽略 | 解压附带的 macOS 元数据，可清理 |
| `.env*`、私钥、证书、任务数据库、客户数据目录 | 忽略 | 保留必要本地配置，不能公开；脱敏模板可显式提交 |
| EXE、安装包、压缩包与 wheel | 忽略 | 发布时使用 GitHub Releases 或内部交付渠道 |

本次仅设置忽略规则并记录清理建议，没有删除历史项目、开发环境或交付包。公开仓库不包含本地历史快照，因此文档里提到的快照路径属于来源说明，不是运行依赖。

## 提交前检查

```powershell
git status --short
git diff --cached --stat
git ls-files
git check-ignore build/ExcelAssistant/ExcelAssistant.exe runtime/WebView2StandaloneX64.exe
```

不要使用 `git add -f` 绕过客户数据和凭据的忽略规则。需要版本管理的测试表格应使用合成数据，并放入明确的测试 fixture 目录；本次没有用通配符忽略所有 Excel 文件，避免掩盖必要测试样本。

交付包内的对应源码同样使用 Git 跟踪清单，不会收集未跟踪的本地 JSON 配置、`.env` 或缓存。源码包携带 `source-files.json`，用于无 `.git` 目录时重建；禁止手工把客户文件加入该清单。

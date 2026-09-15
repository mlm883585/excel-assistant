# Excel 数据助手品牌资源

产品使用原创“绿色表格＋助手”图标：主色 `#167864`、白色网格、浅绿色辅助标记。产品名称为“Excel 数据助手”，图标内部不放文字。SVG 母版和派生 PNG、ICO 集中在 `assets/branding/`，应用标识、可执行文件名与数据目录沿用原值。

## 维护与构建

修改 SVG 后执行 `node scripts/render_branding.cjs`。脚本通过本地 Chromium 渲染 1024×1024 透明 PNG，再使用已锁定的 Pillow 生成 16、24、32、48、64、128、256 像素 ICO。通过 `PLAYWRIGHT_MODULE`、`CHROME_EXECUTABLE`、`UI_PYTHON` 可指定已有工具；生成过程无网络请求，无新增应用运行依赖。

前端直接发布 `assets/` 中的资源，用于工作台标识和 favicon。桌面构建将 ICO 嵌入 EXE，并附带同一 ICO 供原生窗口使用；开发运行同样显式指定图标。源码构建使用随仓库提交的成品图标，无需重新生成。

## 上游资源处理

删除应用和随附框架中的 PPX 默认图片、macOS 图标及博客背景；Windows 资源检查只要求 PNG、ICO。随附框架不提供新项目模板，相关命令在创建目录前失败。初始化脚本排除旧图片，并去除上游 README 中的图片与赞助、公众号内容。

保留上游技术包名、源码、作者、来源和许可证。PPX Python 许可证位于便携包的 `licenses/ppx/LICENSE`，JavaScript 许可证继续随前端依赖清单归档。上游修改记录见根目录 `THIRD_PARTY_NOTICES.md`；本项目技术基础仍为 PPX V6、Vue 3、Univer、Qwen Code 和迁入的数据处理核心。

## 验证方式

| 命令 | 覆盖范围 |
| --- | --- |
| `python scripts/verify_branding.py` | 透明边缘、ICO 尺寸、已跟踪源码中的旧图片哈希、宣传内容和前端资源一致性 |
| `python scripts/verify_branding.py --bundle` | 额外检查便携包原生图标、EXE 内嵌全部尺寸图标及 PPX 许可证 |
| `ExcelAssistant.exe --smoke` | 实际 WebView2 页面、本地资源、中文窗口标题、原生窗口与任务栏所用图标 |
| `python scripts/verify_release.py` | 最终前端、对应源码、许可证、全部交付文件哈希及品牌验证 |

`--smoke` 使用 `EXCEL_ASSISTANT_HOME` 指定独立测试目录，输出 `desktop-branding.json`；测试失败返回非零码，正常启动不执行该检查。最新实测结果见 [本地验证记录](VALIDATION.md)。

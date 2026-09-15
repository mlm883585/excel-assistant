# 第三方来源与修改

| 组件 | 固定来源 | 本项目处理 |
| --- | --- | --- |
| PPX | pangao1990/PPX，247da805d531910302fc9505b96aa3218cd952b9，AGPL-3.0-only | 保留 vendor 下 Python/JS 源码与许可证；使用应用自有入口收窄 RPC；Windows 固定 WebView2；新增可选窗口标题与图标参数；移除默认品牌图片和 README 宣传内容，缺失模板时禁止脚手架写入；资源检查按平台执行 |
| Qwen Code | npm @qwen-code/qwen-code 0.23.3，Apache-2.0 | npm 锁文件固定；保留运行包许可证 |
| Qwen Python SDK | 官方提交见 vendor/qwen-code-revision.txt，Apache-2.0 | 源码构建 0.1.0；新增 node_executable 选项，JavaScript 入口使用指定 Node 路径启动；保留其余传输协议 |
| DataCraft | docs/datacraft-toolkit/datacraft-toolkit/src/data_toolkit | 复制业务模块；修复默认 NA 识别和问题行号；发布前确认原项目分发授权 |
| Univer | dream-num/univer，开源 npm 插件固定 0.25.1，Apache-2.0 | 使用 core、render、formula、docs、sheets、UI、数字格式、排序、按值筛选、查找替换；未修改上游源码。无 Pro、协作、商业转换组件；使用应用自有本机格式适配器 |
| React / React DOM | 18.3.1，MIT | Univer 插件界面运行依赖；主界面仍为 Vue |
| RxJS | 7.8.2，Apache-2.0 | Univer 的本地事件与状态依赖 |

本项目按根 LICENSE 的 AGPL-3.0 提供。向客户交付时一并提供对应版本源代码、构建脚本、依赖锁文件、许可证及修改说明；不将客户数据、密钥或内部模型地址纳入源码分发。此文件是交付记录，不替代组织对分发方式的许可证适配核查。

Python 第三方包许可证保留在 wheel/安装元数据中；Node 依赖保留各包许可证。正式发布需对实际交付包完成依赖清单及许可证归档。

2026-09-15：应用图标由本项目原创 SVG 生成，母版和派生文件位于 `assets/branding/`，按根许可证提供。PPX 默认图标、博客背景和 README 宣传图片已移除；必要技术说明、作者归属与许可证保留。桌面运行时新增可选标题和图标参数，打包规格附带相同图标供窗口使用；PPX Python 许可证改归档到交付包 `licenses/ppx/LICENSE`。初始化排除被裁剪图片，前端与 EXE 均使用自有图标。未改名或隐藏运行时的 PPX 技术来源。

编辑器前端依赖的固定版本、来源与许可证正文归档于 `vendor/licenses/gui/`，由 `scripts/archive_gui_licenses.py` 从锁定的已安装运行包生成，随便携包交付。`gui/package-lock.json` 保存完整依赖图及完整性校验。

产品交互参考 Grist（Apache-2.0）的旧值与新值并排核对、OpenRefine（BSD-3-Clause）的步骤与历史说明、Microsoft Data Formulator（MIT）的输入→操作→结果卡片；仅借鉴交互思路，未复制其源码或资产。FortuneSheet 为评估候选，未引入。FormulaAI 仅作为场景展示与确认流程参考。

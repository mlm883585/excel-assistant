# 第三方来源与修改

| 组件 | 固定来源 | 本项目处理 |
| --- | --- | --- |
| PPX | pangao1990/PPX，247da805d531910302fc9505b96aa3218cd952b9，AGPL-3.0-only | 保留 vendor 下 Python/JS 源码与许可证；使用应用自有入口收窄 RPC；Windows 固定 WebView2 |
| Qwen Code | npm @qwen-code/qwen-code 0.23.3，Apache-2.0 | npm 锁文件固定；保留运行包许可证 |
| Qwen Python SDK | 官方提交见 vendor/qwen-code-revision.txt，Apache-2.0 | 源码构建 0.1.0；新增 node_executable 选项，JavaScript 入口使用指定 Node 路径启动；保留其余传输协议 |
| DataCraft | docs/datacraft-toolkit/datacraft-toolkit/src/data_toolkit | 复制业务模块；修复默认 NA 识别和问题行号；发布前确认原项目分发授权 |

本项目按根 LICENSE 的 AGPL-3.0 提供。向客户交付时一并提供对应版本源代码、构建脚本、依赖锁文件、许可证及修改说明；不将客户数据、密钥或内部模型地址纳入源码分发。此文件是交付记录，不替代组织对分发方式的许可证适配核查。

Python 第三方包许可证保留在 wheel/安装元数据中；Node 依赖保留各包许可证。正式发布需对实际交付包完成依赖清单及许可证归档。

# ppx-js

PPX 是一个开源的跨平台桌面应用框架：用 Python 编写业务，用 JavaScript 构建界面，为 Windows、macOS 和 Linux 生成桌面客户端。可以选择 Vanilla JavaScript、Vue 或 React，不需要维护 pywebview 入口、PyInstaller spec 或安装器脚本。

[项目源码](https://github.com/pangao1990/PPX) · [完整教程](https://blog.pangao.vip/docs-ppx/) · [下载安装包](https://github.com/pangao1990/PPX/releases) · [问题反馈](https://github.com/pangao1990/PPX/issues)

PPX 由两个包配合工作：`ppx-py` 提供 Python 运行时、开发命令和三端打包；`ppx-js` 提供前端调用、事件订阅和 TypeScript 声明。旧 V5 项目请查阅 [V5 归档文档](https://blog.pangao.vip/docs-ppx/v5/)，两代接口不能直接混用。

PPX 的轻量 JavaScript RPC 客户端。它只负责 Web 页面与 `ppx-py` 之间的稳定调用和事件边界，不依赖 Vue、Element Plus 或其他 UI 框架。

```bash
pnpm add ppx-js@6.0.0
```

```javascript
import { ppx } from 'ppx-js'

const owner = await ppx.call('system.getOwner')
const stop = ppx.on('changed', (data) => console.log(data))
stop()
```

RPC 默认使用 30 秒总超时，覆盖等待桥接和等待 Python 的完整过程，可用第三个参数调整：

```javascript
await ppx.call('report.create', { id: 1 }, { timeoutMs: 60_000 })
```

本包包含 TypeScript 声明，并可在 SSR/Node 环境中安全导入；实际调用只能发生在 PPX 的 pywebview 页面内。

每次调用在浏览器侧生成 requestId，并传给 Python。调用失败统一抛出 `PpxError`；超时和底层传输失败也会携带 requestId。可根据 `error.code` 处理 `BRIDGE_UNAVAILABLE`、`BRIDGE_ERROR`、`TIMEOUT`、`METHOD_NOT_FOUND`、`INVALID_PARAMS`、`INVALID_RESULT` 和业务侧返回的其他稳定错误码。

完整文档：[PPX JavaScript API](https://blog.pangao.vip/docs-ppx/v6/reference/javascript)

## 开源协议

本项目使用 [AGPL-3.0-only](https://github.com/pangao1990/PPX/blob/main/LICENSE) 协议。

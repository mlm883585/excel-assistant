# UI 组件库选型：Element Plus

## 结论

`gui/` 前端统一使用 **Element Plus 2.x**（当前 `2.14.5`），不迁移到其他库。精力放在补齐图标、整理组件注册、修复隐藏 bug 上；主题 tokens 保持现状。

## 理由

- **长期可维护**：Vue 3 原生生态、社区最大、持续维护，中文 locale 内建（`zhCn`），TypeScript 类型完备。
- **离线交付**：全量 `element-plus/dist/index.css`，无 CDN（`index.html` 有严格 CSP，`vite.config.ts` 无 externals）。
- **零迁移成本**：21 个 `el-*` 标签已是现成使用面，其中 `ElTableV2` / `ElAutoResizer` 虚拟滚动预览栅格在轻量库中无等价替代。
- **已有品牌主题**：`gui/src/style.css:1` 的 `:root` 已覆盖 `--el-color-primary:#167864`（teal 绿）及全套色阶 + 圆角。

## 对比（为何不选）

| 候选 | 结论 | 原因 |
| --- | --- | --- |
| Naive UI | 不选 | 需重写全部 61 处 `el-button` 及组件属性语义，收益不足以覆盖迁移成本 |
| Ant Design Vue | 不选 | 同样重写，且视觉风格偏离现有 teal 品牌 |
| Arco / Vuetify | 不选 | 无差异化优势，迁移成本相当 |

一句话：换库是「重写 9 个 `.vue` 组件、约 1184 行」，不是「美化」。

## 约定（团队后续遵守）

- **主题 tokens**：统一放 `gui/src/style.css` 的 `:root`（主色、色阶、圆角）。
- **图标**：统一用 `@element-plus/icons-vue` + `<el-icon>`，或 `el-button` 的 `:icon` 属性；不用 emoji/unicode 字形占位。
- **locale**：`zhCn`，经 `main.ts` 的 `ElConfigProvider` 注入。
- **组件注册**：统一在 `gui/src/element.ts` 的 `setupElement()`；新增/移除 Element Plus 组件只改这里。
- **暗色模式**：已实现（三态：浅色 / 深色 / 跟随系统，`gui/src/theme.ts` + `html.dark` + 语义 token）；Univer 表格编辑器保持浅色。

## 已知边界

- 图表用 ECharts、表格编辑器用 Univer，均有独立主题，不受本选型影响。
- 维持「全量 CSS + 手动按需注册」的离线稳定路线，不引入 auto-import / tree-shake 插件。

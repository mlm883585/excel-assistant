import type { App } from 'vue'
import {
  ElIcon, ElButton, ElTag, ElAlert, ElSelect, ElOption, ElInput, ElInputNumber,
  ElTabs, ElTabPane, ElTable, ElTableColumn, ElCheckbox, ElRadioGroup, ElRadioButton,
  ElDialog, ElPagination, ElDrawer, ElEmpty, ElSwitch, ElLoading,
} from 'element-plus'

// 组件注册单点：新增/移除 Element Plus 组件只需改这里。
const components = [
  ElIcon, ElButton, ElTag, ElAlert, ElSelect, ElOption, ElInput, ElInputNumber,
  ElTabs, ElTabPane, ElTable, ElTableColumn, ElCheckbox, ElRadioGroup, ElRadioButton,
  ElDialog, ElPagination, ElDrawer, ElEmpty, ElSwitch,
]

export function setupElement(app: App) {
  for (const component of components) app.component(component.name!, component)
  app.use(ElLoading)
}

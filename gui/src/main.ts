import { createApp, h } from 'vue'
import { ElConfigProvider, ElButton, ElTag, ElAlert, ElSelect, ElOption, ElInput, ElInputNumber, ElTabs, ElTabPane, ElTable, ElTableColumn, ElCheckbox, ElRadioGroup, ElRadioButton, ElDialog, ElPagination, ElLoading } from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import './style.css'
const app = createApp({ render: () => h(ElConfigProvider, { locale: zhCn }, () => h(App)) })
for (const component of [ElButton, ElTag, ElAlert, ElSelect, ElOption, ElInput, ElInputNumber, ElTabs, ElTabPane, ElTable, ElTableColumn, ElCheckbox, ElRadioGroup, ElRadioButton, ElDialog, ElPagination]) app.component(component.name!, component)
app.use(ElLoading)
app.mount('#app')

import { createApp, h } from 'vue'
import { ElConfigProvider } from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import App from './App.vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import './style.css'
import { setupElement } from './element'
import { initTheme } from './theme'

initTheme()
const app = createApp({ render: () => h(ElConfigProvider, { locale: zhCn }, () => h(App)) })
setupElement(app)
app.mount('#app')

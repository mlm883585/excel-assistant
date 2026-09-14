<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ppx } from 'ppx-js'
import EnvironmentPanel from './EnvironmentPanel.vue'

type FileInfo = { id: string; name: string; statistics?: Record<string, unknown>; issues?: unknown[] }
type Task = { id: string; status: string; files: FileInfo[]; outputs: FileInfo[]; error?: string }
type Selection = { file_id: string; sheet: string | number; header_row: number }
type Event = { id: number; kind: string; data: any }
const task = ref<Task>(), history = ref<Task[]>([]), events = ref<Event[]>([])
const environmentOpen = ref(false), startupError = ref('')
const runtimeStatus = ref({ready:false, excel_ready:false, first_use:false, message:'运行环境尚未检查'})
async function refreshEnvironment() { runtimeStatus.value = await call('runtime.status') }
const selections = ref<Selection[]>([]), sheets = ref<Record<string, string[]>>({})
const preview = ref<{columns: string[]; rows: Record<string, unknown>[]; total: number}>({columns: [], rows: [], total: 0})
const activeFile = ref(''), page = ref(1), prompt = ref(''), operation = ref('append')
const keys = ref<string[]>([]), columns = ref<string[]>([]), pivotColumn = ref(''), pivotValue = ref('')
const busy = computed(() => ['running', 'waiting'].includes(task.value?.status || ''))
const fields = computed(() => preview.value.columns.filter(c => !c.startsWith('__source_')))
const settingsOpen = ref(false), settings = ref({base_url: '', model: ''}), recipes = ref<any[]>([])
const answers = ref<Record<string,string>>({}), question = ref<any>(null)
const templateSheet = ref(''), templateStart = ref(2), templateMapping = ref<Record<string,string>>({})
const labels: Record<string,string> = {pending:'待执行',running:'处理中',waiting:'等待回答',succeeded:'已完成',failed:'需处理',cancelled:'已取消'}
let timer: ReturnType<typeof setInterval> | undefined, polling = false
async function call<T=any>(method: string, params: unknown = {}): Promise<T> { return ppx.call<T>(method, params, {timeoutMs: 60000}) }
async function action(fn: () => Promise<unknown>) { try { await fn() } catch (e) { ElMessage.error(e instanceof Error ? e.message : String(e)) } }
async function refreshLists() { history.value = await call('tasks.list'); recipes.value = await call('recipes.list') }
async function selectTask(value: Task) {
  task.value = value; events.value = []; question.value = null; selections.value = []; sheets.value = {}; activeFile.value = ''; preview.value = {columns:[],rows:[],total:0}
  for (const file of value.files) {
    const info = await call('files.inspect', {task_id:value.id,file_id:file.id})
    sheets.value[file.id] = info.sheets
    selections.value.push({file_id:file.id,sheet:info.sheets[0] === 'CSV' ? 0 : info.sheets[0],header_row:1})
  }
  if (value.files[0]) activeFile.value = value.files[0].id
  await poll()
}
async function newTask() { await selectTask(await call('tasks.create')); await refreshLists() }
async function addFiles() { await call('files.choose',{task_id:task.value!.id}); const result = await call('tasks.get',{task_id:task.value!.id}); await selectTask(result.task) }
async function loadPreview() {
  const selection = selections.value.find(s => s.file_id === activeFile.value) || {file_id:activeFile.value,sheet:0,header_row:1}
  preview.value = await call('files.preview',{task_id:task.value!.id,selection,offset:(page.value-1)*50,limit:50})
}
async function poll() {
  if (!task.value || polling) return
  polling = true
  const id = task.value.id
  try {
    const result = await call('tasks.get',{task_id:id,after:events.value.at(-1)?.id || 0})
    if (task.value?.id !== id) return
    task.value = result.task; events.value.push(...result.events)
    for (const event of result.events) if (event.kind === 'question') { question.value = event.data; answers.value = {} }
    if (task.value?.status !== 'waiting') question.value = null
  } finally { polling = false }
}
async function run() {
  const params: Record<string,unknown> = {keys:keys.value,columns:columns.value,validate:'many_to_one',how:'left',aggregate:'sum'}
  if (operation.value === 'clean') params.config = {schema_version:1,columns:Object.fromEntries(columns.value.map(c=>[c,{type:'string',trim:true}]))}
  if (operation.value === 'pivot') Object.assign(params,{column:pivotColumn.value,value:pivotValue.value})
  if (operation.value === 'template') Object.assign(params,{sheet:templateSheet.value,start_row:templateStart.value,mapping:templateMapping.value})
  const multiple = ['append','join','compare','template'].includes(operation.value)
  await call('tasks.execute',{task_id:task.value!.id,plan:{steps:[{kind:operation.value,inputs:multiple?selections.value:selections.value.filter(s=>s.file_id===activeFile.value),params}],questions:[]}})
  await poll()
}
async function askAgent() { await call('tasks.agent',{task_id:task.value!.id,prompt:prompt.value,selections:selections.value}); prompt.value=''; await poll() }
async function saveRecipe() { const result = await ElMessageBox.prompt('为这套处理步骤命名','保存常用任务'); await call('recipes.save',{task_id:task.value!.id,name:result.value}); await refreshLists() }
onMounted(async()=> {
  await action(async()=> { await refreshEnvironment(); environmentOpen.value=runtimeStatus.value.first_use })
  await action(async()=> { settings.value=await call('settings.get') })
  try { await refreshLists(); if(history.value[0]) await selectTask(history.value[0]); else await newTask(); timer=setInterval(()=>action(poll),1200) }
  catch(e) { startupError.value=String(e); environmentOpen.value=true }
})
onUnmounted(()=>clearInterval(timer))
</script>

<template>
  <div class="shell">
    <aside><div class="brand"><span class="mark">▦</span> Excel 数据助手</div><p class="muted">内网工作台 · 文件在本机处理</p>
      <el-button type="primary" class="wide" @click="action(newTask)">＋ 新建任务</el-button>
      <h4>最近任务</h4><button v-for="item in history" :key="item.id" class="history" :class="{selected:task?.id===item.id}" @click="action(()=>selectTask(item))">{{item.files[0]?.name || '新任务'}}<small>{{labels[item.status]}}</small></button>
      <h4>常用任务</h4><button v-for="recipe in recipes" :key="recipe.id" class="history" :disabled="busy" @click="action(()=>call('recipes.apply',{task_id:task!.id,recipe_id:recipe.id}))">{{recipe.name}}<small>按原顺序导入 {{recipe.slots.length}} 个替换文件</small></button>
      <el-button class="settings" @click="settingsOpen=true">模型连接设置</el-button>
      <el-button @click="environmentOpen=true">环境检测</el-button>
    </aside>
    <main v-if="task"><header><div><div class="eyebrow">从数据到可交付的结果</div><h1>今天，需要整理什么数据？</h1></div><el-tag>{{labels[task.status]}}</el-tag></header>
      <el-alert v-if="!runtimeStatus.ready" :title="runtimeStatus.message" type="info" :closable="false"><el-button link @click="environmentOpen=true">打开环境检测</el-button>常用操作无需连接模型。</el-alert>
      <section class="panel"><div class="section-title"><h3>1 · 选择文件与表头</h3><el-button :disabled="busy" @click="action(addFiles)">添加 Excel / CSV</el-button></div>
        <div v-if="!task.files.length" class="empty">添加 ERP 导出表、库存表、订单表或输出模板，开始一个任务。</div>
        <div v-for="(file,index) in task.files" :key="file.id" class="file-row"><el-radio v-model="activeFile" :value="file.id">{{index+1}}. {{file.name}}</el-radio><template v-if="selections[index]"><el-select v-model="selections[index].sheet" :disabled="busy" style="width:160px"><el-option v-for="s in sheets[file.id]" :key="s" :label="s" :value="s==='CSV'?0:s"/></el-select><span>表头行</span><el-input-number v-model="selections[index].header_row" :min="1" :max="1048576" :disabled="busy" size="small"/></template></div>
        <el-button v-if="activeFile" @click="action(async()=>{page=1;await loadPreview()})">读取预览</el-button>
        <el-table v-if="preview.columns.length" :data="preview.rows" height="260" stripe><el-table-column v-for="col in preview.columns" :key="col" :prop="col" :label="col" min-width="140" show-overflow-tooltip/></el-table>
        <el-pagination v-if="preview.total" v-model:current-page="page" :page-size="50" :total="preview.total" layout="total, prev, pager, next" @current-change="()=>action(loadPreview)"/>
      </section>
      <div class="workspace"><section class="panel"><h3>2 · 描述要求</h3><p class="muted">例如：将库存按物料汇总，再关联订单，列出没有匹配的记录。</p>
        <div class="conversation"><div v-for="event in events.filter(e=>['message','user','progress','error'].includes(e.kind))" :key="event.id" class="message" :class="event.kind">{{event.data}}</div><div v-if="!events.length" class="empty">也可以使用右侧常用操作，不需要连接模型。</div></div>
        <div v-if="question"><div v-for="(q,index) in question.questions" :key="index"><p>{{q.question || q.title}}</p><el-input v-model="answers[String(index)]" placeholder="填写业务规则或选择的选项"/><p class="muted">{{q.options?.map((o:any)=>o.label || o).join(' / ')}}</p></div><el-button @click="action(()=>call('tasks.answer',{task_id:task!.id,answers}))">提交回答</el-button></div>
        <el-input v-model="prompt" type="textarea" :rows="3" placeholder="用业务语言说明你想得到的结果" :disabled="busy"/>
        <div class="actions"><el-button type="primary" :disabled="busy || !runtimeStatus.ready || !task.files.length || !prompt.trim()" @click="action(askAgent)">开始处理 / 继续对话</el-button><el-button v-if="busy" @click="action(()=>call('tasks.cancel',{task_id:task!.id}))">取消任务</el-button></div>
      </section><section class="panel tools"><h3>常用操作</h3><el-select v-model="operation"><el-option v-for="(label,value) in {append:'合并文件',join:'按字段关联',clean:'清理文本空格',compare:'对账差异',group:'分组求和',melt:'宽表转长表',pivot:'长表转矩阵 / BOM',template:'填写模板',recalculate:'Excel 原生重算副本'}" :key="value" :label="label" :value="value"/></el-select>
        <p>关键字段 / 分组字段</p><el-select v-model="keys" multiple placeholder="先读取文件预览"><el-option v-for="col in fields" :key="col" :value="col"/></el-select>
        <p>处理字段 / 数值字段</p><el-select v-model="columns" multiple><el-option v-for="col in fields" :key="col" :value="col"/></el-select>
        <template v-if="operation==='pivot'"><p>转为列名的字段</p><el-select v-model="pivotColumn"><el-option v-for="col in fields" :key="col" :value="col"/></el-select><p>数量字段</p><el-select v-model="pivotValue"><el-option v-for="col in fields" :key="col" :value="col"/></el-select></template>
        <template v-if="operation==='template'"><p>第二个文件为模板；目标工作表</p><el-input v-model="templateSheet"/><p>开始行</p><el-input-number v-model="templateStart" :min="1"/><div v-for="col in columns" :key="col"><p>{{col}} 写入列（如 A）</p><el-input v-model="templateMapping[col]"/></div></template>
        <p class="muted">关联使用左连接，右表关键字段须唯一；单表操作使用当前选中文件。模板按导入顺序选取数据、模板。</p><el-button type="primary" :disabled="busy || !task.files.length || (operation==='recalculate' && !runtimeStatus.excel_ready)" @click="action(run)">按以上规则执行</el-button>
      </section></div>
      <section class="panel"><div class="section-title"><h3>3 · 结果与检查</h3><el-button :disabled="task.status!=='succeeded'" @click="action(saveRecipe)">保存为常用任务</el-button></div><el-alert v-if="task.error" :title="task.error" type="error" :closable="false"/>
        <div v-for="file in task.outputs" :key="file.id" class="output"><strong>{{file.name}}</strong><pre>{{JSON.stringify(file.statistics,null,2)}}</pre><el-button @click="action(()=>call('files.open',{task_id:task!.id,file_id:file.id}))">用 Excel 打开</el-button><el-button @click="action(async()=>{activeFile=file.id;page=1;await loadPreview()})">预览结果</el-button><details v-if="file.issues?.length"><summary>检查事项</summary><pre>{{JSON.stringify(file.issues,null,2)}}</pre></details></div><p v-if="!task.outputs.length" class="muted">执行后将在这里展示结果。源文件保持不变。</p>
      </section>
    </main>
    <main v-else><h1>工作环境需要检查</h1><el-alert :title="startupError || '正在加载工作台'" type="warning" :closable="false"/><el-button @click="environmentOpen=true">打开环境检测</el-button><p>修复依赖或数据目录后，请重新打开软件。</p></main>
    <EnvironmentPanel v-model="environmentOpen" :busy="busy" @updated="action(refreshEnvironment)" />
    <el-dialog v-model="settingsOpen" title="内网模型连接" width="520"><p>模型服务地址</p><el-input v-model="settings.base_url" placeholder="由客户 IT 提供的接口地址"/><p>实际 model 标识</p><el-input v-model="settings.model"/><p class="muted">认证密钥由部署人员通过 EXCEL_ASSISTANT_API_KEY 环境变量配置。模型未连接时仍可使用常用操作。</p><template #footer><el-button type="primary" @click="action(async()=>{await call('settings.save',{base_url:settings.base_url,model:settings.model});settingsOpen=false})">保存设置</el-button></template></el-dialog>
  </div>
</template>

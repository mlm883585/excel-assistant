<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import FilePreview from './FilePreview.vue'
import ResultPanel from './ResultPanel.vue'
import RuleFields from './RuleFields.vue'
import { call, statusLabels, type Task, type Selection } from './rpc'
import { useTaskSession } from './composables/useTaskSession'
import { useWorkbookSession } from './composables/useWorkbookSession'
import type { WorkbookContext, WorkbookSelection } from './workbook/types'
const EnvironmentPanel = defineAsyncComponent(() => import('./EnvironmentPanel.vue'))
const WorkbookEditor = defineAsyncComponent(() => import('./WorkbookEditor.vue'))
const ruleFields = ref<{ params: () => Record<string, unknown> }>()
const submitting = ref(false)
const environmentOpen = ref(false), environmentLoaded = ref(false), startupError = ref('')
const runtime = ref({ ready: false, excel_ready: false, first_use: false, message: '' })
const mode = ref('tools'), prompt = ref('')
const activeFile = ref(''), fields = ref<string[]>([]), selections = ref<Record<string, Selection>>({})
const operation = ref('append'), keys = ref<string[]>([]), columns = ref<string[]>([])
const left = ref(''), right = ref(''), pivotColumn = ref(''), pivotValue = ref(''), templateSheet = ref(''), templateStart = ref(2), mapping = ref<Record<string,string>>({})
const session = useTaskSession({
  beforeSelect: () => workbook.flush(),
  reset: () => {
    workbook.reset()
    fields.value = []; selections.value = {}; prompt.value = ''
    keys.value = []; columns.value = []; mapping.value = {}
  },
  selected: async record => {
    activeFile.value = record.files[0]?.id || ''
    left.value = activeFile.value
    right.value = record.files[1]?.id || ''
    await workbook.refreshBooks()
  },
  questioned: () => { mode.value = 'agent'; view.value = 'work' },
  finished: record => { if (record.outputs.length) view.value = 'result' },
  report: error => ElMessage.error(String(error)),
})
const {
  task, history, moreTasks, recipes, historyOffset, events, moreEvents, cursor,
  viewingOlder, loading, question, answers, refreshLists, selectTask, poll, older, latest,
} = session
const workbook = useWorkbookSession({ task, capture: session.capture, opened: () => { operation.value = 'calculate' } })
const {
  editor, workbookId, editorKey, books, workbookContext, inputScope, autoExport,
  workbookRevision, view, changeView, openBook, bookInput, refreshBooks,
} = workbook
const busy = computed(() => session.busy.value || submitting.value)
const file = computed(() => task.value?.files.find(f => f.id === activeFile.value))
const selectedInput = (id: string): Selection => selections.value[id] || { file_id: id, sheet: 0, header_row: 1 }
const operations: Record<string, string> = { calculate: '新增计算列', classify: '条件分级', create_table: '无文件建表', append: '合并文件', join: '按字段关联', clean: '清理文本空格', compare: '对账差异', group: '分组求和', melt: '宽表转长表', pivot: '长表转矩阵 / BOM', template: '填写模板', recalculate: 'Excel 重算副本' }
const newRule = computed(() => ['calculate','classify','create_table'].includes(operation.value))
const usesKeys = computed(() => ['join','compare','group','melt','pivot'].includes(operation.value))
const usesColumns = computed(() => ['clean','compare','group','melt','template'].includes(operation.value))
const twoFiles = computed(() => ['join','compare','template'].includes(operation.value))
const displayedEvents = computed(() => events.value.filter(e => ['message','user','progress','error'].includes(e.kind)))
async function action(fn: () => Promise<unknown>) { try { await fn() } catch (e) { if (e !== 'cancel' && e !== 'close') ElMessage.error(String(e)) } }
function openEnvironment() { environmentLoaded.value = true; environmentOpen.value = true }
async function refreshEnvironment() { runtime.value = await call('runtime.status') }
async function openReviewed(id: string, exportNow = false, outputId?: string) { await openBook(id,undefined,undefined,exportNow?outputId:undefined) }
function editorContext(value: WorkbookContext) {
  workbookContext.value = value
  fields.value = editor.value?.fields(inputScope.value==='range') || []
}
async function newTask() {
  const current = session.capture()
  await workbook.flush()
  if (!current()) return
  const value = await call<Task>('tasks.create')
  if (!current()) return
  await selectTask(value.id)
  await refreshLists()
}
async function addFiles() {
  const id = task.value!.id, current = session.capture()
  await call('files.choose', { task_id: id })
  if (!current()) return
  const record = await call<{ task: Task }>('tasks.get', { task_id: id, after: cursor.value })
  if (!current()) return
  task.value = record.task
  activeFile.value ||= record.task.files[0]?.id || ''
  left.value ||= activeFile.value
  right.value ||= record.task.files[1]?.id || ''
  await refreshLists()
}
async function submitTask(method: string, params: Record<string, unknown>) {
  const id = task.value!.id, current = session.capture()
  submitting.value = true
  try {
    await call(method, { task_id: id, ...params })
    if (current()) await poll()
  } finally { submitting.value = false }
}
async function applyRecipe(id: string) {
  const current = session.capture()
  await workbook.flush()
  if (current()) await submitTask('recipes.apply', { recipe_id: id })
}
function resetOperation() { if (twoFiles.value && left.value) activeFile.value = left.value; keys.value = []; columns.value = []; pivotColumn.value = ''; pivotValue.value = ''; mapping.value = {} }
async function execute() {
  const current = session.capture()
  await workbook.flush()
  if (!current()) return
  if (!task.value?.files.length && operation.value!=='create_table' && view.value!=='editor') throw new Error('请先添加文件或新建工作簿')
  let inputs: (Selection | WorkbookSelection)[] = operation.value==='create_table' ? [] : view.value==='editor' && !twoFiles.value ? [bookInput()] : operation.value === 'append' ? task.value!.files.map(f => selectedInput(f.id)) : [selectedInput(activeFile.value)]
  if (twoFiles.value) { if (!left.value || !right.value || left.value === right.value) throw new Error('请选择两个不同的文件'); inputs = [selectedInput(left.value), selectedInput(right.value)] }
  if (usesKeys.value && !keys.value.length) throw new Error('请选择用于关联或分组的字段')
  if (usesColumns.value && operation.value !== 'compare' && !columns.value.length) throw new Error('请选择要处理的字段')
  const params: Record<string, unknown> = { keys: keys.value, columns: columns.value, validate: 'many_to_one', how: 'left', aggregate: 'sum' }
  if (newRule.value) { Object.keys(params).forEach(k=>delete params[k]); Object.assign(params, ruleFields.value!.params()) }
  if (operation.value === 'clean') params.config = { schema_version: 1, columns: Object.fromEntries(columns.value.map(c => [c, { type: 'string', trim: true }])) }
  if (operation.value === 'pivot') { if (!pivotColumn.value || !pivotValue.value) throw new Error('请选择列名字段与数量字段'); Object.assign(params, { column: pivotColumn.value, value: pivotValue.value }) }
  if (operation.value === 'template') {
    if (columns.value.some(c => !/^[A-Za-z]{1,3}$/.test(mapping.value[c] || ''))) throw new Error('请为每个字段填写有效 Excel 列名，如 A')
    Object.assign(params, { sheet: templateSheet.value, start_row: templateStart.value, mapping: Object.fromEntries(columns.value.map(c => [c, mapping.value[c].toUpperCase()])) })
  }
  await submitTask('tasks.execute', { plan: { steps: [{ kind: operation.value, inputs, params }], questions: [] } })
}
async function ask() {
  const current = session.capture()
  await workbook.flush()
  if (!current()) return
  const selections = view.value==='editor' ? [bookInput()] : task.value!.files.map(f => selectedInput(f.id))
  const scope = view.value==='editor' ? `\n当前工作表：${workbookContext.value!.sheet_name}；选中区域 ${workbookContext.value!.address}（${JSON.stringify(workbookContext.value!.range)}）。数据输入范围：${inputScope.value==='sheet'?'工作表全部实际数据':'上述选区'}。编辑指定区域时必须核对用户范围。` : ''
  await submitTask('tasks.agent', { prompt: prompt.value + scope, selections, editing_selection:view.value==='editor'?bookInput(true):undefined }); if (current()) prompt.value = ''
}
async function saveRecipe() {
  const taskId = task.value!.id, current = session.capture()
  const result = await ElMessageBox.prompt('给这套处理步骤起一个名称', '保存常用任务')
  if (!current()) return
  await call('recipes.save', { task_id: taskId, name: result.value })
  await refreshLists()
}
function message(data: unknown): string { return typeof data === 'string' ? data : data && typeof data === 'object' ? String((data as any).message || (data as any).text || '处理状态已更新') : String(data ?? '') }
onMounted(async () => {
  void action(refreshEnvironment)
  try { await refreshLists(); if (history.value[0]) await selectTask(history.value[0].id); else await newTask() }
  catch (e) { startupError.value = String(e); loading.value = false }
})
</script>

<template>
  <div class="shell">
    <aside class="sidebar"><div class="brand"><span class="mark">▦</span><div>Excel 数据助手<small>内网业务工作台</small></div></div><el-button type="primary" class="wide" :disabled="busy" @click="action(newTask)">＋ 新建任务</el-button>
      <nav class="task-navigation" aria-label="任务导航"><h3>最近任务</h3><button v-for="item in history" :key="item.id" class="history" :class="{selected:task?.id===item.id}" :disabled="busy && task?.id!==item.id" @click="action(()=>selectTask(item.id))"><span>{{item.name}}</span><small>{{statusLabels[item.status]}}</small></button><el-button v-if="historyOffset" text @click="action(()=>refreshLists())">返回最近任务</el-button><el-button v-if="moreTasks" text @click="action(()=>refreshLists(true))">加载更多任务</el-button>
      <template v-if="view==='editor' && task?.files.length"><h3>任务文件</h3><button v-for="f in task.files" :key="f.id" class="history" :disabled="busy" @click="action(()=>openBook(undefined,f.id))"><span>▦ {{f.name}}</span><small>打开副本编辑</small></button></template><h3>常用任务</h3><p v-if="!recipes.length" class="muted">完成一次处理后，可将步骤保存到这里。</p><button v-for="recipe in recipes" :key="recipe.id" class="history" :disabled="busy || !task" @click="action(()=>applyRecipe(recipe.id))"><span>{{recipe.name}}</span><small>按保存顺序准备 {{recipe.slots.length}} 份文件</small></button></nav>
      <button class="settings-link" @click="openEnvironment">⚙ 设置与环境 <span class="status-dot" :class="{ready:runtime.ready}" /></button><p class="local-note">文件在本机处理</p>
    </aside>
    <main class="main-content">
      <header class="task-header"><div><p class="eyebrow">EXCEL 工作台</p><h1>{{task?.files[0]?.name || '开始整理你的业务数据'}}</h1><p class="muted">{{busy ? '正在处理，请留意进度或待确认的问题' : task?.outputs.length ? '结果已保留，可以核对或继续处理' : '添加文件，选择处理方式，再核对结果'}}</p></div><el-tag v-if="task" :type="task.status==='failed'?'danger':busy?'warning':'success'">{{statusLabels[task.status]}}</el-tag></header>
      <el-alert v-if="!runtime.ready" class="environment-hint" title="常用操作可直接使用；智能处理需要配置运行环境与模型。" type="info" :closable="true"><el-button link @click="openEnvironment">配置智能处理</el-button></el-alert>
      <div v-if="startupError" class="panel"><el-alert :title="startupError" type="warning" :closable="false"/><el-button @click="openEnvironment">打开环境检测</el-button></div>
      <div v-else-if="loading" class="panel empty">正在加载工作台…</div>
      <template v-else-if="task">
        <div class="workspace-tabs" role="tablist" aria-label="任务视图"><button role="tab" :aria-selected="view==='work'" :class="{active:view==='work'}" @click="action(()=>changeView('work'))">① 文件与处理</button><button v-if="workbookId" role="tab" :aria-selected="view==='editor'" :class="{active:view==='editor'}" @click="action(()=>changeView('editor'))">表格编辑器</button><button role="tab" :aria-selected="view==='result'" :class="{active:view==='result'}" @click="action(()=>changeView('result'))">② 结果与核对 <span v-if="task.outputs.length">{{task.outputs.length}}</span></button><el-button :disabled="busy" @click="action(()=>openBook())">＋ 空白工作簿</el-button></div>
        <div v-if="books.length" class="workbook-chips"><span>任务工作簿</span><button v-for="b in books" :key="b.id" :class="{active:workbookId===b.id && view==='editor'}" :disabled="busy" @click="action(()=>openBook(b.id))">{{b.name}} · v{{b.revision}}</button></div>
        <div v-if="view!=='result'" class="work-layout" :class="{'editor-layout':view==='editor'}">
          <WorkbookEditor v-if="view==='editor' && workbookId" :key="`${task.id}-${workbookId}-${editorKey}`" ref="editor" :task-id="task.id" :workbook-id="workbookId" :revision="workbookRevision" :busy="busy" :auto-export="autoExport" @context="editorContext" @export-handled="autoExport=undefined" @view-version="(id:string,revision:number)=>action(()=>openBook(id,undefined,revision))" @extracted="(id:string)=>action(()=>openBook(id))" @saved="action(refreshBooks)"/>
          <section v-else class="panel files-panel"><div class="section-title"><div><h2>输入文件 <small>{{task.files.length}} / 10</small></h2><p class="muted">支持 Excel 与 CSV，保留原文件副本</p></div><el-button :disabled="busy" @click="action(addFiles)">＋ 添加文件</el-button></div>
            <div v-if="!task.files.length" class="empty file-empty"><span class="empty-icon">▦</span><strong>从一份业务表格开始</strong><p>库存、订单、ERP 导出表或输出模板</p><el-button type="primary" @click="action(addFiles)">选择 Excel / CSV</el-button></div>
            <template v-else><div class="file-chips"><button v-for="f in task.files" :key="f.id" :class="{active:activeFile===f.id}" :disabled="busy" @click="activeFile=f.id">▦ {{f.name}}</button></div><el-button :disabled="busy" @click="action(()=>openBook(undefined,activeFile))">在表格编辑器中打开</el-button><p class="muted">超出 20 万有效单元格时继续使用下方分页预览与全量处理。</p><FilePreview :task-id="task.id" :file="file" :busy="busy" :initial="selections[activeFile]" @selection="s=>selections[s.file_id]=s" @columns="v=>fields=v" /></template>
          </section>
          <section class="panel processing-panel"><h2>处理方式</h2><div v-if="view==='editor' && workbookContext" class="input-context"><strong>{{workbookContext.sheet_name}}</strong><p>当前选区 {{workbookContext.address}} · 版本 {{workbookContext.version}}</p><el-radio-group v-model="inputScope" :disabled="busy" @change="editorContext(workbookContext)"><el-radio-button value="sheet">整张表数据</el-radio-button><el-radio-button value="range">选区数据</el-radio-button></el-radio-group><p class="muted">数据输入首行为表头；编辑要求将显示选区并生成待核对候选。</p></div><el-tabs v-model="mode"><el-tab-pane label="常用操作" name="tools"/><el-tab-pane label="用文字描述" name="agent"/></el-tabs>
            <template v-if="mode==='tools'"><label class="field-label">想做什么？</label><el-select v-model="operation" aria-label="常用操作" :disabled="busy" @change="resetOperation"><el-option v-for="(label,key) in operations" :key="key" :value="key" :label="label"/></el-select>
              <template v-if="twoFiles"><label class="field-label">{{operation==='template'?'数据文件':'主表 / 左表'}}</label><el-select v-model="left" aria-label="主表或数据文件" :disabled="busy" @change="activeFile=left"><el-option v-for="f in task.files" :key="f.id" :value="f.id" :label="f.name"/></el-select><label class="field-label">{{operation==='template'?'模板文件':'补充表 / 右表'}}</label><el-select v-model="right" aria-label="补充表或模板文件" :disabled="busy"><el-option v-for="f in task.files" :key="f.id" :value="f.id" :label="f.name"/></el-select></template>
              <RuleFields v-if="newRule" :key="operation" ref="ruleFields" :kind="operation" :fields="fields.filter(c=>!c.startsWith('__source_'))" :busy="busy"/>
              <p v-if="!newRule" class="operation-note">{{view==='editor' && !twoFiles?'使用当前工作簿所选输入范围。':operation==='append'?'合并全部已导入文件；可分别点击文件调整工作表与表头。':operation==='join'?'保留主表全部记录，按同名字段匹配；补充表的关联字段必须唯一。':operation==='template'?'明确选择数据与模板，写入模板副本。':twoFiles?'按同名关键字段对比两份表格。':'使用当前选中的文件与工作表。'}}</p>
              <template v-if="usesKeys"><label class="field-label">{{['join','compare'].includes(operation)?'关联依据（同名字段）':'分组 / 保留字段'}}</label><el-select v-model="keys" multiple aria-label="关键字段" :disabled="busy" placeholder="从预览字段中选择"><el-option v-for="c in fields" :key="c" :value="c"/></el-select></template>
              <template v-if="usesColumns"><label class="field-label">{{operation==='group'?'求和字段':operation==='compare'?'对比字段（留空比较共同字段）':'处理字段'}}</label><el-select v-model="columns" multiple aria-label="处理字段" :disabled="busy"><el-option v-for="c in fields" :key="c" :value="c"/></el-select></template>
              <template v-if="operation==='pivot'"><label class="field-label">转成列名的字段</label><el-select v-model="pivotColumn" aria-label="列名字段" :disabled="busy"><el-option v-for="c in fields" :key="c" :value="c"/></el-select><label class="field-label">数量字段（重复项求和）</label><el-select v-model="pivotValue" aria-label="数量字段" :disabled="busy"><el-option v-for="c in fields" :key="c" :value="c"/></el-select></template>
              <template v-if="operation==='template'"><label class="field-label">模板目标工作表（留空使用首表）</label><el-input v-model="templateSheet" aria-label="模板工作表" :disabled="busy"/><label class="field-label">开始写入行</label><el-input-number v-model="templateStart" :min="1" :disabled="busy"/><div v-for="c in columns" :key="c"><label class="field-label">{{c}} → Excel 列名</label><el-input v-model="mapping[c]" :aria-label="`${c}目标列`" placeholder="如 A" :disabled="busy"/></div></template>
              <el-button type="primary" class="wide execute" :disabled="busy || (view==='editor' && workbookContext?.readonly) || (!task.files.length && operation!=='create_table' && view!=='editor') || (operation==='recalculate' && (!runtime.excel_ready || view==='editor'))" @click="action(execute)">{{task.status==='failed'?'按修改后的规则重试':'开始处理'}}</el-button><p v-if="operation==='recalculate' && !runtime.excel_ready" class="muted">Excel 原生重算不可用，请在设置中检测。</p>
            </template>
            <template v-else><p class="muted">例如：按物料汇总库存，再关联订单，列出未匹配记录。</p><el-alert v-if="!runtime.ready" title="请先在设置中配置智能处理；常用操作仍可使用。" type="info" :closable="false"/><div class="conversation"><div class="section-title"><el-button v-if="moreEvents" text @click="action(older)">更早的消息</el-button><el-button v-if="viewingOlder" text @click="action(latest)">返回最新消息</el-button></div><div v-for="event in displayedEvents" :key="event.id" class="message" :class="event.kind">{{message(event.data)}}</div></div>
              <div v-if="question" class="question-box"><h3>需要你确认</h3><div v-for="(q,index) in question.questions" :key="index"><label class="field-label">{{q.question || q.title || q}}</label><el-select v-if="q.options?.length" v-model="answers[String(index)]" allow-create filterable default-first-option :aria-label="q.question || q.title"><el-option v-for="(o,i) in q.options" :key="i" :label="o.label || o" :value="o.value || o.label || o"/></el-select><el-input v-else v-model="answers[String(index)]" :aria-label="q.question || q.title || '业务规则'"/></div><el-button type="primary" class="execute" @click="action(()=>submitTask('tasks.answer',{answers}))">提交确认</el-button></div>
              <div class="scenario-chips"><button :disabled="busy" @click="prompt='新建一张采购填报表，表头为编号、物料、数量、单价、备注，留出20行空白。'">新建填报表</button><button :disabled="busy" @click="prompt='新增金额列，按数量乘以单价计算，保留两位小数。'">计算金额</button><button :disabled="busy" @click="prompt='把当前选区的表头设为粗体、蓝色背景，其他内容保持原样。'">设置表头格式</button></div><el-input v-model="prompt" type="textarea" :rows="4" aria-label="处理要求" placeholder="描述你想得到的结果…" :disabled="busy"/><el-button type="primary" class="wide execute" :disabled="busy || (view==='editor' && workbookContext?.readonly) || !runtime.ready || !prompt.trim()" @click="action(ask)">发送处理要求</el-button>
            </template>
            <div v-if="busy" class="running-box" role="status"><strong>{{statusLabels[task.status]}}</strong><p>{{message([...events].reverse().find(e=>e.kind==='progress')?.data) || '任务已提交，请稍候'}}</p><el-button @click="action(()=>submitTask('tasks.cancel',{}))">取消任务</el-button></div><el-alert v-if="task.error" :title="task.error" type="error" :closable="false"/>
          </section>
        </div>
        <ResultPanel v-else :key="task.id" :task="task" :busy="busy" @open-workbook="(id,exportNow,outputId)=>action(()=>openReviewed(id,exportNow,outputId))"><el-button :disabled="task.status!=='succeeded'" @click="action(saveRecipe)">保存为常用任务</el-button></ResultPanel>
      </template>
    </main>
    <EnvironmentPanel v-if="environmentLoaded" v-model="environmentOpen" :busy="busy" @updated="action(refreshEnvironment)" />
  </div>
</template>

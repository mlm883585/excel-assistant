<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { ElAutoResizer, ElTableV2 } from 'element-plus'
import { call, type FileInfo, type Selection } from './rpc'

const props = defineProps<{ taskId: string; file?: FileInfo; busy: boolean; initial?: Selection }>()
const emit = defineEmits<{ selection: [value: Selection]; columns: [value: string[]] }>()
const sheet = ref<string | number>(0), header = ref(1), sheets = ref<string[]>([])
const page = ref(1), token = ref(''), rows = ref<Record<string, unknown>[]>([]), names = ref<string[]>([])
const total = ref<number | null>(null), indexed = ref(0), state = ref(''), error = ref('')
let generation = 0, timer: ReturnType<typeof setTimeout> | undefined
const sourceLabels: Record<string, string> = { __source_file: '来源文件', __source_sheet: '来源工作表', __source_row: '原始行号' }
const scrollLeft = ref(0)
function columnsFor(width: number) {
  const start = Math.max(0, Math.floor(scrollLeft.value / 160) - 2)
  const end = Math.min(names.value.length, start + Math.ceil(width / 160) + 5)
  const columns: any[] = names.value.slice(start, end).map(name => ({ key: name, dataKey: name, title: sourceLabels[name] || name, width: 160 }))
  const spacer = (key: string, size: number) => ({ key, width: size, title: '', cellRenderer: () => null, headerCellRenderer: () => null })
  if (start) columns.unshift(spacer('_left', start * 160))
  if (end < names.value.length) columns.push(spacer('_right', (names.value.length - end) * 160))
  return columns
}
async function readPage(g: number) {
  const requestedPage = page.value
  try {
    const value = await call('files.preview_page', { preview_id: token.value, offset: (requestedPage - 1) * 50, limit: 50 })
    if (g !== generation || requestedPage !== page.value) return
    state.value = value.state
    if (value.message) error.value = value.message
    if (value.columns?.length) {
      names.value = value.columns; rows.value = value.rows; total.value = value.total; indexed.value = value.indexed_rows
      emit('columns', names.value.filter(name => !name.startsWith('__source_')))
    }
    if (state.value === 'indexing') timer = setTimeout(() => readPage(g), 500)
  } catch (e) { if (g === generation) error.value = String(e) }
}
async function start() {
  const g = ++generation
  clearTimeout(timer); rows.value = []; names.value = []; total.value = null; indexed.value = 0; page.value = 1; error.value = ''; token.value = ''
  scrollLeft.value = 0
  emit('columns', [])
  if (!props.file || props.busy) { state.value = props.busy ? 'busy' : ''; return }
  const selection = { file_id: props.file.id, sheet: sheet.value, header_row: header.value }
  emit('selection', selection); state.value = 'indexing'
  try {
    const result = await call('files.preview_start', { task_id: props.taskId, selection })
    if (g !== generation) return
    if (result.state === 'busy') { timer = setTimeout(() => { if (g === generation) void start() }, result.retry_after_ms); return }
    token.value = result.preview_id; await readPage(g)
  } catch (e) { if (g === generation) { error.value = String(e); state.value = 'failed' } }
}
async function inspect() {
  const g = ++generation
  clearTimeout(timer); rows.value = []; names.value = []; sheets.value = []; error.value = ''; emit('columns', [])
  if (!props.file) return
  try {
    const info = await call('files.inspect', { task_id: props.taskId, file_id: props.file.id })
    if (g !== generation) return
    sheets.value = info.sheets
    sheet.value = props.initial?.sheet ?? (info.sheets[0] === 'CSV' ? 0 : info.sheets[0])
    header.value = props.initial?.header_row ?? 1
    await start()
  } catch (e) { if (g === generation) error.value = String(e) }
}
function turn(delta: number) { page.value += delta; clearTimeout(timer); void readPage(++generation) }
watch(() => [props.taskId, props.file?.id], inspect, { immediate: true })
watch(() => props.busy, () => start())
onBeforeUnmount(() => { ++generation; clearTimeout(timer); if (token.value) void call('files.preview_cancel', { preview_id: token.value }).catch(() => {}) })
</script>

<template>
  <div class="preview">
    <div v-if="file" class="preview-toolbar">
      <label>工作表 <el-select v-model="sheet" aria-label="预览工作表" :disabled="busy" @change="start"><el-option v-for="s in sheets" :key="s" :label="s" :value="s==='CSV'?0:s" /></el-select></label>
      <label>表头行 <el-input-number v-model="header" aria-label="表头行" :min="1" :max="1048576" :disabled="busy" @change="start" /></label>
      <el-button text :disabled="busy" @click="start">重新加载</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" />
    <div v-if="names.length" class="data-grid"><el-auto-resizer><template #default="{ height, width }"><el-table-v2 :columns="columnsFor(width)" :data="rows" :width="width" :height="height" :row-height="34" :header-height="38" fixed @scroll="event=>scrollLeft=event.scrollLeft" /></template></el-auto-resizer></div>
    <div v-else class="empty compact">{{busy ? '任务执行中，完成后可继续预览' : state==='indexing' ? '正在读取文件，首批数据就绪后自动显示…' : '选择文件后，在这里查看数据'}}</div>
    <div v-if="names.length" class="preview-footer"><span>{{total===null ? `已读取 ${indexed.toLocaleString()} 行 · 继续建立索引` : `共 ${total.toLocaleString()} 行`}} · 每页 50 行</span><div><el-button :disabled="page===1" @click="turn(-1)">上一页</el-button><span class="page-label">{{page}}</span><el-button :disabled="page*50 >= (total ?? indexed)" @click="turn(1)">下一页</el-button></div></div>
    <p v-if="state==='indexing' && names.length" class="muted">当前为部分预览；完整数据与校验以执行结果为准。</p>
  </div>
</template>

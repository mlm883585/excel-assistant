<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { CanceledError } from '@univerjs/core'
import { call } from './rpc'
import type { WorkbookContext, WorkbookEditorHandle, WorkbookVersion, ExportResult } from './workbook/types'
import { createEditor, unavailableCommand } from './workbook/engine'
import { markCircularFormulas } from './workbook/formulaValidation'
import { countCells, fromRange, fromUniver, MAX_CELLS, toUniver, type WorkbookRecord } from './workbook/adapter'

const props = defineProps<{ taskId: string; workbookId: string; revision?: number; busy: boolean; autoExport?: string }>()
const emit = defineEmits<{ context: [value: WorkbookContext]; saved: []; close: []; exportHandled: []; extracted: [id: string]; viewVersion: [id: string, revision: number] }>()
const container = ref<HTMLElement>(), record = shallowRef<WorkbookRecord>(), status = ref('正在载入…'), error = ref(''), dirty = ref(false), saving = ref(false), count = ref(0), history = ref<WorkbookVersion[]>([]), historyOpen = ref(false), historyOffset = ref(0), errors = ref<string[]>([])
let editor: ReturnType<typeof createEditor> | undefined, disposed = false, serial = 0, saveTimer: ReturnType<typeof setTimeout> | undefined, deadline: ReturnType<typeof setTimeout> | undefined, contextTimer: ReturnType<typeof setTimeout> | undefined, activeSave: Promise<void> | undefined
const exporting = ref(false)
const ids = new Map<string, string>(), disposables: { dispose: () => void }[] = []
const used = (c: any) => !!c && (c.v != null || c.f || c.p || c.s && Object.keys(typeof c.s === 'string' ? editor?.workbook.getWorkbook().getStyles().getStyleByCell(c) || {} : c.s).length > 0)
function report(e: unknown) { error.value = String(e); status.value = '未保存'; ElMessage.error(String(e)) }
function cellAddress(key: string) {
  const [row,column]=key.split(',').map(Number);let n=column+1,label=''
  while(n){label=String.fromCharCode(65+(n-1)%26)+label;n=Math.floor((n-1)/26)}
  return `${label}${row+1}`
}
function snapshot() {
  if (!editor || !record.value) throw new Error('编辑器尚未准备完成')
  return fromUniver(editor.workbook.save(), record.value.snapshot, ids, (sid, r, c) => editor!.workbook.getSheetBySheetId(sid)!.getRange(r, c).getFormula())
}
function context() {
  if (!editor || !record.value) return
  const sheet = editor.workbook.getActiveSheet(), area = sheet.getActiveRange(), sid = ids.get(sheet.getSheetId()) || sheet.getSheetId()
  emit('context', { workbook_id: record.value.snapshot.id, version: record.value.revision, readonly: record.value.readonly, sheet_id: sid, sheet_name: sheet.getSheetName(), name: record.value.snapshot.name, range: area ? fromRange(area.getRange()) : null, address: area?.getA1Notation() || '未选择区域', header_row: 1, dirty: dirty.value })
}
function fields(selectedRange = false): string[] {
  if (!editor) return []
  const sheet = editor.workbook.getActiveSheet(), range = sheet.getActiveRange()?.getRange()
  const r = selectedRange ? range?.startRow || 0 : 0, c0 = selectedRange ? range?.startColumn || 0 : 0, c1 = selectedRange ? range?.endColumn || 0 : sheet.getMaxColumns()-1
  return (sheet.getRange(r,c0,1,c1-c0+1).getValues()[0] || []).map(v=>String(v??'').trim()).filter(Boolean)
}
function changed() {
  if (record.value?.readonly || disposed) return
  ++serial; dirty.value = true; status.value = '未保存'
  clearTimeout(saveTimer)
  if (!props.busy) {
    saveTimer = setTimeout(() => void flush(false).catch(report), 1000)
    deadline ||= setTimeout(() => { deadline = undefined; void flush(false).catch(report) }, 10000)
  }
}
async function flush(force = true): Promise<void> {
  clearTimeout(saveTimer); clearTimeout(deadline); deadline = undefined
  if (activeSave) { await activeSave; if (dirty.value) return flush(force); return }
  if (!dirty.value || !editor || !record.value || record.value.readonly) return
  if (props.busy) throw new Error('处理期间不可保存工作簿')
  activeSave = (async () => {
    saving.value = true; status.value = '计算并保存…'
    const version = serial
    try {
      const formula = editor!.api.getFormula()
      await formula.onCalculationResultApplied(30000)
      if (disposed) return
      const data = snapshot()
      if (data.sheets.some(s=>Object.values(s.cells).some(c=>c.formula))) {
        const trees=await formula.getAllDependencyTrees(30000)
        if (disposed) return
        if (serial!==version) { dirty.value=true; status.value='未保存'; return }
        markCircularFormulas(data,trees,ids)
      }
      errors.value = data.sheets.flatMap(s => Object.entries(s.cells).filter(([,c]) => c.formula && c.result_state !== 'ready').map(([key,c]) => `${s.name}!${cellAddress(key)}：${c.result_state === 'error' ? c.value : '等待计算'}`))
      const result = await call<{ revision: number; cell_count: number }>('workbooks.save', { task_id: props.taskId, snapshot: data, expected_version: record.value!.revision })
      if (disposed) return
      record.value = { ...record.value!, snapshot: data, revision: result.revision, current_revision: result.revision }
      count.value = result.cell_count; dirty.value = version !== serial; error.value = ''
      status.value = dirty.value ? '未保存' : `已保存 · 版本 ${result.revision}`
      emit('saved'); context()
    } finally { saving.value = false }
  })()
  try {
    await activeSave
  } catch (failure) {
    error.value = String(failure)
    status.value = '未保存'
    throw failure
  } finally { activeSave = undefined }
  if (dirty.value && force) return flush(true)
  if (dirty.value) { saveTimer = setTimeout(() => void flush(false).catch(report), 1000); deadline ||= setTimeout(() => { deadline = undefined; void flush(false).catch(report) }, 10000) }
}
function guardCapacity(command: any) {
  if (unavailableCommand(command.id)) { ElMessage.warning('此功能不在本机工作簿兼容范围内，未应用修改'); throw new CanceledError() }
  if (!editor || !command.id.includes('.mutation.')) return
  const p = command.params || {}, sheet = editor.workbook.getWorkbook().getSheetBySheetId(p.subUnitId)
  if (command.id === 'sheet.mutation.set-range-values' && p.cellValue && sheet) {
    let next = count.value
    for (const [r, cols] of Object.entries(p.cellValue)) for (const [c, raw] of Object.entries(cols as object)) {
      const old = sheet.getCellRaw(Number(r), Number(c)), merged = raw === null ? null : { ...old, ...(raw as object) }
      next += Number(used(merged)) - Number(used(old))
    }
    if (next > MAX_CELLS) { const message = '操作超过 200000 个有效单元格，已拦截；可改用分页预览与全量处理'; ElMessage.warning(message); throw new CanceledError() }
  }
  if (command.id.includes('insert-sheet') && p.sheet?.cellData) {
    const added = Object.values(p.sheet.cellData).reduce<number>((n, row: any) => n + Object.values(row).filter(used).length, 0)
    if (count.value + added > MAX_CELLS) { ElMessage.warning('新工作表超出 200000 个有效单元格容量'); throw new CanceledError() }
  }
  if(command.id==='sheet.mutation.set.numfmt' && sheet) {
    const cells = new Set<string>()
    for(const entry of Object.values(p.values) as any[]) for(const range of entry.ranges) {
      if((range.endRow-range.startRow+1)*(range.endColumn-range.startColumn+1)>MAX_CELLS){ElMessage.warning('数字格式范围超出 200000 格容量');throw new CanceledError()}
      for(let r=range.startRow;r<=range.endRow;r++) for(let c=range.startColumn;c<=range.endColumn;c++) if(!used(sheet.getCellRaw(r,c))) cells.add(`${r},${c}`)
    }
    if(count.value+cells.size>MAX_CELLS){ElMessage.warning('数字格式将超出 200000 个有效单元格，已拦截');throw new CanceledError()}
  }
}
async function mountEditor() {
  const loaded = await call<WorkbookRecord>('workbooks.open', { task_id: props.taskId, workbook_id: props.workbookId, revision: props.revision })
  if (disposed) return
  record.value = loaded; count.value = countCells(loaded.snapshot)
  for (const sheet of loaded.snapshot.sheets) ids.set(sheet.id, sheet.id)
  editor = createEditor(container.value!, toUniver(loaded.snapshot))
  editor.workbook.setEditable(!props.busy && !loaded.readonly && !props.autoExport)
  disposables.push(editor.api.onBeforeCommandExecute(guardCapacity))
  disposables.push(editor.api.addEvent(editor.api.Event.BeforeClipboardPaste, event => {
    const selection = event.worksheet.getActiveRange()?.getRange()
    if (!selection) return
    const rows = event.text?.replace(/\r\n/g,'\n').replace(/\n$/,'').split('\n').map(r=>r.split('\t')) || []
    const html = event.html ? new DOMParser().parseFromString(event.html,'text/html') : undefined
    const htmlRows = html ? Array.from(html.querySelectorAll('table tr')) : []
    const height = Math.max(rows.length,htmlRows.length), width = Math.max(0,...rows.map(r=>r.length),...htmlRows.map(r=>Array.from(r.querySelectorAll('td,th')).reduce((n,c)=>n+Number(c.getAttribute('colspan')||1),0)))
    if (!height || !width) return
    const targetHeight = Math.max(height, selection.endRow-selection.startRow+1), targetWidth = Math.max(width,selection.endColumn-selection.startColumn+1)
    let additional = 0
    if (targetHeight*targetWidth > MAX_CELLS) additional = MAX_CELLS+1
    else for(let r=0;r<targetHeight;r++) for(let c=0;c<targetWidth;c++) {
      const hasData = htmlRows.length || rows[r%height]?.[c%width]
      if(hasData && !used(editor!.workbook.getWorkbook().getSheetBySheetId(event.worksheet.getSheetId())!.getCellRaw(selection.startRow+r,selection.startColumn+c))) ++additional
    }
    if(count.value+additional>MAX_CELLS) { event.cancel=true; ElMessage.warning('粘贴超过 200000 个有效单元格，已在应用前拦截') }
  }))
  disposables.push(editor.api.onCommandExecuted(command => {
    if (command.id.startsWith('sheet.mutation.') && !command.id.includes('formula-calculation') && !command.id.includes('set-formula')) {
      // Recompute once per mutation from sparse storage, never expand whole rows/columns.
      count.value = editor!.workbook.getWorkbook().getSheets().reduce((n, s) => { let k = 0; s.getCellMatrix().forValue((_r, _c, v) => { if (used(v)) ++k }); return n + k }, 0)
      changed()
    }
    clearTimeout(contextTimer); contextTimer = setTimeout(context, 100)
  }))
  status.value = loaded.readonly ? `只读查看 · 版本 ${loaded.revision}` : `已保存 · 版本 ${loaded.revision}`
  if (!loaded.readonly && loaded.snapshot.sheets.some(s => Object.values(s.cells).some(c => c.formula))) {
    editor.api.getFormula().executeCalculation()
    changed()
  }
  context()
  if (props.autoExport) {
    const outputId = props.autoExport
    // Consume the one-time request before awaiting a native dialog or calculation.
    emit('exportHandled')
    await exportFile(outputId)
  }
}
async function showHistory(offset = 0) {
  await flush(); historyOffset.value = offset
  history.value = await call<WorkbookVersion[]>('workbooks.versions', { task_id: props.taskId, workbook_id: props.workbookId, offset })
  historyOpen.value = true
}
async function restore(version: number) {
  await flush()
  await call('workbooks.restore', { task_id: props.taskId, workbook_id: props.workbookId, revision: version, expected_version: record.value!.current_revision })
  emit('extracted', props.workbookId); historyOpen.value = false
}
function updateEditable() {
  editor?.workbook.setEditable(!props.busy && !record.value?.readonly && !exporting.value)
}
async function exportFile(outputId?: string) {
  if (exporting.value) return
  exporting.value = true
  updateEditable()
  try {
    await flush()
    if (errors.value.length) throw new Error('请先修正公式错误并完成计算，再导出')
    const result = await call<ExportResult>('outputs.export', {
      task_id: props.taskId, workbook_id: props.workbookId,
      expected_version: record.value!.revision, output_id: outputId,
    })
    if (!disposed && result.exported) ElMessage.success(`已导出版本 ${result.revision}：${result.name}`)
  } finally { exporting.value = false; if (!disposed) updateEditable() }
}
function unload(e: BeforeUnloadEvent) { if (dirty.value || saving.value) { e.preventDefault(); e.returnValue = ''; void flush().catch(report) } }
watch(() => props.busy, value => {
  updateEditable()
  if (value) status.value = '任务处理中 · 只读'
  else if (record.value?.readonly) status.value = `只读查看 · 版本 ${record.value.revision}`
  else status.value = dirty.value || error.value ? '未保存' : `已保存 · 版本 ${record.value?.revision || ''}`
})
onMounted(() => { window.addEventListener('beforeunload', unload); void mountEditor().catch(report) })
onBeforeUnmount(() => { disposed = true; clearTimeout(saveTimer); clearTimeout(deadline); clearTimeout(contextTimer); window.removeEventListener('beforeunload', unload); for (const d of disposables) d.dispose(); editor?.sparseStyles.dispose(); editor?.univer.dispose() })
defineExpose<WorkbookEditorHandle>({ flush, exportFile, getContext: () => { context(); return record.value }, snapshot, fields })
</script>

<template>
  <section class="workbook-panel">
    <div class="workbook-tools"><strong>{{record?.snapshot.name || '工作簿'}}</strong><span class="save-state" :class="{unsaved:dirty || error}" role="status">{{status}}</span><span>{{count.toLocaleString()}} / 200,000 格</span><el-button :disabled="busy || !dirty || saving" @click="flush().catch(report)">保存</el-button><el-button :disabled="busy || !record || record.limitations.length>0" @click="showHistory().catch(report)">历史版本</el-button><el-button type="primary" :disabled="busy || exporting || !record || record.readonly" @click="exportFile().catch(report)">确认并导出</el-button></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-if="record?.historical" type="info" :closable="false" :title="`正在查看历史版本 ${record.revision}，当前版本为 ${record.current_revision}。`"><el-button @click="emit('extracted',workbookId)">返回当前版本</el-button><el-button :disabled="busy || record.limitations.length>0" @click="restore(record.revision).catch(report)">恢复此版本</el-button></el-alert>
    <el-alert v-if="record?.limitations.length" type="warning" :closable="false" title="此文件包含首版编辑器未支持的内容，当前只读查看。"><ul><li v-for="item in record.limitations" :key="item">{{item}}</li></ul><el-button v-if="record.source" @click="call('workbooks.open',{task_id:taskId,file_id:record.source,pure_data:true}).then(r=>emit('extracted',r.snapshot.id)).catch(report)">提取纯数据副本并编辑</el-button></el-alert>
    <details v-if="errors.length" class="formula-errors"><summary>有 {{errors.length}} 个公式未成功计算</summary><p v-for="item in errors.slice(0,50)" :key="item">{{item}}</p></details>
    <div ref="container" class="univer-container" aria-label="工作簿编辑器" />
    <el-dialog v-model="historyOpen" title="历史版本 · 恢复会生成新版本" width="760px"><el-table :data="history"><el-table-column prop="revision" label="版本"/><el-table-column prop="kind" label="来源"/><el-table-column prop="created" label="保存时间" width="180"/><el-table-column label="操作" width="180"><template #default="{row}"><el-button @click="emit('viewVersion',workbookId,row.revision)">查看</el-button><el-button :disabled="busy || row.revision===record?.revision" @click="restore(row.revision).catch(report)">恢复</el-button></template></el-table-column></el-table><el-button :disabled="historyOffset===0" @click="showHistory(Math.max(0,historyOffset-50)).catch(report)">上一页</el-button><el-button :disabled="history.length<50" @click="showHistory(historyOffset+50).catch(report)">下一页</el-button></el-dialog>
  </section>
</template>

<style scoped>
.workbook-panel{display:flex;flex-direction:column;min-width:0;height:100%;background:white;border:1px solid #dce3ed;border-radius:12px;overflow:hidden}.workbook-tools{display:flex;align-items:center;gap:10px;padding:10px 12px;flex-wrap:wrap;font-size:12px;border-bottom:1px solid #e6eaf0}.workbook-tools strong{font-size:14px;margin-right:auto}.save-state{color:#36775b}.save-state.unsaved{color:#b75a15}.univer-container{flex:1;min-height:510px;position:relative;isolation:isolate}.formula-errors{padding:8px 16px;max-height:120px;overflow:auto;color:#a8332c}.workbook-panel :deep(.el-alert){flex-shrink:0;max-height:180px;overflow:auto}
</style>

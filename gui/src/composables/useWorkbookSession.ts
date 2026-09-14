import { onBeforeUnmount, ref, type Ref } from 'vue'
import { call, type Task } from '../rpc'
import type { WorkbookRecord } from '../workbook/adapter'
import type { WorkbookContext, WorkbookEditorHandle, WorkbookSelection, WorkbookSummary } from '../workbook/types'

type Options = { task: Ref<Task | undefined>; capture: () => () => boolean; opened: () => void }

export function useWorkbookSession(options: Options) {
  const editor = ref<WorkbookEditorHandle>()
  const workbookId = ref(''), editorKey = ref(0), books = ref<WorkbookSummary[]>([])
  const workbookContext = ref<WorkbookContext>(), inputScope = ref('sheet')
  const workbookRevision = ref<number>(), autoExport = ref<string>()
  const view = ref('work')
  let navigation = 0, listing = 0, disposed = false

  async function flush() { await editor.value?.flush() }
  function reset() {
    ++navigation
    ++listing
    workbookId.value = ''
    workbookContext.value = undefined
    workbookRevision.value = undefined
    autoExport.value = undefined
    books.value = []
    view.value = 'work'
  }
  async function refreshBooks() {
    if (!options.task.value) return
    const current = options.capture(), request = ++listing
    const result = await call<WorkbookSummary[]>('workbooks.list', { task_id: options.task.value.id })
    if (!disposed && current() && request === listing) books.value = result
  }
  async function changeView(next: string) {
    const current = options.capture(), request = ++navigation
    await flush()
    if (!disposed && current() && request === navigation) view.value = next
  }
  async function openBook(id?: string, fileId?: string, revision?: number, exportOutput?: string) {
    const taskId = options.task.value?.id
    if (!taskId) return
    const current = options.capture(), request = ++navigation
    await flush()
    if (disposed || !current() || request !== navigation) return
    const result = await call<WorkbookRecord>('workbooks.open', {
      task_id: taskId, revision, ...(id ? { workbook_id: id } : fileId ? { file_id: fileId } : {}),
    })
    if (disposed || !current() || request !== navigation) return
    workbookContext.value = undefined
    autoExport.value = exportOutput
    workbookRevision.value = revision
    workbookId.value = result.snapshot.id
    ++editorKey.value
    view.value = 'editor'
    options.opened()
    await refreshBooks()
  }
  function bookInput(forEditing = false): WorkbookSelection {
    const context = workbookContext.value
    if (!context || context.workbook_id !== workbookId.value) throw new Error('请先打开工作簿并选择工作表')
    if (context.readonly) throw new Error('请返回当前可编辑版本，或提取纯数据副本后处理')
    return {
      workbook_id: context.workbook_id, version: context.version, sheet_id: context.sheet_id,
      range: forEditing || inputScope.value === 'range' ? context.range : null, header_row: 1,
    }
  }
  onBeforeUnmount(() => { disposed = true; reset() })
  return {
    editor, workbookId, editorKey, books, workbookContext, inputScope, workbookRevision,
    autoExport, view, flush, reset, refreshBooks, changeView, openBook, bookInput,
  }
}

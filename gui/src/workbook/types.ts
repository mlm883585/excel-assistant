import type { Area, Snapshot, WorkbookRecord } from './adapter'

export type WorkbookSummary = { id: string; name: string; revision: number }
export type WorkbookVersion = { revision: number; kind: string; created: string }
export type WorkbookSelection = {
  workbook_id: string
  version: number
  sheet_id: string
  range: Area | null
  header_row: number
}
export type WorkbookContext = WorkbookSelection & {
  readonly: boolean
  sheet_name: string
  name: string
  address: string
  dirty: boolean
}
export type WorkbookEditorHandle = {
  flush: (force?: boolean) => Promise<void>
  exportFile: (outputId?: string) => Promise<void>
  fields: (selectedRange?: boolean) => string[]
  snapshot: () => Snapshot
  getContext: () => WorkbookRecord | undefined
}
export type OutputChange = {
  id: number
  kind: string
  property?: string
  location: string
  old?: unknown
  new?: unknown
  note?: string
}
export type OutputReview = {
  legacy?: boolean
  message?: string
  operation?: string
  inputs?: unknown[]
  base?: { revision: number }
  total: number
  counts?: Record<string, number>
  can_edit?: boolean
  applied_book?: string
  applied_revision?: number
  exported_revision?: number
  export_valid?: boolean
  state?: string
  limitations?: string[]
  requires_excel_recalculation?: boolean
}
export type ExportResult = { exported: boolean; revision?: number; name?: string }

import { LocaleType, type IWorkbookData } from '@univerjs/core'

export type Area = { r0: number; c0: number; r1: number; c1: number }
export type Style = Record<string, any>
export type Cell = { value?: string | number | boolean | null; type?: string; formula?: string; result_state?: string; style?: Style }
export type Sheet = { id: string; name: string; row_count: number; column_count: number; cells: Record<string, Cell>; rows: Record<string, any>; columns: Record<string, any>; merges: Area[]; freeze: { row: number; column: number }; filter: any; hidden?: boolean }
export type Snapshot = { schema_version: 1; id: string; name: string; date1904: boolean; sheets: Sheet[] }
export type WorkbookRecord = { snapshot: Snapshot; revision: number; current_revision: number; readonly: boolean; historical?: boolean; limitations: string[]; source?: string }
export const MAX_CELLS = 200000
const borders = ['', 'thin', 'hair', 'dotted', 'dashed', 'dashDot', 'dashDotDot', 'double', 'medium', 'mediumDashed', 'mediumDashDot', 'mediumDashDotDot', 'slantDashDot', 'thick']
const align = ['general', 'left', 'center', 'right', 'justify']
const valign = ['', 'top', 'center', 'bottom']
const edge: Record<string, string> = { left: 'l', right: 'r', top: 't', bottom: 'b' }
const errors = new Set(['#DIV/0!', '#N/A', '#NAME?', '#NULL!', '#NUM!', '#REF!', '#VALUE!', '#SPILL!', '#CYCLE!'])
export const newId = () => crypto.randomUUID().replaceAll('-', '')
export const toRange = (r: Area) => ({ startRow: r.r0, startColumn: r.c0, endRow: r.r1, endColumn: r.c1 })
export const fromRange = (r: any): Area => ({ r0: r.startRow, c0: r.startColumn, r1: r.endRow, c1: r.endColumn })

function toStyle(s: Style = {}): any {
  const result: any = {}
  for (const [a, b] of Object.entries({ font_name: 'ff', font_size: 'fs' })) if (s[a] !== undefined) result[b] = s[a]
  for (const [a, b] of Object.entries({ bold: 'bl', italic: 'it' })) if (s[a] !== undefined) result[b] = Number(s[a])
  if (s.underline !== undefined) result.ul = { s: Number(s.underline) }
  if (s.strike !== undefined) result.st = { s: Number(s.strike) }
  if (s.font_color) result.cl = { rgb: s.font_color }
  if (s.bg_color) result.bg = { rgb: s.bg_color }
  if (s.num_format) result.n = { pattern: s.num_format }
  if (s.align) result.ht = align.indexOf(s.align)
  if (s.valign) result.vt = valign.indexOf(s.valign)
  if (s.text_wrap !== undefined) result.tb = s.text_wrap ? 3 : 1
  if (s.rotation !== undefined) result.tr = { a: s.rotation, v: 0 }
  if (s.borders) result.bd = Object.fromEntries(Object.entries(s.borders).map(([k, v]: [string, any]) => [edge[k], { s: borders.indexOf(v.style), cl: { rgb: v.color || '#000000' } }]))
  return result
}

function fromStyle(input: any, styles: any): Style {
  const s = typeof input === 'string' ? styles[input] || {} : input || {}, result: Style = {}
  for (const [a, b] of Object.entries({ ff: 'font_name', fs: 'font_size' })) if (s[a] != null) result[b] = s[a]
  for (const [a, b] of Object.entries({ bl: 'bold', it: 'italic' })) if (s[a] != null) result[b] = Boolean(s[a])
  if (s.ul) result.underline = Boolean(s.ul.s)
  if (s.st) result.strike = Boolean(s.st.s)
  if (s.cl?.rgb) result.font_color = normalizeColor(s.cl.rgb)
  if (s.bg?.rgb) result.bg_color = normalizeColor(s.bg.rgb)
  if (s.n?.pattern) result.num_format = s.n.pattern
  if (s.ht) result.align = align[s.ht] || 'justify'
  if (s.vt) result.valign = valign[s.vt] || 'bottom'
  if (s.tb) result.text_wrap = s.tb === 3
  if (s.tr) result.rotation = s.tr.a || 0
  if (s.bd) {
    result.borders = {}
    for (const [name, code] of Object.entries(edge)) if (s.bd[code]?.s) result.borders[name] = { style: borders[s.bd[code].s], color: normalizeColor(s.bd[code].cl?.rgb || '#000000') }
    if (!Object.keys(result.borders).length) delete result.borders
  }
  return result
}

function normalizeColor(value: string) {
  if (/^#[\da-f]{6}$/i.test(value)) return value.toUpperCase()
  if (/^#[\da-f]{8}$/i.test(value)) return value.slice(0, 7).toUpperCase()
  const rgb = value.match(/^rgb\((\d+),\s*(\d+),\s*(\d+)\)$/)
  if (rgb) return '#' + rgb.slice(1).map(n => Number(n).toString(16).padStart(2, '0')).join('').toUpperCase()
  throw new Error(`暂不支持颜色 ${value}，请使用不透明 RGB 颜色`)
}

export function countCells(snapshot: Snapshot) {
  return snapshot.sheets.reduce((total, s) => total + Object.values(s.cells).filter(c => c.value != null || c.formula || c.style && Object.keys(c.style).length).length, 0)
}

export function toUniver(book: Snapshot): IWorkbookData {
  const sheets: any = {}, filters: any = {}
  for (const s of book.sheets) {
    const cellData: any = {}
    for (const [key, c] of Object.entries(s.cells)) {
      const [row, col] = key.split(',')
      cellData[row] ||= {}
      cellData[row][col] = { ...(c.value != null ? { v: c.value, t: c.type === 'boolean' ? 3 : ['number', 'date'].includes(c.type || '') ? 2 : 1 } : {}), ...(c.formula ? { f: c.formula } : {}), ...(c.style ? { s: toStyle(c.style) } : {}) }
    }
    const dimensions = (items: any, size: string, key: string) => Object.fromEntries(Object.entries(items).map(([i, p]: [string, any]) => [i, { ...(p[size] != null ? { [key]: p[size] } : {}), ...(p.hidden ? { hd: 1 } : {}), ...(p.style ? { s: toStyle(p.style) } : {}) }]))
    sheets[s.id] = { id: s.id, name: s.name, hidden: Number(!!s.hidden), rowCount: s.row_count, columnCount: s.column_count, cellData, rowData: dimensions(s.rows, 'height', 'h'), columnData: dimensions(s.columns, 'width', 'w'), mergeData: s.merges.map(toRange), freeze: { xSplit: s.freeze.column, ySplit: s.freeze.row, startRow: s.freeze.row, startColumn: s.freeze.column }, defaultColumnWidth: 88, defaultRowHeight: 24 }
    if (s.filter) filters[s.id] = { ref: toRange(s.filter.range), cachedFilteredOut: s.filter.hidden_rows || [], filterColumns: s.filter.columns.map((c: any) => ({ colId: c.column, filters: { filters: c.values.map(String), ...(c.blank ? { blank: true } : {}) } })) }
  }
  return { id: book.id, name: book.name, appVersion: '0.25.1', locale: LocaleType.ZH_CN, sheetOrder: book.sheets.map(s => s.id), sheets, styles: {}, resources: [{ name: 'SHEET_FILTER_PLUGIN', data: JSON.stringify(filters) }] }
}

export function fromUniver(data: IWorkbookData, original: Snapshot, ids: Map<string, string>, resolveFormula?: (sheet: string, row: number, column: number) => string): Snapshot {
  const result: Snapshot = { schema_version: 1, id: original.id, name: data.name || original.name, date1904: original.date1904, sheets: [] }
  const filters = JSON.parse(data.resources?.find(r => r.name === 'SHEET_FILTER_PLUGIN')?.data || '{}')
  for (const sid of data.sheetOrder) {
    const s = data.sheets[sid]!, cells: Record<string, Cell> = {}
    if (!ids.has(sid)) ids.set(sid, /^[a-f0-9]{32}$/.test(sid) ? sid : newId())
    for (const [row, columns] of Object.entries(s.cellData || {})) for (const [col, raw] of Object.entries(columns || {})) {
      if (!raw) continue
      const c = raw as any, style = fromStyle(c.s, data.styles)
      let value = c.v ?? null
      if (c.p?.body?.textRuns?.some((run:any)=>Object.keys(run.ts||{}).length)) throw new Error(`${s.name} 的单元格含分段文字格式，当前修改未保存；请改用纯文本和统一的单元格格式`)
      if (c.p?.body?.dataStream) value = c.p.body.dataStream.replace(/\r\n$/, '')
      const formula = c.si ? resolveFormula?.(sid, Number(row), Number(col)) || c.f : c.f
      if (c.si && !formula) throw new Error('无法还原共享公式，当前修改未保存')
      if (value == null && !formula && !Object.keys(style).length) continue
      const cell: Cell = { value, type: typeof value === 'boolean' || c.t === 3 ? 'boolean' : typeof value === 'number' ? 'number' : 'string' }
      if (c.t === 3 && typeof value === 'number') cell.value = Boolean(value)
      // Numeric dates remain serials with their number format. Original epoch is retained separately.
      if (Object.keys(style).length) cell.style = style
      if (formula) {
        cell.formula = formula
        cell.result_state = value == null ? 'pending' : errors.has(String(value)) ? 'error' : 'ready'
        if (cell.result_state === 'error') cell.type = 'error'
      }
      cells[`${row},${col}`] = cell
    }
    const dimensions = (items: any, size: string, key: string) => Object.fromEntries(Object.entries(items || {}).map(([i, raw]: [string, any]) => {
      const p = raw || {}, style = fromStyle(p.s, data.styles)
      return [i, { ...(p[key] != null ? { [size]: p[key] } : {}), ...(p.hd ? { hidden: true } : {}), ...(Object.keys(style).length ? { style } : {}) }]
    }))
    const filter = filters[sid]
    if (filter?.filterColumns?.some((c: any) => c.customFilters || c.colorFilters)) throw new Error('当前格式适配支持按值筛选，请将颜色或条件筛选改为按值筛选后保存')
    result.sheets.push({ id: ids.get(sid)!, name: s.name!, row_count: s.rowCount!, column_count: s.columnCount!, cells, rows: dimensions(s.rowData, 'height', 'h'), columns: dimensions(s.columnData, 'width', 'w'), merges: (s.mergeData || []).map(fromRange), freeze: { row: s.freeze?.ySplit || 0, column: s.freeze?.xSplit || 0 }, hidden: !!s.hidden, filter: filter ? { range: fromRange(filter.ref), hidden_rows:filter.cachedFilteredOut || [], columns: (filter.filterColumns || []).map((c: any) => ({ column: c.colId, values: c.filters?.filters || [], blank: !!c.filters?.blank })) } : null })
  }
  if (countCells(result) > MAX_CELLS) throw new Error('完整编辑最多支持 200000 个有效单元格；请缩小操作范围')
  return result
}

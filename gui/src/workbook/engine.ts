import { LocaleType, Univer, mergeLocales, type IWorkbookData } from '@univerjs/core'
import { FUniver } from '@univerjs/core/facade'
import { defaultTheme } from '@univerjs/themes'
import { UniverRenderEnginePlugin } from '@univerjs/engine-render'
import { UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { UniverUIPlugin } from '@univerjs/ui'
import { UniverDocsPlugin } from '@univerjs/docs'
import { UniverDocsUIPlugin } from '@univerjs/docs-ui'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { UniverSheetsUIPlugin } from '@univerjs/sheets-ui'
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import { UniverSheetsFormulaUIPlugin } from '@univerjs/sheets-formula-ui'
import { UniverSheetsNumfmtPlugin } from '@univerjs/sheets-numfmt'
import { UniverSheetsNumfmtUIPlugin } from '@univerjs/sheets-numfmt-ui'
import { UniverSheetsFilterPlugin } from '@univerjs/sheets-filter'
import { UniverSheetsFilterUIPlugin } from '@univerjs/sheets-filter-ui'
import { UniverSheetsSortPlugin } from '@univerjs/sheets-sort'
import { UniverSheetsSortUIPlugin } from '@univerjs/sheets-sort-ui'
import { UniverFindReplacePlugin } from '@univerjs/find-replace'
import { UniverSheetsFindReplacePlugin } from '@univerjs/sheets-find-replace'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-ui/facade'
import '@univerjs/ui/facade'
import '@univerjs/engine-formula/facade'
import '@univerjs/sheets-formula/facade'
import '@univerjs/sheets-filter/facade'
import '@univerjs/sheets-numfmt/facade'
import '@univerjs/design/lib/index.css'
import '@univerjs/ui/lib/index.css'
import '@univerjs/docs-ui/lib/index.css'
import '@univerjs/sheets-ui/lib/index.css'
import '@univerjs/sheets-formula-ui/lib/index.css'
import '@univerjs/sheets-numfmt-ui/lib/index.css'
import '@univerjs/sheets-filter-ui/lib/index.css'
import '@univerjs/sheets-sort-ui/lib/index.css'
import '@univerjs/find-replace/lib/index.css'
import DesignZh from '@univerjs/design/locale/zh-CN'
import UIZh from '@univerjs/ui/locale/zh-CN'
import DocsZh from '@univerjs/docs-ui/locale/zh-CN'
import SheetsZh from '@univerjs/sheets/locale/zh-CN'
import SheetsUIZh from '@univerjs/sheets-ui/locale/zh-CN'
import FormulaZh from '@univerjs/sheets-formula/locale/zh-CN'
import FormulaUIZh from '@univerjs/sheets-formula-ui/locale/zh-CN'
import NumfmtZh from '@univerjs/sheets-numfmt-ui/locale/zh-CN'
import FilterZh from '@univerjs/sheets-filter-ui/locale/zh-CN'
import SortZh from '@univerjs/sheets-sort-ui/locale/zh-CN'
import FindZh from '@univerjs/find-replace/locale/zh-CN'
import { commonStyles } from './commonStyles'

const unavailable = [
  'sheet.command.add-range-protection-from-toolbar', 'sheet.command.add-range-protection-from-context-menu',
  'sheet.command.add-range-protection-from-sheet-bar', 'sheet.command.view-sheet-permission-from-context-menu',
  'sheet.command.view-sheet-permission-from-sheet-bar', 'sheet.command.set-range-protection-from-context-menu',
  'sheet.command.change-sheet-protection-from-sheet-bar', 'sheet-permission.operation.openPanel',
  'sheet-permission.operation.openDialog', 'sidebar.operation.defined-name',
  'sheet.command.set-worksheet-range-theme-style', 'sheet.command.set-range-subscript', 'sheet.command.set-range-superscript',
]
export const unavailableCommand = (id: string) => unavailable.includes(id) || id.startsWith('sheet.command.') && /defined-name|range-theme|protection/.test(id)

export function createEditor(container: HTMLElement, data: IWorkbookData) {
  const univer = new Univer({ locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: mergeLocales(DesignZh, UIZh, DocsZh, SheetsZh, SheetsUIZh, FormulaZh, FormulaUIZh, NumfmtZh, FilterZh, SortZh, FindZh) }, theme: defaultTheme })
  univer.registerPlugin(UniverRenderEnginePlugin)
  univer.registerPlugin(UniverFormulaEnginePlugin)
  univer.registerPlugin(UniverUIPlugin, { container, header: true, toolbar: true, footer: true, menu: Object.fromEntries(unavailable.map(id=>[id,{hidden:true}])) })
  univer.registerPlugin(UniverDocsPlugin)
  univer.registerPlugin(UniverDocsUIPlugin)
  univer.registerPlugin(UniverSheetsPlugin)
  univer.registerPlugin(UniverSheetsUIPlugin)
  univer.registerPlugin(UniverSheetsFormulaPlugin)
  univer.registerPlugin(UniverSheetsFormulaUIPlugin)
  univer.registerPlugin(UniverSheetsNumfmtPlugin)
  univer.registerPlugin(UniverSheetsNumfmtUIPlugin)
  univer.registerPlugin(UniverSheetsFilterPlugin)
  univer.registerPlugin(UniverSheetsFilterUIPlugin)
  univer.registerPlugin(UniverSheetsSortPlugin)
  univer.registerPlugin(UniverSheetsSortUIPlugin)
  univer.registerPlugin(UniverFindReplacePlugin)
  univer.registerPlugin(UniverSheetsFindReplacePlugin)
  const api = FUniver.newAPI(univer), workbook = api.createWorkbook(data)
  const sparseStyles = commonStyles(univer, api)
  return { univer, api, workbook, sparseStyles }
}

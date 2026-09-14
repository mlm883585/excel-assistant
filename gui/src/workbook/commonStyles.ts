/** Keep row/column styles sparse, including numeric formats and native undo/redo. */
import { CanceledError, CommandType, ICommandService, IUndoRedoService, type Univer } from '@univerjs/core'
import { INumfmtService, SetColDataMutation, SetColDataMutationFactory, SetRowDataMutation, SetRowDataMutationFactory, SetRangeValuesMutation, SetRangeValuesUndoMutationFactory, SheetsSelectionsService } from '@univerjs/sheets'
import type { FUniver } from '@univerjs/core/facade'

export function commonStyles(univer: Univer, api: FUniver) {
  const injector = univer.__getInjector(), commands = injector.get(ICommandService)
  const numfmt = injector.get(INumfmtService), originalNumfmt = numfmt.getValue.bind(numfmt)
  numfmt.getValue = (unit, sid, row, col) => {
    const direct = originalNumfmt(unit,sid,row,col)
    if (direct) return direct
    const sheet = api.getWorkbook(unit)?.getWorkbook().getSheetBySheetId(sid)
    return sheet?.getRowStyle(row)?.n || sheet?.getColumnStyle(col)?.n || null
  }
  const custom = commands.registerCommand({
    id:'workbook.command.common-style',type:CommandType.COMMAND,
    handler: (accessor, params: any) => {
      const workbook = api.getActiveWorkbook()!, sheet = workbook.getWorkbook().getSheetBySheetId(params.sheetId)!, { range, style } = params
      const common = { unitId:workbook.getId(),subUnitId:params.sheetId }, isRow = range.rangeType===1
      const start = isRow?range.startRow:range.startColumn, end = isRow?range.endRow:range.endColumn, data: any={}
      for(let i=start;i<=end;i++) data[i]={s:{...(isRow?sheet.getRowStyle(i):sheet.getColumnStyle(i))||{},[style.type]:style.value}}
      const values: any={}
      sheet.getCellMatrix().forValue((r,c,cell)=> {
        const i = isRow?r:c
        if(i>=start && i<=end && cell) {values[r] ||= {}; values[r][c]={s:{[style.type]:style.value}}}
      })
      const props = {...common,cellValue:values}, meta = isRow?{...common,rowData:data}:{...common,columnData:data}
      const mutation = isRow?SetRowDataMutation:SetColDataMutation
      const before = isRow?SetRowDataMutationFactory(meta as any,sheet):SetColDataMutationFactory(meta as any,sheet)
      const beforeCells = SetRangeValuesUndoMutationFactory(accessor,props)
      if(!commands.syncExecuteCommand(mutation.id,meta) || !commands.syncExecuteCommand(SetRangeValuesMutation.id,props)) return false
      accessor.get(IUndoRedoService).pushUndoRedo({unitID:common.unitId,undoMutations:[{id:mutation.id,params:before},{id:SetRangeValuesMutation.id,params:beforeCells}],redoMutations:[{id:mutation.id,params:meta},{id:SetRangeValuesMutation.id,params:props}]})
      return true
    }
  })
  const listener = commands.beforeCommandExecuted((command: any) => {
    if(!['sheet.command.set-style','sheet.command.numfmt.set.numfmt'].includes(command.id))return
    const ranges = command.params?.range?[command.params.range]:injector.get(SheetsSelectionsService).getCurrentSelections().map(s=>s.range)
    if(ranges.length!==1 || ![1,2].includes(ranges[0].rangeType))return
    const range=ranges[0]
    let style=command.params.style
    if(command.id==='sheet.command.numfmt.set.numfmt') {
      const patterns=new Set(command.params.values.map((v:any)=>v.pattern))
      if(patterns.size!==1)return
      style={type:'n',value:{pattern:command.params.values[0].pattern||'General'}}
    }
    if(!style || Array.isArray(style.value))return
    const sheetId=command.params.subUnitId || api.getActiveWorkbook()!.getActiveSheet().getSheetId()
    commands.syncExecuteCommand('workbook.command.common-style',{range,style,sheetId})
    throw new CanceledError()
  })
  return {dispose(){listener.dispose();custom.dispose();numfmt.getValue=originalNumfmt}}
}

import copy
import json

from .workbook_model import blank_workbook, blank_sheet, identifier, get_sheet, validate_snapshot, validate_style, validate_range, invalidate_formulas, formula_issue, MAX_CELLS
from .workbooks import Workbooks


def cell(value):
    if value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError('单元格值须为文本、数字、布尔值或空值')
    return {'value': value, 'type': 'boolean' if isinstance(value, bool) else 'number' if isinstance(value, (float, int)) else 'string'}


def create_table(params):
    if set(params) - {'name', 'sheet_name', 'columns', 'rows', 'blank_rows', 'example_data'}:
        raise ValueError('建表包含未知参数')
    columns = params.get('columns')
    if not isinstance(columns, list) or not columns or len(columns) > 1000 or any(not isinstance(c, str) or not c.strip() for c in columns) or len(set(columns)) != len(columns):
        raise ValueError('请明确提供不重复的表头字段')
    if any(c.startswith('__source_') for c in columns):
        raise ValueError('表头不能使用系统保留的来源字段')
    rows, blank = params.get('rows', []), params.get('blank_rows', 20)
    if not isinstance(rows, list) or type(blank) is not int or not 0 <= blank <= 10000:
        raise ValueError('数据或空白填报行数无效')
    if (1 + max(len(rows), blank)) * len(columns) > MAX_CELLS:
        raise ValueError('建表超出 200000 个有效单元格容量')
    book = blank_workbook(params.get('name', '新建工作簿'))
    sheet = book['sheets'][0]
    sheet['name'] = params.get('sheet_name', '填报表')
    if params.get('example_data'):
        sheet['name'] = sheet['name'][:25] + '（示例）'
    sheet['row_count'] = max(21, len(rows) + 1, blank + 1)
    sheet['column_count'] = max(26, len(columns))
    sheet['freeze'] = {'row': 1, 'column': 0}
    for c, title in enumerate(columns):
        sheet['cells'][f'0,{c}'] = {**cell(title), 'style': {'bold': True, 'bg_color': '#E8EFFA'}}
        sheet['columns'][str(c)] = {'width': 140}
        for r in range(1, max(len(rows), blank) + 1):
            sheet['cells'][f'{r},{c}'] = {**cell(None), 'style': {'borders': {'bottom': {'style': 'hair', 'color': '#D9E0EA'}}}}
    for r, row in enumerate(rows, 1):
        if not isinstance(row, list) or len(row) != len(columns):
            raise ValueError('每行数据数量须与表头一致，缺失数字请使用 null')
        for c, value in enumerate(row):
            sheet['cells'][f'{r},{c}'].update(cell(value))
    validate_snapshot(book)
    return book


def edit_workbook(book, selected_sheet, params):
    if set(params) != {'edits'} or not isinstance(params['edits'], list) or not 1 <= len(params['edits']) <= 100:
        raise ValueError('编辑需要 1–100 个 edits 操作')
    result = copy.deepcopy(book)
    for edit in params['edits']:
        kind = edit.get('kind')
        if kind == 'add_sheet' and set(edit) == {'kind', 'name'}:
            result['sheets'].append(blank_sheet(edit['name']))
            continue
        target = get_sheet(result, edit.get('sheet_id', selected_sheet))
        if kind == 'rename_sheet' and not set(edit) - {'kind', 'sheet_id', 'name'}:
            target['name'] = edit['name']
        elif kind in {'set_values', 'set_style'} and not set(edit) - {'kind', 'sheet_id', 'range', 'values' if kind == 'set_values' else 'style'}:
            area = edit['range']; validate_range(area)
            height, width = area['r1']-area['r0']+1, area['c1']-area['c0']+1
            if height * width > MAX_CELLS:
                raise ValueError('编辑区域超出 200000 个单元格容量')
            if kind == 'set_values':
                values = edit['values']
                if not isinstance(values, list) or len(values) != height or any(not isinstance(r, list) or len(r) != width for r in values):
                    raise ValueError('值矩阵尺寸须与选区一致')
            else:
                validate_style(edit['style'])
            for r in range(area['r0'], area['r1'] + 1):
                for c in range(area['c0'], area['c1'] + 1):
                    key = f'{r},{c}'
                    before = target['cells'].get(key, {})
                    if kind == 'set_values':
                        target['cells'][key] = {**cell(values[r-area['r0']][c-area['c0']]), **({'style': before['style']} if before.get('style') else {})}
                    else:
                        target['cells'][key] = {**before, 'style': {**before.get('style', {}), **edit['style']}}
            target['row_count'] = max(target['row_count'], area['r1']+1)
            target['column_count'] = max(target['column_count'], area['c1']+1)
        elif kind == 'set_formula' and not set(edit) - {'kind', 'sheet_id', 'range', 'formulas'}:
            area = edit['range']; validate_range(area)
            height, width = area['r1']-area['r0']+1, area['c1']-area['c0']+1
            if height * width > MAX_CELLS:
                raise ValueError('编辑区域超出 200000 个单元格容量')
            formulas = edit['formulas']
            if not isinstance(formulas, list) or len(formulas) != height or any(not isinstance(row, list) or len(row) != width for row in formulas):
                raise ValueError('公式矩阵尺寸须与选区一致')
            for r in range(area['r0'], area['r1'] + 1):
                for c in range(area['c0'], area['c1'] + 1):
                    key = f'{r},{c}'
                    formula = formulas[r-area['r0']][c-area['c0']]
                    before = target['cells'].get(key, {})
                    if formula in (None, ''):
                        target['cells'].pop(key, None)
                        continue
                    issue = formula_issue(formula)
                    if issue:
                        raise ValueError(issue)
                    target['cells'][key] = {'formula': formula, 'value': None, 'result_state': 'pending', **({'style': before['style']} if before.get('style') else {})}
            target['row_count'] = max(target['row_count'], area['r1']+1)
            target['column_count'] = max(target['column_count'], area['c1']+1)
        else:
            raise ValueError('编辑只允许 set_values/set_style/set_formula/add_sheet/rename_sheet')
        validate_snapshot(result)
    invalidate_formulas(result)
    validate_snapshot(result)
    return result


def run_workbook_operation(store, task, op):
    service, base = Workbooks(store), None
    if op.kind == 'create_table':
        snapshot = create_table(op.params)
    else:
        selection = op.inputs[0]
        scope = store.get(task).get('editing_scope')
        if scope and any(scope.get(k) != getattr(selection, k) for k in ('workbook_id', 'version', 'sheet_id')):
            raise ValueError('编辑目标与用户当前工作簿、版本或工作表不一致')
        allowed = scope.get('range') if scope else selection.range
        for edit in op.params.get('edits', []):
            if edit.get('kind') in {'set_values', 'set_style', 'set_formula'}:
                if edit.get('sheet_id', selection.sheet_id) != selection.sheet_id:
                    raise ValueError('编辑不能跨出用户选择的工作表')
                area = edit.get('range'); validate_range(area)
                if allowed and not (allowed['r0'] <= area['r0'] <= area['r1'] <= allowed['r1'] and allowed['c0'] <= area['c0'] <= area['c1'] <= allowed['c1']):
                    raise ValueError('编辑超出用户选区，请先扩大选区并明确要求')
        record = service.load(task, selection.workbook_id, selection.version)
        if record['readonly'] or record['current_revision'] != selection.version:
            raise ValueError('工作簿只读或版本过期')
        base = {'id': selection.workbook_id, 'revision': selection.version}
        snapshot = edit_workbook(record['snapshot'], selection.sheet_id, op.params)
    output_id = identifier()
    service.candidate(task, output_id, snapshot, base, {'operation': op.kind, 'inputs': [i.model_dump(exclude_none=True) for i in op.inputs], 'rules': op.params})
    # A pending workbook is kept in the task store, never passed off as a calculated xlsx.
    folder = store.directory(task) / 'outputs'; folder.mkdir(exist_ok=True)
    path = folder / f'{output_id}.workbook.json'
    path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')
    info = {'id': output_id, 'name': snapshot['name'], 'kind': 'workbook_candidate', 'relative': str(path.relative_to(store.directory(task))), 'validated': True, 'statistics': {'output_rows': sum(s['row_count'] for s in snapshot['sheets'])}}
    record = store.get(task); record['outputs'].append(info); store.save(record)
    return info

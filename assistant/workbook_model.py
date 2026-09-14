"""Application-owned workbook contract. No editor or model SDK objects live here."""
import copy
import math
import re
import uuid

MAX_CELLS = 200_000
MAX_ROWS = 1_048_576
MAX_COLS = 16_384
FUNCTIONS = set('SUM AVERAGE MIN MAX COUNT COUNTA IF IFERROR AND OR ROUND SUMIF COUNTIF VLOOKUP INDEX MATCH ABS SUMIFS COUNTIFS LEFT RIGHT MID LEN TRIM CONCATENATE DATE YEAR MONTH DAY NOT ISBLANK ISNUMBER ISTEXT ROUNDUP ROUNDDOWN'.split())
ERRORS = {'#DIV/0!', '#N/A', '#NAME?', '#NULL!', '#NUM!', '#REF!', '#VALUE!', '#SPILL!', '#CYCLE!'}
STYLE_KEYS = {'font_name', 'font_size', 'bold', 'italic', 'underline', 'strike', 'font_color', 'bg_color', 'align', 'valign', 'text_wrap', 'rotation', 'num_format', 'borders'}


def identifier():
    return uuid.uuid4().hex


def blank_sheet(name='Sheet1'):
    return {'id': identifier(), 'name': name, 'row_count': 100, 'column_count': 26,
            'cells': {}, 'rows': {}, 'columns': {}, 'merges': [], 'freeze': {'row': 0, 'column': 0}, 'filter': None}


def blank_workbook(name='新建工作簿'):
    return {'schema_version': 1, 'id': identifier(), 'name': name, 'date1904': False, 'sheets': [blank_sheet()]}


def coordinate(row, column):
    return f'{row},{column}'


def position(key):
    if not isinstance(key, str) or not re.fullmatch(r'\d+,\d+', key):
        raise ValueError('单元格坐标无效')
    row, column = map(int, key.split(','))
    if not 0 <= row < MAX_ROWS or not 0 <= column < MAX_COLS:
        raise ValueError('单元格超出 Excel 范围')
    return row, column


def sheet_name(name):
    if not isinstance(name, str) or not name.strip() or len(name) > 31 or re.search(r'[\[\]:*?/\\]', name) or name.startswith("'") or name.endswith("'"):
        raise ValueError('工作表名称须为 1–31 个字符，不能包含 []:*?/\\ 或首尾单引号')
    return name


def formula_issue(formula):
    from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
    if not isinstance(formula, str) or not formula.startswith('=') or len(formula) > 8192:
        return '公式格式或长度无效'
    if '[' in formula or ']' in formula:
        return '外部或结构化引用暂不支持'
    try:
        for token in Tokenizer(formula).items:
            if token.type == 'FUNC' and token.subtype == 'OPEN' and token.value[:-1].upper() not in FUNCTIONS:
                return f'暂不支持公式函数 {token.value[:-1]}'
            if token.type == 'ARRAY':
                return '数组公式暂不支持'
    except (TokenizerError, IndexError) as exc:
        return f'公式无法解析：{exc}'
    return None


def validate_style(style):
    if not isinstance(style, dict) or set(style) - STYLE_KEYS:
        raise ValueError('包含不支持的单元格格式')
    for key in ('font_color', 'bg_color'):
        if key in style and not re.fullmatch(r'#[0-9a-fA-F]{6}', str(style[key])):
            raise ValueError('颜色须为 #RRGGBB')
    if 'font_size' in style and (not isinstance(style['font_size'], (int, float)) or not 1 <= style['font_size'] <= 409):
        raise ValueError('字号无效')
    if 'rotation' in style and (not isinstance(style['rotation'], (int, float)) or not -90 <= style['rotation'] <= 90):
        raise ValueError('文字旋转范围无效')
    if style.get('align', 'general') not in {'general', 'left', 'center', 'right', 'justify'}:
        raise ValueError('水平对齐方式无效')
    if style.get('valign', 'bottom') not in {'top', 'center', 'bottom', 'justify'}:
        raise ValueError('垂直对齐方式无效')
    for key in ('font_name', 'num_format'):
        if key in style and (not isinstance(style[key], str) or len(style[key]) > 255):
            raise ValueError('字体或数字格式过长')
    for key in ('bold', 'italic', 'underline', 'strike', 'text_wrap'):
        if key in style and not isinstance(style[key], bool):
            raise ValueError('格式开关须为布尔值')
    if 'borders' in style:
        if not isinstance(style['borders'], dict) or set(style['borders']) - {'left', 'right', 'top', 'bottom'}:
            raise ValueError('边框方向无效')
        for edge in style['borders'].values():
            if not isinstance(edge, dict) or set(edge) - {'style', 'color'} or edge.get('style') not in {'thin', 'medium', 'thick', 'dashed', 'dotted', 'double', 'hair', 'dashDot', 'dashDotDot', 'mediumDashed', 'mediumDashDot', 'mediumDashDotDot', 'slantDashDot'}:
                raise ValueError('边框样式无效')
            if not re.fullmatch(r'#[0-9a-fA-F]{6}', edge.get('color', '#000000')):
                raise ValueError('边框颜色无效')


def validate_snapshot(raw, *, allow_unsupported=False):
    """Validate before every import, save, candidate application and export."""
    if not isinstance(raw, dict) or raw.get('schema_version') != 1:
        raise ValueError('工作簿数据版本无效')
    if set(raw) - {'schema_version', 'id', 'name', 'date1904', 'sheets'}:
        raise ValueError('工作簿包含未知属性')
    if type(raw.get('date1904')) is not bool:
        raise ValueError('日期系统须为布尔值')
    if not re.fullmatch(r'[a-f0-9]{32}', raw.get('id', '')) or not isinstance(raw.get('name'), str) or not 1 <= len(raw['name']) <= 200:
        raise ValueError('工作簿标识或名称无效')
    sheets = raw.get('sheets')
    if not isinstance(sheets, list) or not 1 <= len(sheets) <= 256:
        raise ValueError('须保留至少一张工作表（最多 256 张）')
    ids, names, count = set(), set(), 0
    for sheet in sheets:
        if not isinstance(sheet, dict) or set(sheet) - {'id', 'name', 'row_count', 'column_count', 'cells', 'rows', 'columns', 'merges', 'freeze', 'filter', 'hidden'}:
            raise ValueError('工作表包含未知属性')
        sid, name = sheet.get('id', ''), sheet_name(sheet.get('name'))
        if not re.fullmatch(r'[a-f0-9]{32}', sid) or sid in ids or name.casefold() in names:
            raise ValueError('工作表名称或标识重复')
        ids.add(sid); names.add(name.casefold())
        for key, limit in [('row_count', MAX_ROWS), ('column_count', MAX_COLS)]:
            if type(sheet.get(key)) is not int or not 1 <= sheet[key] <= limit:
                raise ValueError('工作表行列范围无效')
        cells = sheet.get('cells')
        if not isinstance(cells, dict):
            raise ValueError('单元格数据无效')
        for key, cell in cells.items():
            row, col = position(key)
            if row >= sheet['row_count'] or col >= sheet['column_count']:
                raise ValueError('单元格超出工作表尺寸')
            if not isinstance(cell, dict) or set(cell) - {'value', 'type', 'formula', 'style', 'result_state'}:
                raise ValueError('单元格属性无效')
            if cell.get('type', 'string') not in {'string', 'number', 'boolean', 'date', 'error'}:
                raise ValueError('单元格类型无效')
            value = cell.get('value')
            if value is not None and not isinstance(value, (str, bool, int, float)):
                raise ValueError('单元格只能包含文本、数字、布尔值或空值')
            if isinstance(value, str) and len(value) > 32767:
                raise ValueError('单元格文本超过 Excel 容量')
            if isinstance(value, (float, int)) and not isinstance(value, bool) and not math.isfinite(value):
                raise ValueError('单元格不能包含无穷或 NaN')
            if cell.get('result_state', 'ready') not in {'ready', 'pending', 'error'}:
                raise ValueError('公式结果状态无效')
            if cell.get('type') == 'date' and value is not None and (type(value) not in (int, float) or not -100000 < value < 2958466):
                raise ValueError('日期序列值无效')
            if cell.get('formula'):
                issue = formula_issue(cell['formula'])
                if issue and not allow_unsupported:
                    raise ValueError(issue)
                if cell.get('result_state') == 'ready' and value is None:
                    raise ValueError('公式缺少计算结果，不能标记为已计算')
            if cell.get('style'):
                validate_style(cell['style'])
            if value is not None or cell.get('formula') or cell.get('style'):
                count += 1
                if count > MAX_CELLS:
                    raise ValueError('完整编辑最多支持 200000 个有效单元格，请使用分页预览和全量处理')
        for axis, limit, size in [('rows', MAX_ROWS, 'height'), ('columns', MAX_COLS, 'width')]:
            if not isinstance(sheet.get(axis, {}), dict):
                raise ValueError('行列属性须为字典')
            for key, props in sheet.get(axis, {}).items():
                if not isinstance(props, dict) or not str(key).isdigit() or not 0 <= int(key) < limit or set(props) - {size, 'hidden', 'style'}:
                    raise ValueError('行列属性无效')
                if size in props and (not isinstance(props[size], (int, float)) or not 0 <= props[size] <= 2000):
                    raise ValueError('行高或列宽无效')
                if props.get('style'):
                    validate_style(props['style'])
        merges = sheet.get('merges', [])
        if not isinstance(merges, list) or len(merges) > MAX_CELLS:
            raise ValueError('合并区域无效')
        active = []
        for merge in sorted(merges, key=lambda m: m.get('r0', -1)):
            validate_range(merge)
            if merge['r1'] >= sheet['row_count'] or merge['c1'] >= sheet['column_count']:
                raise ValueError('合并超出工作表尺寸')
            active = [m for m in active if m['r1'] >= merge['r0']]
            if any(m['c0'] <= merge['c1'] and merge['c0'] <= m['c1'] for m in active):
                raise ValueError('合并区域相互重叠')
            active.append(merge)
        freeze = sheet.get('freeze', {})
        if not isinstance(freeze, dict) or set(freeze) - {'row', 'column'} or any(type(v) is not int for v in freeze.values()) or not 0 <= freeze.get('row', 0) < MAX_ROWS or not 0 <= freeze.get('column', 0) < MAX_COLS:
            raise ValueError('冻结位置无效')
        if sheet.get('filter'):
            filters = sheet['filter']
            if not isinstance(filters, dict) or set(filters) - {'range', 'columns', 'hidden_rows'} or 'range' not in filters or not isinstance(filters.get('columns'), list):
                raise ValueError('筛选配置无效')
            validate_range(filters['range'])
            for entry in filters['columns']:
                if not isinstance(entry, dict) or set(entry) != {'column', 'values', 'blank'} or type(entry['column']) is not int or not filters['range']['c0'] <= entry['column'] <= filters['range']['c1'] or not isinstance(entry['values'], list) or any(not isinstance(v, (str, int, float, bool)) for v in entry['values']) or type(entry['blank']) is not bool:
                    raise ValueError('按值筛选条件无效')
            if not isinstance(filters.get('hidden_rows', []), list) or any(type(r) is not int or not filters['range']['r0'] < r <= filters['range']['r1'] for r in filters.get('hidden_rows', [])):
                raise ValueError('筛选隐藏行无效')
    if all(sheet.get('hidden') for sheet in sheets):
        raise ValueError('至少一张工作表必须可见')
    return count


def validate_range(value):
    if not isinstance(value, dict) or set(value) != {'r0', 'c0', 'r1', 'c1'} or any(type(v) is not int for v in value.values()):
        raise ValueError('区域须包含 r0/c0/r1/c1（从 0 开始，含结束位置）')
    if not 0 <= value['r0'] <= value['r1'] < MAX_ROWS or not 0 <= value['c0'] <= value['c1'] < MAX_COLS:
        raise ValueError('区域超出 Excel 范围')


def get_sheet(snapshot, sid):
    return next((s for s in snapshot['sheets'] if s['id'] == sid), None) or _missing_sheet()


def _missing_sheet():
    raise ValueError('工作表不存在')


def invalidate_formulas(snapshot):
    for sheet in snapshot['sheets']:
        for cell in sheet['cells'].values():
            if cell.get('formula'):
                cell['result_state'] = 'pending'


def formula_errors(snapshot):
    errors = []
    from openpyxl.utils import get_column_letter
    for sheet in snapshot['sheets']:
        for key, cell in sheet['cells'].items():
            if cell.get('formula') and (cell.get('result_state') != 'ready' or cell.get('type') == 'error'):
                row, col = position(key)
                errors.append(f"{sheet['name']}!{get_column_letter(col + 1)}{row + 1}：{cell.get('value') if cell.get('result_state') == 'error' else '等待重算'}")
    return errors


def data_copy(snapshot):
    result = copy.deepcopy(snapshot)
    result['id'] = identifier()
    result['name'] = result['name'][:180] + '（纯数据）'
    for sheet in result['sheets']:
        sheet['id'] = identifier()
        sheet.update(merges=[], rows={}, columns={}, filter=None, freeze={'row': 0, 'column': 0})
        for cell in sheet['cells'].values():
            if cell.get('formula') and (cell.get('value') is None or cell.get('result_state') != 'ready'):
                raise ValueError('纯数据提取需要有效公式缓存，请先在 Excel 中重算并保存')
            for key in ('formula', 'result_state', 'style'):
                cell.pop(key, None)
    return result

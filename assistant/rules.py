"""A small typed rule interpreter. Model text never becomes executable code."""
import math
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def number(value):
    if isinstance(value, bool) or value is None or str(value).strip() == '':
        raise ValueError('空值或布尔值不能用于数值计算')
    try:
        result = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError('不是有效数值') from exc
    if not result.is_finite() or abs(result) > Decimal('1e100'):
        raise ValueError('数值超出支持范围')
    return result


def validate_expr(expr, fields, depth=0):
    if depth > 20 or not isinstance(expr, dict):
        raise ValueError('规则结构无效或层级过深')
    if set(expr) == {'field'}:
        if expr['field'] not in fields:
            raise ValueError(f"字段不存在：{expr['field']}")
    elif set(expr) == {'number'}:
        number(expr['number'])
    elif set(expr) == {'op', 'args'}:
        op, args = expr['op'], expr['args']
        if op not in {'add', 'subtract', 'multiply', 'divide', 'round', 'min', 'max', 'abs'} or not isinstance(args, list) or len(args) != (1 if op == 'abs' else 2):
            raise ValueError('仅支持 add/subtract/multiply/divide/round/min/max/abs 结构化运算')
        for arg in args:
            validate_expr(arg, fields, depth + 1)
        if op == 'round' and (set(args[1]) != {'number'} or number(args[1]['number']) != int(number(args[1]['number'])) or not 0 <= int(number(args[1]['number'])) <= 15):
            raise ValueError('round 的第二参数须为 0–15 的固定整数')
    else:
        raise ValueError('表达式只允许 field、number 或 op/args')


def evaluate(expr, row):
    if 'field' in expr:
        return number(row[expr['field']])
    if 'number' in expr:
        return number(expr['number'])
    values = [evaluate(arg, row) for arg in expr['args']]
    a, op = values[0], expr['op']
    b = values[-1]
    if op == 'add': result = a + b
    elif op == 'subtract': result = a - b
    elif op == 'multiply': result = a * b
    elif op == 'divide':
        if b == 0:
            raise ValueError('除数为零')
        result = a / b
    elif op == 'round': result = a.quantize(Decimal(1).scaleb(-int(b)), rounding=ROUND_HALF_UP)
    elif op == 'min': result = min(a, b)
    elif op == 'max': result = max(a, b)
    else: result = abs(a)
    if not result.is_finite() or abs(result) > Decimal('1e100'):
        raise ValueError('计算结果超出支持范围')
    return result


def validate_condition(condition, fields, depth=0):
    if depth > 20 or not isinstance(condition, dict):
        raise ValueError('条件结构无效或层级过深')
    if set(condition) in ({'all'}, {'any'}):
        items = next(iter(condition.values()))
        if not isinstance(items, list) or not 1 <= len(items) <= 20:
            raise ValueError('组合条件需要 1–20 个子条件')
        for item in items:
            validate_condition(item, fields, depth + 1)
    elif set(condition) == {'field', 'operator', 'value'}:
        if condition['field'] not in fields or condition['operator'] not in {'eq', 'ne', 'gt', 'ge', 'lt', 'le'}:
            raise ValueError('条件字段或比较方式无效')
        if condition['operator'] in {'gt', 'ge', 'lt', 'le'}:
            number(condition['value'])
        elif not isinstance(condition['value'], (str, int, float, bool)):
            raise ValueError('比较值须为文本或数字')
    else:
        raise ValueError('条件仅允许 all/any 或 field/operator/value')


def matches(condition, row):
    if 'all' in condition:
        return all(matches(c, row) for c in condition['all'])
    if 'any' in condition:
        return any(matches(c, row) for c in condition['any'])
    a, b, op = row[condition['field']], condition['value'], condition['operator']
    if a is None or str(a).strip() == '':
        raise ValueError('分级依据为空')
    if op not in {'eq', 'ne'} or isinstance(b, (int, float)) and not isinstance(b, bool):
        a, b = number(a), number(b)
    return {'eq': lambda: a == b, 'ne': lambda: a != b, 'gt': lambda: a > b, 'ge': lambda: a >= b, 'lt': lambda: a < b, 'le': lambda: a <= b}[op]()


def transform(frame, kind, params):
    from .tables import SOURCE
    definitions = params.get('columns')
    if set(params) != {'columns'} or not isinstance(definitions, list) or not 1 <= len(definitions) <= 100:
        raise ValueError('请指定 1–100 个新增列规则：columns 数组')
    fields, new_names = set(frame.columns), set()
    for item in definitions:
        allowed = {'name', 'expression'} if kind == 'calculate' else {'name', 'rules', 'default'}
        if not isinstance(item, dict) or set(item) != allowed:
            raise ValueError('新增列规则字段无效')
        name = item['name']
        if not isinstance(name, str) or not name.strip() or len(name) > 200 or name in fields | new_names or name.startswith('__source_'):
            raise ValueError('新增字段为空、重复或与原字段冲突')
        new_names.add(name)
        if kind == 'calculate':
            validate_expr(item['expression'], fields)
        else:
            if not isinstance(item['rules'], list) or not 1 <= len(item['rules']) <= 100 or not isinstance(item['default'], str):
                raise ValueError('分级需要 rules 数组及文本 default')
            for rule in item['rules']:
                if set(rule) != {'when', 'label'} or not isinstance(rule['label'], str):
                    raise ValueError('分级规则需要 when 条件与 label 文本')
                validate_condition(rule['when'], fields)
    result, issues = frame.copy(), []
    # Iterate each row once and retain even invalid rows; no eval/exec/compiled expressions.
    output = {item['name']: [] for item in definitions}
    for values in frame.itertuples(index=False, name=None):
        row = dict(zip(frame.columns, values))
        for item in definitions:
            try:
                if kind == 'calculate':
                    value = float(evaluate(item['expression'], row))
                else:
                    value = next((r['label'] for r in item['rules'] if matches(r['when'], row)), item['default'])
                output[item['name']].append(value)
            except (ValueError, ArithmeticError) as exc:
                output[item['name']].append(None)
                issues.append({**{k: row.get(k) for k in SOURCE}, '字段': item['name'], '原因': str(exc)})
    for name, values in output.items():
        result[name] = values
    return result, issues

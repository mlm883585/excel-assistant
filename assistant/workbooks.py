"""Transactional local workbook drafts, immutable revisions and reviewed candidates."""
import copy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import zlib

from .workbook_model import blank_workbook, data_copy, identifier, validate_snapshot, get_sheet, validate_range
from .workbook_excel import import_workbook, export_workbook


def packed(value):
    return zlib.compress(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode(), 3)


def unpacked(value):
    return json.loads(zlib.decompress(value))


class Workbooks:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS workbooks(task TEXT, id TEXT, revision INTEGER NOT NULL, source TEXT, limitations TEXT NOT NULL, PRIMARY KEY(task,id));
                CREATE TABLE IF NOT EXISTS workbook_versions(task TEXT, book TEXT, revision INTEGER, kind TEXT, snapshot BLOB NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(task,book,revision));
                CREATE TABLE IF NOT EXISTS output_reviews(task TEXT, id TEXT, book TEXT, base INTEGER, snapshot BLOB, summary TEXT NOT NULL, applied_book TEXT, applied_revision INTEGER, exported_revision INTEGER, PRIMARY KEY(task,id));
                CREATE TABLE IF NOT EXISTS output_changes(task TEXT, output TEXT, seq INTEGER, body TEXT NOT NULL, PRIMARY KEY(task,output,seq));
                CREATE TABLE IF NOT EXISTS workbook_exports(task TEXT, book TEXT, revision INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP);
            ''')
            # Serialize inspection and ALTER together: parallel review/list RPCs may
            # initialize the same older task database on their first request.
            db.execute('BEGIN IMMEDIATE')
            if 'name' not in [r[1] for r in db.execute('PRAGMA table_info(workbooks)')]:
                db.execute('ALTER TABLE workbooks ADD COLUMN name TEXT')
            columns = [r[1] for r in db.execute('PRAGMA table_info(output_reviews)')]
            if 'run_id' not in columns:
                db.execute('ALTER TABLE output_reviews ADD COLUMN run_id TEXT')
            if 'state' not in columns:
                db.execute("ALTER TABLE output_reviews ADD COLUMN state TEXT NOT NULL DEFAULT 'ready'")

    def idle(self, task):
        if self.store.get(task)['status'] in {'running', 'waiting'}:
            raise ValueError('处理期间工作簿只读，请等待完成或取消任务')

    def list(self, task):
        self.store.get(task)
        with self.store.connect() as db:
            rows = db.execute('SELECT id,revision,source,limitations,name FROM workbooks WHERE task=? ORDER BY rowid', (task,)).fetchall()
        return [{'id': r[0], 'revision': r[1], 'source': r[2], 'limitations': json.loads(r[3]), 'name': r[4] or self.load(task,r[0])['snapshot']['name']} for r in rows]

    def open(self, task, workbook_id=None, file_id=None, pure_data=False, revision=None):
        self.store.get(task)
        if workbook_id:
            record = self.load(task, workbook_id, revision)
            if revision is not None:
                record.update(readonly=True, historical=True)
            return record
        if revision is not None:
            raise ValueError('查看历史版本必须指定工作簿')
        self.idle(task)
        if file_id and not pure_data:
            with self.store.connect() as db:
                row = db.execute('SELECT id FROM workbooks WHERE task=? AND source=?', (task, file_id)).fetchone()
            if row:
                return self.load(task, row[0])
        if file_id:
            path, info = self.store.resolve_file(task, file_id)
            snapshot, limitations = import_workbook(path, info['name'])
            if pure_data:
                snapshot, limitations = data_copy(snapshot), []
        else:
            snapshot, limitations = blank_workbook(), []
        self._insert(task, snapshot, 'import' if file_id else 'create', file_id if not pure_data else None, limitations)
        return self.load(task, snapshot['id'])

    def _insert(self, task, snapshot, kind, source=None, limitations=None, db=None):
        validate_snapshot(snapshot, allow_unsupported=bool(limitations))
        if db is None:
            with self.store.connect() as conn:
                return self._insert(task, snapshot, kind, source, limitations, conn)
        db.execute('INSERT INTO workbooks(task,id,revision,source,limitations,name) VALUES(?,?,?,?,?,?)', (task, snapshot['id'], 1, source, json.dumps(limitations or [], ensure_ascii=False), snapshot['name']))
        db.execute('INSERT INTO workbook_versions(task,book,revision,kind,snapshot) VALUES(?,?,?,?,?)', (task, snapshot['id'], 1, kind, packed(snapshot)))

    def load(self, task, workbook_id, revision=None):
        self.store.get(task)
        with self.store.connect() as db:
            meta = db.execute('SELECT revision,source,limitations FROM workbooks WHERE task=? AND id=?', (task, workbook_id)).fetchone()
            if not meta:
                raise ValueError('工作簿不属于当前任务')
            number = meta[0] if revision is None else revision
            row = db.execute('SELECT snapshot,kind,created FROM workbook_versions WHERE task=? AND book=? AND revision=?', (task, workbook_id, number)).fetchone()
        if not row:
            raise ValueError('工作簿版本不存在')
        issues = json.loads(meta[2])
        return {'snapshot': unpacked(row[0]), 'revision': number, 'current_revision': meta[0], 'source': meta[1], 'limitations': issues, 'readonly': bool(issues), 'kind': row[1], 'created': row[2]}

    def _save(self, db, task, snapshot, expected_version, kind='draft'):
        count = validate_snapshot(snapshot)
        changed = db.execute('UPDATE workbooks SET revision=revision+1,name=? WHERE task=? AND id=? AND revision=? AND limitations=?', (snapshot['name'], task, snapshot['id'], expected_version, '[]'))
        if changed.rowcount != 1:
            raise ValueError('版本冲突或只读工作簿：请重新打开，当前修改尚未保存')
        version = expected_version + 1
        db.execute('INSERT INTO workbook_versions(task,book,revision,kind,snapshot) VALUES(?,?,?,?,?)', (task, snapshot['id'], version, kind, packed(snapshot)))
        return {'revision': version, 'cell_count': count}

    def save(self, task, snapshot, expected_version, kind='draft'):
        self.idle(task)
        with self.store.connect() as db:
            return self._save(db, task, snapshot, expected_version, kind)

    def versions(self, task, workbook_id, offset=0, limit=50):
        self.load(task, workbook_id)
        if offset < 0 or not 1 <= limit <= 200:
            raise ValueError('版本分页无效')
        with self.store.connect() as db:
            rows = db.execute('SELECT revision,kind,created FROM workbook_versions WHERE task=? AND book=? ORDER BY revision DESC LIMIT ? OFFSET ?', (task, workbook_id, limit, offset)).fetchall()
        return [{'revision': r[0], 'kind': r[1], 'created': r[2]} for r in rows]

    def restore(self, task, workbook_id, revision, expected_version):
        snapshot = self.load(task, workbook_id, revision)['snapshot']
        self.save(task, snapshot, expected_version, 'restore')
        return self.load(task, workbook_id)

    def undo(self, task, workbook_id, expected_version):
        record = self.load(task, workbook_id, expected_version)
        if record['current_revision'] != expected_version:
            raise ValueError('工作簿已改变，请重新核对')
        if record['current_revision'] <= 1:
            raise ValueError('已是初始版本，无法撤销')
        return self.restore(task, workbook_id, record['current_revision'] - 1, expected_version)

    def input(self, task, selection):
        """Fixed-revision input; its immutable snapshot also provides source coordinates."""
        record = self.load(task, selection.workbook_id, selection.version)
        if record['current_revision'] != selection.version:
            raise ValueError('输入工作簿版本已过期，请刷新选区')
        sheet = get_sheet(record['snapshot'], selection.sheet_id)
        area = selection.range
        if area is None:
            populated = [tuple(map(int, k.split(','))) for k, c in sheet['cells'].items() if c.get('value') is not None or c.get('formula')]
            if not populated:
                raise ValueError('所选工作表没有数据')
            area = {'r0': 0, 'c0': 0, 'r1': max(p[0] for p in populated), 'c1': max(p[1] for p in populated)}
        validate_range(area)
        if (area['r1']-area['r0']+1)*(area['c1']-area['c0']+1) > 2_000_000:
            raise ValueError('所选区域过大，请缩小到实际数据范围')
        rows = []
        for r in range(area['r0'], area['r1'] + 1):
            row = []
            for c in range(area['c0'], area['c1'] + 1):
                cell = sheet['cells'].get(f'{r},{c}', {})
                if cell.get('formula') and cell.get('result_state') != 'ready':
                    raise ValueError(f"{sheet['name']} 行 {r+1} 列 {c+1} 公式尚未成功计算")
                value = cell.get('value')
                fmt = cell.get('style', {}).get('num_format', '')
                if isinstance(value, (int, float)) and len(fmt) > 1 and set(fmt) == {'0'} and int(value) == value:
                    value = str(int(value)).zfill(len(fmt))
                row.append('' if value is None else value)
            rows.append(row)
        return rows, {'name': record['snapshot']['name'], 'sheet': sheet['name'], 'row_offset': area['r0'], 'area': area, 'snapshot': record['snapshot']}

    def candidate(self, task, output_id, snapshot, base=None, summary=None, changes=None):
        """Worker-only preparation. Approval and export are deliberately separate UI APIs."""
        if snapshot is not None:
            validate_snapshot(snapshot)
        summary = {**(summary or {}), 'can_edit': snapshot is not None}
        if changes is None:
            before = self.load(task, base['id'], base['revision'])['snapshot'] if base else None
            changes = workbook_changes(before, snapshot)
        with self.store.connect() as db:
            record = self.store.get(task)
            run_id = record.get('run_id') if record['status'] in {'running', 'waiting'} else None
            db.execute('INSERT INTO output_reviews(task,id,book,base,snapshot,summary,run_id,state) VALUES(?,?,?,?,?,?,?,?)', (task, output_id, base['id'] if base else None, base['revision'] if base else None, packed(snapshot) if snapshot else None, '{}', run_id, 'pending' if run_id else 'ready'))
            count, kinds = 0, {}
            for count, change in enumerate(changes, 1):
                kinds[change['kind']] = kinds.get(change['kind'], 0) + 1
                db.execute('INSERT INTO output_changes VALUES(?,?,?,?)', (task, output_id, count, json.dumps(change, ensure_ascii=False, default=str, allow_nan=False)))
            summary.update(total=count, counts=kinds, base=base)
            db.execute('UPDATE output_reviews SET summary=? WHERE task=? AND id=?', (json.dumps(summary, ensure_ascii=False), task, output_id))

    def review(self, task, output_id):
        self.store.get(task)
        with self.store.connect() as db:
            row = db.execute('SELECT summary,applied_book,applied_revision,exported_revision,state FROM output_reviews WHERE task=? AND id=?', (task, output_id)).fetchone()
        if not row:
            return {'legacy': True, 'message': '此结果没有差异记录，请通过分页预览核对完整结果。'}
        current = self.load(task,row[1])['revision'] if row[1] else None
        return {**json.loads(row[0]), 'applied_book': row[1], 'applied_revision': row[2], 'exported_revision': row[3], 'export_valid': bool(row[3] and row[3] == current), 'state': row[4]}

    def changes(self, task, output_id, offset=0, limit=50):
        if offset < 0 or not 1 <= limit <= 200:
            raise ValueError('差异分页无效，最多 200 条')
        summary = self.review(task, output_id)
        with self.store.connect() as db:
            rows = db.execute('SELECT seq,body FROM output_changes WHERE task=? AND output=? AND seq>? ORDER BY seq LIMIT ?', (task, output_id, offset, limit)).fetchall()
        return {'total': summary.get('total', 0), 'items': [{'id':r[0],**json.loads(r[1])} for r in rows]}

    def apply(self, task, output_id):
        self.idle(task)
        if self.store.get(task)['status'] in {'failed', 'cancelled'}:
            raise ValueError('本次任务失败或已取消，请重新生成完整候选结果')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT book,base,snapshot,applied_book,applied_revision,state FROM output_reviews WHERE task=? AND id=?', (task, output_id)).fetchone()
            if not row or row[2] is None:
                raise ValueError('此结果只能全量处理和分页核对，无法进入完整编辑')
            if row[5] != 'ready':
                raise ValueError('此候选所属执行尚未成功或已取消，不能采用')
            if row[3]:
                raise ValueError('该候选已经采用，请打开已采用工作簿')
            snapshot = unpacked(row[2])
            if row[0]:
                snapshot['id'] = row[0]
                version = self._save(db, task, snapshot, row[1], 'apply')['revision']
            else:
                self._insert(task, snapshot, 'apply', db=db)
                version = 1
            db.execute('UPDATE output_reviews SET applied_book=?,applied_revision=? WHERE task=? AND id=?', (snapshot['id'], version, task, output_id))
        return self.load(task, snapshot['id'])

    def export(self, task, workbook_id, expected_version, target, output_id=None):
        self.idle(task)
        record = self.load(task, workbook_id, expected_version)
        if record['current_revision'] != expected_version or record['readonly']:
            raise ValueError('确认版本已失效或工作簿只读，请重新核对')
        target = Path(target).resolve()
        if target.suffix.lower() != '.xlsx':
            raise ValueError('输出文件须使用 .xlsx 扩展名')
        # Always a new file, including compared with all task originals and outputs.
        if target.exists():
            raise ValueError('请使用新文件名另存，避免覆盖已有文件')
        handle, temporary = tempfile.mkstemp(prefix='.workbook-', suffix='.xlsx', dir=target.parent)
        os.close(handle)
        created = False
        try:
            export_workbook(record['snapshot'], Path(temporary))
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                current = db.execute('SELECT revision FROM workbooks WHERE task=? AND id=?', (task, workbook_id)).fetchone()
                if not current or current[0] != expected_version:
                    raise ValueError('导出时工作簿已改变，请重新核对')
                # Exclusive destination creation avoids replacing a file created during calculation.
                with open(temporary, 'rb') as src, open(target, 'xb') as dst:
                    created = True
                    import shutil
                    shutil.copyfileobj(src, dst)
                    dst.flush(); os.fsync(dst.fileno())
                db.execute('INSERT INTO workbook_exports(task,book,revision) VALUES(?,?,?)', (task, workbook_id, expected_version))
                if output_id:
                    db.execute('UPDATE output_reviews SET exported_revision=? WHERE task=? AND id=? AND applied_book=?', (expected_version, task, output_id, workbook_id))
            return {'exported': True, 'revision': expected_version, 'name': target.name}
        except BaseException:
            # A partially written new destination must not be mistaken for a successful export.
            if created:
                target.unlink()
            raise
        finally:
            Path(temporary).unlink(missing_ok=True)


def workbook_changes(before, after):
    if after is None:
        return
    old = {s['id']: s for s in (before or {}).get('sheets', [])}
    new = {s['id']: s for s in after['sheets']}
    if list(old) != list(new):
        yield {'kind': 'structure', 'location': '工作表顺序', 'old': [s['name'] for s in old.values()], 'new': [s['name'] for s in new.values()]}
    for sid in dict.fromkeys([*old, *new]):
        a, b = old.get(sid, {}), new.get(sid, {})
        label = b.get('name', a.get('name'))
        for prop in ('name', 'row_count', 'column_count', 'rows', 'columns', 'merges', 'freeze', 'filter', 'hidden'):
            if a.get(prop) != b.get(prop):
                yield {'kind': 'structure', 'location': label, 'property': prop, 'old': a.get(prop), 'new': b.get(prop)}
        for key in sorted(set(a.get('cells', {})) | set(b.get('cells', {})), key=lambda k: tuple(map(int, k.split(',')))):
            ca, cb = a.get('cells', {}).get(key, {}), b.get('cells', {}).get(key, {})
            for prop in ('value', 'formula', 'style', 'type'):
                if ca.get(prop) != cb.get(prop):
                    r, c = map(int, key.split(','))
                    from openpyxl.utils import get_column_letter
                    yield {'kind': 'format' if prop == 'style' else prop, 'location': f'{label}!{get_column_letter(c+1)}{r+1}', 'old': ca.get(prop), 'new': cb.get(prop)}

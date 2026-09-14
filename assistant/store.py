import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import uuid
from contextlib import contextmanager


def data_root() -> Path:
    return Path(os.environ.get("EXCEL_ASSISTANT_HOME", str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ExcelAssistant")))


class Store:
    def __init__(self, root: Path | None = None):
        self.root = (root or data_root()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, body TEXT NOT NULL, updated TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, task TEXT NOT NULL, body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_task_id ON events(task, id);
                CREATE INDEX IF NOT EXISTS tasks_updated_id ON tasks(updated DESC, id DESC);
                CREATE TABLE IF NOT EXISTS recipes(id TEXT PRIMARY KEY, body TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / "tasks.sqlite", timeout=30)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            with db:
                yield db
        finally:
            db.close()

    def directory(self, task: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", task):
            raise ValueError("任务标识无效")
        path = self.root / "tasks" / task
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create(self):
        task = {"id": uuid.uuid4().hex, "status": "pending", "files": [], "outputs": [], "plan": None, "session_id": None, "error": None}
        self.save(task)
        return task

    def save(self, task):
        with self.connect() as db:
            db.execute("INSERT INTO tasks(id,body) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body, updated=CURRENT_TIMESTAMP", (task["id"], json.dumps(task, ensure_ascii=False)))

    def get(self, task):
        self.directory(task)
        with self.connect() as db:
            row = db.execute("SELECT body FROM tasks WHERE id=?", (task,)).fetchone()
        if not row:
            raise ValueError("任务不存在")
        return json.loads(row[0])

    def list(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM tasks ORDER BY updated DESC LIMIT 100")]

    def event(self, task, kind, data):
        with self.connect() as db:
            db.execute("INSERT INTO events(task,body) VALUES(?,?)", (task, json.dumps({"kind": kind, "data": data}, ensure_ascii=False)))

    def finish_reviews(self, task, success):
        run_id = self.get(task).get('run_id')
        if not run_id:
            return
        with self.connect() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='output_reviews'").fetchone():
                db.execute('UPDATE output_reviews SET state=? WHERE task=? AND run_id=?', ('ready' if success else 'invalid', task, run_id))

    def summaries(self, offset=0, limit=30):
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError('任务分页范围无效')
        with self.connect() as db:
            rows = db.execute("SELECT id, json_extract(body,'$.status'), json_extract(body,'$.files[0].name'), updated FROM tasks ORDER BY updated DESC, id DESC LIMIT ? OFFSET ?", (limit + 1, offset)).fetchall()
        return {'items': [{'id': r[0], 'status': r[1], 'name': r[2] or '新任务', 'updated': r[3]} for r in rows[:limit]], 'has_more': len(rows) > limit}

    def event_page(self, task, before=None, limit=200):
        if not 1 <= limit <= 200:
            raise ValueError('消息分页范围无效')
        with self.connect() as db:
            rows = db.execute('SELECT id,body FROM events WHERE task=? AND id<? ORDER BY id DESC LIMIT ?', (task, before if before is not None else 9223372036854775807, limit + 1)).fetchall()
        return {'items': [{'id': row[0], **json.loads(row[1])} for row in reversed(rows[:limit])], 'has_more': len(rows) > limit}

    def events(self, task, after=0):
        with self.connect() as db:
            return [{"id": row[0], **json.loads(row[1])} for row in db.execute("SELECT id,body FROM events WHERE task=? AND id>? ORDER BY id LIMIT 200", (task, after))]

    def import_file(self, task_id, source):
        task = self.get(task_id)
        if task["status"] in {"running", "waiting"}:
            raise ValueError("请先结束当前任务再添加文件")
        if len(task["files"]) >= 10:
            raise ValueError("每个任务最多导入 10 个文件")
        source = Path(source).resolve(strict=True)
        if source.suffix.lower() not in {".xlsx", ".xls", ".csv"}:
            raise ValueError("首版支持 xlsx、xls、csv；含宏文件暂不支持")
        file_id = uuid.uuid4().hex
        folder = self.directory(task_id) / "inputs"
        folder.mkdir(exist_ok=True)
        target = folder / (file_id + source.suffix.lower())
        shutil.copyfile(source, target)
        info = {"id": file_id, "name": source.name, "relative": str(target.relative_to(self.directory(task_id)))}
        task["files"].append(info)
        self.save(task)
        return info

    def resolve_file(self, task_id, file_id):
        task = self.get(task_id)
        for file in task["files"] + task["outputs"]:
            if file["id"] == file_id:
                root = self.directory(task_id).resolve()
                path = (root / file["relative"]).resolve(strict=True)
                if not path.is_relative_to(root) or path.is_symlink():
                    raise ValueError("文件不在任务范围内")
                return path, file
        raise ValueError("文件未导入此任务")

    def save_recipe(self, task_id, name):
        task = self.get(task_id)
        if task["status"] != "succeeded" or not task.get("plan"):
            raise ValueError("仅可保存已成功执行的操作规则")
        slots = {f["id"]: i for i, f in enumerate(task["files"])}
        plan = json.loads(json.dumps(task["plan"]))
        recipe_files = task['files'] if any(step['inputs'] for step in plan['steps']) else []
        for step in plan["steps"]:
            if step['kind'] == 'edit_workbook' or any(item.get('workbook_id') for item in step['inputs']):
                raise ValueError('手动编辑及工作簿选区流程暂不能保存为输入槽位规则')
            for item in step["inputs"]:
                if item["file_id"] not in slots:
                    raise ValueError("暂不能保存引用中间文件的规则，请使用原始输入")
                item["file_id"] = f"slot:{slots[item['file_id']]}"
        recipe = {"id": uuid.uuid4().hex, "name": name[:100], "plan": plan, "slots": [f["name"] for f in recipe_files]}
        with self.connect() as db:
            db.execute("INSERT INTO recipes VALUES(?,?)", (recipe["id"], json.dumps(recipe, ensure_ascii=False)))
        return recipe

    def recipes(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM recipes")]

    def recipe_plan(self, recipe_id, task_id):
        recipe = next((r for r in self.recipes() if r["id"] == recipe_id), None)
        if not recipe:
            raise ValueError("规则不存在")
        files = self.get(task_id)["files"]
        if recipe['slots'] and len(files) != len(recipe["slots"]):
            raise ValueError("文件数量与规则输入槽位不一致，请按原顺序导入替换文件")
        for step in recipe["plan"]["steps"]:
            for item in step["inputs"]:
                item["file_id"] = files[int(item["file_id"].split(":")[1])]["id"]
        return recipe["plan"]

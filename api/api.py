import json
import os
from pathlib import Path
import sys
import threading

from ppx_py import api_method, BridgeError
from assistant.store import Store
from assistant.jobs import Jobs
from assistant.tables import overview, preview

_store = None
_jobs = None
_lock = threading.Lock()


def services():
    global _store, _jobs
    with _lock:
        if _store is None:
            _store = Store()
            _jobs = Jobs(_store)
    return _store, _jobs


def guarded(function):
    from functools import wraps
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (ValueError, OSError, KeyError) as exc:
            raise BridgeError("TASK_ERROR", str(exc)) from exc
    return call


@api_method("tasks.create")
@guarded
def create():
    return services()[0].create()


@api_method("tasks.list")
def list_tasks():
    return services()[0].list()


@api_method("tasks.get")
@guarded
def get_task(task_id: str, after: int = 0):
    store, _ = services()
    return {"task": store.get(task_id), "events": store.events(task_id, after)}


@api_method("files.choose")
@guarded
def choose(task_id: str):
    import webview
    paths = webview.windows[0].create_file_dialog(webview.OPEN_DIALOG, allow_multiple=True, file_types=("Excel 与 CSV (*.xlsx;*.xls;*.csv)",))
    store, _ = services()
    return [store.import_file(task_id, path) for path in (paths or [])]


@api_method("files.inspect")
@guarded
def inspect(task_id: str, file_id: str):
    store, _ = services()
    path, _ = store.resolve_file(task_id, file_id)
    return overview(path)


@api_method("files.preview")
@guarded
def preview_file(task_id: str, selection: dict, offset: int = 0, limit: int = 50):
    return preview(services()[0], task_id, selection, offset, limit)


@api_method("files.open")
@guarded
def open_file(task_id: str, file_id: str):
    path, _ = services()[0].resolve_file(task_id, file_id)
    os.startfile(path)
    return True


@api_method("tasks.execute")
@guarded
def execute(task_id: str, plan: dict):
    return services()[1].start(task_id, plan=plan)


def config_path():
    return services()[0].root / "model.json"


@api_method("settings.get")
def settings_get():
    path = config_path()
    root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    cli = root / "node_modules/@qwen-code/qwen-code/cli.js"
    defaults = {"base_url": "", "model": "", "cli": str(cli), "node_dir": str(root / "runtime"), "python": sys.executable}
    return {**defaults, **(json.loads(path.read_text(encoding="utf-8")) if path.exists() else {})}


@api_method("settings.save")
@guarded
def settings_save(base_url: str, model: str):
    from urllib.parse import urlparse
    if urlparse(base_url).scheme not in {"http", "https"} or not urlparse(base_url).hostname:
        raise ValueError("请输入内网 HTTP(S) 模型地址")
    config = {"base_url":base_url.rstrip("/"), "model":model.strip()}
    config_path().write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return True


@api_method("tasks.agent")
@guarded
def agent(task_id: str, prompt: str, selections: list[dict]):
    if not prompt.strip() or len(prompt) > 20000:
        raise ValueError("请输入有效任务要求")
    from assistant.models import InputSelection
    from assistant.agent import AgentRunner
    store, jobs = services()
    for item in selections:
        selection = InputSelection.model_validate(item)
        store.resolve_file(task_id, selection.file_id)
    config = settings_get()
    AgentRunner(store, task_id, config).options()
    request = prompt + "\n用户选定的输入与表头：" + json.dumps(selections, ensure_ascii=False)
    store.event(task_id, "user", prompt)
    return jobs.start(task_id, prompt=request, config=config)


@api_method("tasks.answer")
@guarded
def answer(task_id: str, answers: dict):
    store, _ = services()
    if store.get(task_id)["status"] != "waiting":
        raise ValueError("当前任务没有等待回答")
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in answers.items()):
        raise ValueError("回答格式不正确")
    folder = store.directory(task_id)
    temp = folder / "answer.tmp"
    temp.write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
    temp.replace(folder / "answer.json")
    return True


@api_method("tasks.cancel")
@guarded
def cancel(task_id: str):
    return services()[1].cancel(task_id)


@api_method("recipes.save")
@guarded
def save_recipe(task_id: str, name: str):
    return services()[0].save_recipe(task_id, name)


@api_method("recipes.list")
def recipes():
    return services()[0].recipes()


@api_method("recipes.apply")
@guarded
def apply_recipe(task_id: str, recipe_id: str):
    store, jobs = services()
    return jobs.start(task_id, plan=store.recipe_plan(recipe_id, task_id))

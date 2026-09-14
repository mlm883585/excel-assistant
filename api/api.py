import json
import os
from pathlib import Path
import sys
import threading

from ppx_py import api_method, BridgeError
from assistant.store import Store, data_root

_store = None
_jobs = None
_lock = threading.RLock()
_environment = None


def services():
    global _store, _jobs
    with _lock:
        if _store is None:
            from assistant.jobs import Jobs
            store = Store()
            jobs = Jobs(store)
            _store, _jobs = store, jobs
    return _store, _jobs


def guarded(function):
    from functools import wraps
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ImportError as exc:
            raise BridgeError('DEPENDENCY_MISSING', '业务依赖无法加载，请打开环境检测；客户请重新解压完整交付包') from exc
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
    from assistant.tables import overview
    store, _ = services()
    path, _ = store.resolve_file(task_id, file_id)
    return overview(path)


@api_method("files.preview")
@guarded
def preview_file(task_id: str, selection: dict, offset: int = 0, limit: int = 50):
    from assistant.tables import preview
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
    with _lock:
        check_execution(plan)
        return services()[1].start(task_id, plan=plan)


def config_path():
    return data_root() / "model.json"


@api_method("settings.get")
def settings_get():
    path = config_path()
    raw = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    return {key: raw.get(key, '') for key in ['base_url', 'model']}


@api_method("settings.save")
@guarded
def settings_save(base_url: str, model: str):
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("请输入内网 HTTP(S) 模型地址")
    if not model.strip():
        raise ValueError('请输入实际 model 标识')
    config = {"base_url":base_url.rstrip("/"), "model":model.strip()}
    config_path().parent.mkdir(parents=True, exist_ok=True)
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
    with _lock:
        check_execution()
        selected = environment().runtime.selected()
        config = {**settings_get(), 'cli': selected['cli'], 'node_executable': selected['node_executable'], 'runtime_fingerprint': selected['fingerprint']}
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
    with _lock:
        plan = store.recipe_plan(recipe_id, task_id)
        check_execution(plan)
        return jobs.start(task_id, plan=plan)


def environment():
    global _environment
    with _lock:
        if _environment is None:
            from assistant.runtime import RuntimeManager
            from assistant.environment_service import EnvironmentService
            _environment = EnvironmentService(RuntimeManager(data_root()))
            _environment.on_select = runtime_select
        return _environment


def check_execution(plan=None):
    from assistant.diagnostics import require_storage, excel_installed
    require_storage()
    service = environment()
    if service.installing:
        raise ValueError('环境安装进行中，请完成后再执行任务')
    if plan and any(s.get('kind') == 'recalculate' for s in plan.get('steps', [])):
        if not excel_installed() or service.results.get('excel', {}).get('status') == 'fail':
            raise ValueError('Excel 原生重算不可用，请在环境检测中完成 Excel 测试')


def ensure_idle():
    if _jobs and any(p.is_alive() for p in _jobs.processes.values()):
        raise ValueError('任务正在执行，请结束后再切换或修复运行环境')


@api_method('runtime.status')
@guarded
def runtime_status():
    from assistant.diagnostics import excel_installed
    service = environment()
    try:
        selected = service.runtime.selected()
        status = {'ready': True, 'selected': selected, 'message': '运行环境已验证'}
    except ValueError as exc:
        status = {'ready': False, 'selected': None, 'message': str(exc)}
    status['first_use'] = not service.runtime.path.exists()
    status['excel_ready'] = excel_installed() and service.results.get('excel', {}).get('status') != 'fail'
    return status


@api_method('runtime.discover')
@guarded
def runtime_discover():
    return environment().runtime.discover()


@api_method('runtime.choose')
@guarded
def runtime_choose():
    import webview
    paths = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
    return environment().runtime.discover(paths[0]) if paths else []


@api_method('runtime.automatic')
@guarded
def runtime_automatic():
    with _lock:
        ensure_idle()
        path = config_path()
        raw = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        return environment().automatic(raw.get('cli'))


@api_method('runtime.validate')
@guarded
def runtime_validate(candidate_id: str):
    return environment().validate(candidate_id)


@api_method('runtime.select')
@guarded
def runtime_select(candidate_id: str):
    with _lock:
        ensure_idle()
        return environment().runtime.select(candidate_id)


@api_method('diagnostics.check')
@guarded
def diagnostics_check(kind: str):
    return environment().check(kind, settings_get() if kind == 'model' else None)


@api_method('diagnostics.get')
@guarded
def diagnostics_get(run_id: str):
    return environment().get(run_id)


@api_method('diagnostics.cancel')
@guarded
def diagnostics_cancel(run_id: str):
    return environment().cancel(run_id)


@api_method('diagnostics.export')
@guarded
def diagnostics_export():
    import webview
    safe, explanation = environment().export()
    paths = webview.windows[0].create_file_dialog(webview.SAVE_DIALOG, save_filename='环境检测报告.json', file_types=('JSON (*.json)',))
    if not paths:
        return False
    target = Path(paths if isinstance(paths, str) else paths[0])
    # One file avoids silently overwriting a second, unapproved sibling file.
    target.write_text(json.dumps({**safe, '说明': explanation}, ensure_ascii=False, indent=2), encoding='utf-8')
    return True


@api_method('diagnostics.install_webview')
@guarded
def diagnostics_install():
    from assistant.runtime import app_root
    from assistant.windows_repair import install_webview
    from assistant.diagnostics import platform_checks, report
    def install(stop):
        result = install_webview(app_root())
        return {**result, 'checks': platform_checks()}
    with _lock:
        ensure_idle()
        return environment().start('install', install)


def shutdown():
    if _environment:
        _environment.close()
    if _jobs:
        _jobs.close()

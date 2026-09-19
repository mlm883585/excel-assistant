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
_previews = None
_scheduler = None
_app_version = ""


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


@api_method('tasks.summaries')
@guarded
def task_summaries(offset: int = 0, limit: int = 30):
    return services()[0].summaries(offset, limit)


@api_method('tasks.events')
@guarded
def task_events(task_id: str, before: int | None = None, limit: int = 200):
    return services()[0].event_page(task_id, before, limit)


def previews():
    global _previews
    with _lock:
        if _previews is None:
            from assistant.preview import PreviewService
            _previews = PreviewService(services()[0])
        return _previews


@api_method('files.preview_start')
@guarded
def preview_start(task_id: str, selection: dict):
    with _lock:
        if _jobs and any(p.is_alive() for p in _jobs.processes.values()):
            return {'state': 'busy', 'retry_after_ms': 500}
        return previews().start(task_id, selection)


@api_method('files.preview_page')
@guarded
def preview_page(preview_id: str, offset: int = 0, limit: int = 50):
    return previews().page(preview_id, offset, limit)


@api_method('files.preview_cancel')
@guarded
def preview_cancel(preview_id: str | None = None):
    return previews().cancel(preview_id)


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


@api_method("pivot.preview")
@guarded
def pivot_preview(task_id: str, selection: dict, rows: list, columns: list, values: list, aggregate: str = 'sum'):
    from assistant.tables import read, aggregate_pivot, records
    from assistant.models import InputSelection
    store, _ = services()
    frame = read(store, task_id, InputSelection.model_validate(selection))
    result = aggregate_pivot(frame, rows, columns[0] if columns else None, values, aggregate)
    cells = len(result) * len(result.columns)
    if cells > 5000:
        raise ValueError('结果超过 5000 个单元格，请缩小行列或聚合范围')
    return {"columns": result.columns.tolist(), "rows": records(result), "total": cells}


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
    fallback = raw.get('fallback') or {}
    return {'base_url': raw.get('base_url', ''), 'model': raw.get('model', ''),
            'fallback': {'base_url': fallback.get('base_url', ''), 'model': fallback.get('model', '')},
            'agent_backend': raw.get('agent_backend') or 'native'}


@api_method("settings.save")
@guarded
def settings_save(base_url: str, model: str, fallback_base_url: str = '', fallback_model: str = '', agent_backend: str = 'native'):
    from assistant.model_registry import validate_base_url
    base_url = validate_base_url(base_url)
    if not model.strip():
        raise ValueError('请输入实际 model 标识')
    if agent_backend not in {'native', 'qwen'}:
        raise ValueError('请选择原生直连或 Qwen Code 后端')
    config = {"base_url": base_url, "model": model.strip(), "agent_backend": agent_backend}
    fallback_base_url = (fallback_base_url or '').strip()
    fallback_model = (fallback_model or '').strip()
    if fallback_base_url or fallback_model:
        if not fallback_base_url or not fallback_model:
            raise ValueError('备用模型服务需要同时填写地址与 model 标识')
        config["fallback"] = {"base_url": validate_base_url(fallback_base_url), "model": fallback_model}
    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return True


def set_app_version(version):
    global _app_version
    _app_version = version or ""


def update_config_path():
    return data_root() / "update.json"


def _read_update_config():
    path = update_config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return {}


@api_method("update.get")
def update_get():
    raw = _read_update_config()
    return {'version': _app_version, 'base_url': raw.get('base_url', ''), 'enabled': raw.get('enabled', True)}


@api_method("update.save")
@guarded
def update_save(base_url: str, enabled: bool = True):
    from assistant.update_service import validate_update_url
    base_url = validate_update_url(base_url)
    update_config_path().parent.mkdir(parents=True, exist_ok=True)
    update_config_path().write_text(json.dumps({'base_url': base_url, 'enabled': bool(enabled)}, ensure_ascii=False), encoding='utf-8')
    return True


@api_method("update.check")
@guarded
def update_check():
    from assistant.update_service import check_update, resolve_base_url
    raw = _read_update_config()
    if raw.get('enabled') is False:
        return {'update_available': False, 'current_version': _app_version, 'reason': '已停用更新检查'}
    return check_update(resolve_base_url(raw.get('base_url', '')), _app_version)


@api_method("tasks.agent")
@guarded
def agent(task_id: str, prompt: str, selections: list[dict], editing_selection: dict | None = None):
    if not prompt.strip() or len(prompt) > 20000:
        raise ValueError("请输入有效任务要求")
    from assistant.models import InputSelection
    from assistant.agent import AgentRunner
    store, jobs = services()
    for item in selections:
        selection = InputSelection.model_validate(item)
        if selection.workbook_id:
            from assistant.workbooks import Workbooks
            Workbooks(store).input(task_id, selection)
        else:
            store.resolve_file(task_id, selection.file_id)
    with _lock:
        check_execution()
        from assistant.model_registry import choose
        settings = settings_get()
        endpoint = choose(settings)
        backend = (settings.get('agent_backend') or 'native')
        config = {'base_url': endpoint['base_url'], 'model': endpoint['model'],
                  'api_key_env': endpoint['key_env'], 'model_source': endpoint['used'],
                  'backend': backend}
        if backend == 'qwen':
            selected = environment().runtime.selected()
            config.update(cli=selected['cli'], node_executable=selected['node_executable'],
                          runtime_fingerprint=selected['fingerprint'])
            AgentRunner(store, task_id, config).options()
        scope = None
        if editing_selection:
            scope = InputSelection.model_validate(editing_selection)
            if not scope.workbook_id or not scope.range:
                raise ValueError('区域编辑须提供明确的工作簿选区')
            from assistant.workbooks import Workbooks
            record = Workbooks(store).load(task_id, scope.workbook_id, scope.version)
            if record['current_revision'] != scope.version or record['readonly']:
                raise ValueError('当前编辑选区已过期或只读')
        record = store.get(task_id)
        record['editing_scope'] = scope.model_dump(exclude_none=True) if scope else None
        store.save(record)
        request = prompt + "\n用户选定的输入与表头：" + json.dumps(selections, ensure_ascii=False)
        store.event(task_id, "user", prompt)
        store.event(task_id, "message", f"已连接模型服务：{endpoint['model']}（{'备用' if endpoint['used'] == 'fallback' else '主'} · {'Qwen Code' if backend == 'qwen' else '原生直连'}）")
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


def scheduler():
    global _scheduler
    with _lock:
        if _scheduler is None:
            from assistant.scheduler import SchedulerService
            _scheduler = SchedulerService(services()[0], services()[1])
            _scheduler.start()
        return _scheduler


def start_scheduler():
    scheduler()


@api_method("automation.list")
@guarded
def automation_list():
    return scheduler().list()


@api_method("automation.status")
@guarded
def automation_status():
    return scheduler().status()


@api_method("automation.save")
@guarded
def automation_save(schedule: dict):
    return scheduler().save(schedule)


@api_method("automation.delete")
@guarded
def automation_delete(schedule_id: str):
    return scheduler().delete(schedule_id)


@api_method("automation.toggle")
@guarded
def automation_toggle(schedule_id: str, enabled: bool):
    return scheduler().toggle(schedule_id, enabled)


@api_method("automation.run")
@guarded
def automation_run(schedule_id: str):
    return scheduler().run_now(schedule_id)


@api_method("automation.choose_folder")
@guarded
def automation_choose_folder():
    import webview
    paths = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
    return paths[0] if paths else None


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
    if _previews:
        _previews.cancel()
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
    settings = settings_get()
    backend = settings.get('agent_backend') or 'native'
    model_ready = bool((settings.get('base_url') or '').strip() and (settings.get('model') or '').strip())
    if backend == 'qwen':
        try:
            selected = service.runtime.selected()
            status = {'ready': model_ready, 'selected': selected, 'message': '运行环境已验证'}
        except ValueError as exc:
            status = {'ready': False, 'selected': None, 'message': str(exc)}
    else:
        status = {'ready': model_ready, 'selected': None,
                  'message': '原生直连' if model_ready else '请先保存模型服务地址与 model 标识'}
    status['backend'] = backend
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
def diagnostics_check(kind: str, config: dict | None = None):
    if kind == 'model':
        return environment().check(kind, config if config is not None else settings_get())
    return environment().check(kind, None)


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
    if _scheduler:
        _scheduler.close()
    if _previews:
        _previews.close()
    if _environment:
        _environment.close()
    if _jobs:
        _jobs.close()


def workbooks():
    from assistant.workbooks import Workbooks
    return Workbooks(services()[0])


@api_method('workbooks.list')
@guarded
def workbook_list(task_id: str):
    return workbooks().list(task_id)


@api_method('workbooks.open')
@guarded
def workbook_open(task_id: str, workbook_id: str | None = None, file_id: str | None = None, pure_data: bool = False, revision: int | None = None):
    with _lock:
        return workbooks().open(task_id, workbook_id, file_id, pure_data, revision)


@api_method('workbooks.save')
@guarded
def workbook_save(task_id: str, snapshot: dict, expected_version: int):
    with _lock:
        return workbooks().save(task_id, snapshot, expected_version)


@api_method('workbooks.versions')
@guarded
def workbook_versions(task_id: str, workbook_id: str, offset: int = 0, limit: int = 50):
    return workbooks().versions(task_id, workbook_id, offset, limit)


@api_method('workbooks.restore')
@guarded
def workbook_restore(task_id: str, workbook_id: str, revision: int, expected_version: int):
    with _lock:
        return workbooks().restore(task_id, workbook_id, revision, expected_version)


@api_method('workbooks.undo')
@guarded
def workbook_undo(task_id: str, workbook_id: str, expected_version: int):
    with _lock:
        return workbooks().undo(task_id, workbook_id, expected_version)


@api_method('outputs.review')
@guarded
def output_review(task_id: str, output_id: str):
    return workbooks().review(task_id, output_id)


@api_method('outputs.changes')
@guarded
def output_changes(task_id: str, output_id: str, offset: int = 0, limit: int = 50):
    return workbooks().changes(task_id, output_id, offset, limit)


@api_method('outputs.apply')
@guarded
def output_apply(task_id: str, output_id: str):
    with _lock:
        ensure_idle()
        return workbooks().apply(task_id, output_id)


@api_method('outputs.export')
@guarded
def output_export(task_id: str, workbook_id: str | None = None, expected_version: int | None = None, output_id: str | None = None):
    import webview
    with _lock:
        ensure_idle()
        service = workbooks()
        service.idle(task_id)
        if workbook_id:
            record = service.load(task_id, workbook_id, expected_version)
            if expected_version != record['current_revision'] or record['readonly']:
                raise ValueError('请先保存并重新核对当前工作簿版本')
            name = record['snapshot']['name'].removesuffix('.xlsx') + '.xlsx'
        elif output_id:
            review = service.review(task_id, output_id)
            if review.get('can_edit') or review.get('legacy'):
                raise ValueError('请先采用候选并在编辑器完成公式计算后导出；旧结果可用 Excel 打开')
            if review.get('state') != 'ready':
                raise ValueError('此候选所属执行尚未成功或已取消')
            if review.get('requires_excel_recalculation'):
                raise ValueError('此文件含编辑器未支持的对象且公式需要重算，请使用 Excel 原生重算副本后核对')
            if services()[0].get(task_id)['status'] in {'failed', 'cancelled'}:
                raise ValueError('任务失败或取消，请重新生成完整结果')
            source, _ = services()[0].resolve_file(task_id, output_id)
            name = '核对结果.xlsx'
        else:
            raise ValueError('请选择明确的导出版本')
        paths = webview.windows[0].create_file_dialog(webview.SAVE_DIALOG, save_filename=name, file_types=('Excel (*.xlsx)',))
        if not paths:
            return {'exported': False, 'cancelled': True}
        target = Path(paths if isinstance(paths, str) else paths[0])
        if workbook_id:
            return service.export(task_id, workbook_id, expected_version, target, output_id)
        if target.suffix.lower() != '.xlsx' or target.exists():
            raise ValueError('请使用新的 .xlsx 文件名另存')
        import shutil
        created = False
        try:
            with source.open('rb') as src, target.open('xb') as dst:
                created = True
                shutil.copyfileobj(src, dst)
                dst.flush(); os.fsync(dst.fileno())
            with services()[0].connect() as db:
                db.execute('UPDATE output_reviews SET exported_revision=1 WHERE task=? AND id=?', (task_id, output_id))
        except BaseException:
            if created:
                target.unlink(missing_ok=True)
            raise
        return {'exported': True, 'name': target.name}

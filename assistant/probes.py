"""Executed only in disposable diagnostic workers."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
import os
from pathlib import Path
import threading
import time


class ProbeFailure(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def model_probe(config):
    from .model_registry import validate_base_url, list_models, probe as registry_probe
    try:
        base = validate_base_url(config.get('base_url', ''))
    except ValueError as exc:
        return {'status': 'fail', 'code': 'invalid_url', 'message': str(exc), 'models': []}
    key = os.environ.get('EXCEL_ASSISTANT_API_KEY', 'EMPTY')
    if not config.get('model'):
        listing = list_models(base, key)
        return {'status': 'pass' if listing['ok'] else 'fail',
                'code': 'connected' if listing['ok'] else 'network',
                'message': ('已列出 ' + str(len(listing['models'])) + ' 个模型，请选择 model 标识并保存' if listing['ok'] else listing['error']),
                'models': listing['models']}
    result = {'models': list_models(base, key)['models']}
    result.update(registry_probe(base, config['model'], key))
    return result


def excel_probe(folder):
    import pythoncom
    import win32com.client
    import win32process
    import psutil
    pythoncom.CoInitialize()
    app = None
    owned = False
    started = time.time()
    try:
        app = win32com.client.DispatchEx('Excel.Application')
        _, pid = win32process.GetWindowThreadProcessId(app.Hwnd)
        process = psutil.Process(pid)
        if process.create_time() < started - 1 or process.name().lower() != 'excel.exe':
            raise RuntimeError('Excel ownership not confirmed')
        owned = True
        (folder / 'excel-owner.json').write_text(json.dumps({'pid': pid, 'created': process.create_time()}))
        app.Visible = False
        app.DisplayAlerts = False
        app.EnableEvents = False
        app.AutomationSecurity = 3
        version = str(app.Version)
        return {'status': 'pass', 'message': f'独立 Excel COM 实例启动成功，版本 {version}；未打开工作簿', 'code': 'excel_started'}
    finally:
        if owned:
            app.Quit()
        app = None
        pythoncom.CoUninitialize()


def agent_probe(config, folder):
    from .agent import AgentRunner
    from .store import Store
    from qwen_code_sdk import query
    import psutil
    state = {'mode': 'execute', 'file_id': '', 'denied': False, 'tools': False, 'request': threading.Event(), 'stop': threading.Event()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                state['request'].set()
                if state['mode'] == 'cancel':
                    state['stop'].wait(80)
                    return
                names = {t['function']['name'] for t in body.get('tools', [])}
                forbidden = {'run_shell_command', 'read_file', 'agent', 'web_fetch'}
                if names & forbidden:
                    raise ValueError('Unexpected built-in tools')
                if names:
                    state['tools'] = True
                delta = {'role': 'assistant', 'content': 'Synthetic protocol check complete.'}
                finish = 'stop'
                if not any(m.get('role') == 'tool' for m in body.get('messages', [])):
                    if state['mode'] == 'execute':
                        name = next(n for n in names if n.endswith('datacraft_execute'))
                        args = {'operation': {'kind': 'append', 'inputs': [{'file_id': state['file_id']}], 'params': {}}}
                    else:
                        name = 'ask_user_question'
                        args = {'questions': [{'question': 'Synthetic permission check?', 'header': 'Check', 'options': [{'label': 'A', 'description': 'A'}, {'label': 'B', 'description': 'B'}], 'multiSelect': False}]}
                    delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'diagnostic-call', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}
                    finish = 'tool_calls'
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                for change, reason in [(delta, None), ({}, finish)]:
                    event = {'id': 'diagnostic', 'object': 'chat.completion.chunk', 'choices': [{'index': 0, 'delta': change, 'finish_reason': reason}]}
                    self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
                self.wfile.write(b'data: [DONE]\n\n')
                self.wfile.flush()
            except (BrokenPipeError, ConnectionError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    config = {**config, 'base_url': f'http://127.0.0.1:{server.server_port}/v1', 'model': 'synthetic-protocol-check'}
    # The fixture never needs or forwards the customer's authentication secret.
    os.environ['EXCEL_ASSISTANT_API_KEY'] = 'diagnostic-fixture'
    store = Store(folder / 'synthetic-data')
    source = folder / 'synthetic.csv'
    source.write_text('code,qty\n0001,2\nNA,3\n')

    async def run():
        task = store.create()['id']
        state['file_id'] = store.import_file(task, source)['id']
        runner = AgentRunner(store, task, config)
        await runner.run('Use the synthetic tool fixture.')
        if not store.get(task)['session_id'] or not store.get(task)['outputs'] or not state['tools']:
            raise ValueError('Missing MCP output/session')
        denied_task = store.create()['id']
        options = AgentRunner(store, denied_task, config).options()
        options['timeout'] = {'stream_close': 3, 'control_request': 10}

        async def deny(name, payload, context):
            state['denied'] = name == 'ask_user_question'
            return {'behavior': 'deny', 'message': 'Synthetic denial; do not execute this tool.'}

        options['can_use_tool'] = deny
        state['mode'] = 'deny'
        async with query('Exercise the synthetic denial.', options) as stream:
            async for _ in stream:
                pass
        if not state['denied'] or store.get(denied_task)['outputs']:
            raise ValueError('Permission callback was not invoked')
        state['mode'] = 'cancel'
        state['request'].clear()
        before = {(p.pid, p.create_time()) for p in psutil.Process().children(recursive=True)}

        async def pending():
            async with query('Wait for diagnostic cancellation.', options) as stream:
                async for _ in stream:
                    pass

        pending_task = asyncio.create_task(pending())
        try:
            for _ in range(300):
                if state['request'].is_set():
                    break
                if pending_task.done():
                    await pending_task
                    raise ValueError('CLI exited before cancellation')
                await asyncio.sleep(0.05)
            if not state['request'].is_set():
                raise ValueError('Cancellation request did not start')
            expected_node = Path(config['node_executable']).resolve()
            if not any(Path(p.exe()).resolve() == expected_node for p in psutil.Process().children(recursive=True)):
                raise ValueError('CLI did not run using the selected Node executable')
        finally:
            pending_task.cancel()
            try:
                await asyncio.wait_for(pending_task, 8)
            except asyncio.CancelledError:
                pass
        await asyncio.sleep(0.3)
        leaked = [p for p in psutil.Process().children(recursive=True) if (p.pid, p.create_time()) not in before and p.is_running()]
        if leaked:
            raise ValueError('Cancellation left diagnostic descendants running')
    try:
        try:
            asyncio.run(run())
        except Exception as exc:
            stage = state['mode']
            descriptions = {'execute': 'SDK 事件或 MCP 输出检查未通过', 'deny': '工具权限拒绝检查未通过', 'cancel': '取消或指定 Node 检查未通过'}
            raise ProbeFailure('agent_' + stage, descriptions[stage] + '；请使用已验证的完整运行组合') from exc
        return {'status': 'pass', 'message': 'CLI 事件、会话、MCP 输出、权限拒绝及取消检查通过', 'code': 'agent_verified'}
    finally:
        state['stop'].set()
        server.shutdown()
        server.server_close()


def probe(kind, payload, folder):
    if kind == 'model':
        return model_probe(payload)
    if kind == 'excel':
        return excel_probe(folder)
    if kind == 'agent':
        return agent_probe(payload, folder)
    if kind == 'dependencies':
        failed = []
        for module in ['pandas', 'openpyxl', 'xlsxwriter', 'python_calamine', 'mcp', 'qwen_code_sdk', 'webview', 'clr', 'psutil']:
            try:
                importlib.import_module(module)
            except Exception:
                failed.append(module)
        return {'status': 'fail' if failed else 'pass', 'message': '缺失或无法加载：' + ', '.join(failed) if failed else 'Python 及数据组件加载正常', 'code': 'dependencies', 'failed_modules': failed}
    raise ValueError('Unknown diagnostic kind')

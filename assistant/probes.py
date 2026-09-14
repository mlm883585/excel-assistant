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
    import httpx
    from urllib.parse import urlparse
    base = config.get('base_url', '').rstrip('/')
    parsed = urlparse(base)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or not config.get('model'):
        return {'status': 'fail', 'code': 'not_configured', 'message': '请先保存内网模型地址和 model 标识'}
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return {'status': 'fail', 'code': 'invalid_url', 'message': '模型地址不能包含账户信息、查询参数或片段'}
    try:
        with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
            response = client.post(base + '/chat/completions', headers={'Authorization': 'Bearer ' + os.environ.get('EXCEL_ASSISTANT_API_KEY', 'EMPTY')},
                                   json={'model': config['model'], 'messages': [{'role': 'user', 'content': 'Reply OK.'}], 'max_tokens': 8, 'stream': False})
        if response.status_code in {401, 403}:
            return {'status': 'fail', 'code': 'authentication', 'message': '认证失败，请由 IT 核对密钥及访问权限'}
        if response.status_code == 404:
            return {'status': 'fail', 'code': 'model_or_endpoint', 'message': '模型或接口不存在，请核对地址和 model 标识'}
        if not 200 <= response.status_code < 300:
            return {'status': 'fail', 'code': f'http_{response.status_code}', 'message': f'模型服务返回 HTTP {response.status_code}；请核对服务协议与模型配置'}
        body = response.json()
        if not isinstance(body.get('choices'), list) or not body['choices'] or 'message' not in body['choices'][0]:
            raise ValueError('invalid response')
        return {'status': 'pass', 'message': '模型最小请求通过；工具调用能力仍需业务验收', 'code': 'connected'}
    except httpx.TimeoutException:
        return {'status': 'fail', 'code': 'timeout', 'message': '模型响应超时'}
    except httpx.TransportError:
        return {'status': 'fail', 'code': 'network', 'message': '模型连接或 TLS 验证失败，请检查内网服务、证书与防火墙'}
    except (ValueError, KeyError, TypeError):
        return {'status': 'fail', 'code': 'protocol', 'message': '返回内容不是支持的 Chat Completions 格式'}


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

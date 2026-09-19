import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os

from assistant.model_registry import (
    ModelError, api_key, choose, chat, complete, list_models, probe, resolve,
    validate_base_url, PRIMARY_KEY_ENV, FALLBACK_KEY_ENV,
)


class ModelHandler(BaseHTTPRequestHandler):
    behavior = {}  # {'chat': 'ok'|'auth'|'missing'|'error', 'models': 'openai'|'ollama'|'none'}

    def log_message(self, *args):
        pass

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.rstrip('/')
        if path.endswith('/models') and self.behavior['models'] == 'openai':
            self._json(200, {'data': [{'id': 'qwen2.5:7b'}, {'id': 'llama3.1:8b'}]})
            return
        if path.endswith('/api/tags') and self.behavior['models'] == 'ollama':
            self._json(200, {'models': [{'name': 'qwen2.5:7b'}, {'name': 'llama3.1:8b'}]})
            return
        self._json(404, {'error': 'not found'})

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', '0')))
        mode = self.behavior['chat']
        if mode == 'auth':
            self._json(401, {'error': 'unauthorized'}); return
        if mode == 'missing':
            self._json(404, {'error': 'no model'}); return
        if mode == 'error':
            self._json(500, {'error': 'boom'}); return
        if mode == 'tools':
            self._json(200, {'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': None,
                'tool_calls': [{'id': 'call_1', 'type': 'function', 'function': {'name': 'datacraft_files', 'arguments': '{}'}}]},
                'finish_reason': 'tool_calls'}]}); return
        self._json(200, {'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'OK'}, 'finish_reason': 'stop'}]})


def start_server(behavior):
    class Handler(ModelHandler):
        pass
    Handler.behavior = behavior
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f'http://127.0.0.1:{server.server_port}/v1'


class ModelRegistryTests(unittest.TestCase):
    def test_validate_base_url(self):
        self.assertEqual(validate_base_url('http://10.0.0.5:8000/v1/'), 'http://10.0.0.5:8000/v1')
        for bad in ('ftp://host/v1', 'no-scheme', 'http://', 'http://user:pw@host/v1', 'http://host/v1?x=1', 'http://host/v1#f'):
            with self.assertRaises(ValueError, msg=bad):
                validate_base_url(bad)

    def test_api_key_fallback_defaults_to_primary(self):
        previous = os.environ.get(PRIMARY_KEY_ENV), os.environ.get(FALLBACK_KEY_ENV)
        try:
            os.environ.pop(PRIMARY_KEY_ENV, None)
            os.environ.pop(FALLBACK_KEY_ENV, None)
            self.assertEqual(api_key(PRIMARY_KEY_ENV), 'EMPTY')
            self.assertEqual(api_key(FALLBACK_KEY_ENV), 'EMPTY')
            os.environ[PRIMARY_KEY_ENV] = 'primary-secret'
            self.assertEqual(api_key(FALLBACK_KEY_ENV), 'primary-secret')
            os.environ[FALLBACK_KEY_ENV] = 'fallback-secret'
            self.assertEqual(api_key(FALLBACK_KEY_ENV), 'fallback-secret')
        finally:
            for key, value in zip((PRIMARY_KEY_ENV, FALLBACK_KEY_ENV), previous):
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_list_models_openai_shape(self):
        server, base = start_server({'models': 'openai', 'chat': 'ok'})
        result = list_models(base)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['models'], ['llama3.1:8b', 'qwen2.5:7b'])

    def test_list_models_ollama_shape(self):
        server, base = start_server({'models': 'ollama', 'chat': 'ok'})
        result = list_models(base)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['models'], ['llama3.1:8b', 'qwen2.5:7b'])

    def test_list_models_failure(self):
        server, base = start_server({'models': 'none', 'chat': 'ok'})
        result = list_models(base)
        self.assertFalse(result['ok'])
        self.assertEqual(result['models'], [])

    def test_probe_classification(self):
        for mode, expected in [('ok', 'pass'), ('auth', 'authentication'), ('missing', 'model_or_endpoint'), ('error', 'http_500')]:
            server, base = start_server({'models': 'none', 'chat': mode})
            result = probe(base, 'm', timeout=3)
            if expected == 'pass':
                self.assertEqual(result['status'], 'pass', result)
                self.assertEqual(result['code'], 'connected')
            else:
                self.assertEqual(result['status'], 'fail', result)
                self.assertEqual(result['code'], expected)

    def test_complete_returns_text_and_raises(self):
        server, base = start_server({'models': 'none', 'chat': 'ok'})
        self.assertEqual(complete(base, 'm', [{'role': 'user', 'content': 'hi'}] ), 'OK')
        server, base = start_server({'models': 'none', 'chat': 'auth'})
        with self.assertRaises(ModelError):
            complete(base, 'm', [{'role': 'user', 'content': 'hi'}])

    def test_chat_parses_tool_calls(self):
        server, base = start_server({'models': 'none', 'chat': 'tools'})
        result = chat(base, 'm', [{'role': 'user', 'content': 'hi'}],
                      tools=[{'type': 'function', 'function': {'name': 'datacraft_files', 'parameters': {}}}])
        self.assertEqual(result['content'], '')
        self.assertEqual(len(result['tool_calls']), 1)
        self.assertEqual(result['tool_calls'][0]['name'], 'datacraft_files')
        self.assertEqual(result['tool_calls'][0]['arguments'], {})

    def test_resolve_orders_endpoints(self):
        self.assertEqual(resolve({}), [])
        one = resolve({'base_url': 'http://a/v1', 'model': 'm'})
        self.assertEqual([e['label'] for e in one], ['主'])
        two = resolve({'base_url': 'http://a/v1', 'model': 'm', 'fallback': {'base_url': 'http://b/v1', 'model': 'n'}})
        self.assertEqual([e['label'] for e in two], ['主', '备用'])
        self.assertEqual(two[1]['key_env'], FALLBACK_KEY_ENV)

    def test_choose_primary_wins(self):
        good, gbase = start_server({'models': 'none', 'chat': 'ok'})
        bad, bbase = start_server({'models': 'none', 'chat': 'error'})
        result = choose({'base_url': gbase, 'model': 'm', 'fallback': {'base_url': bbase, 'model': 'n'}})
        self.assertEqual(result['used'], 'primary')

    def test_choose_falls_back(self):
        bad, bbase = start_server({'models': 'none', 'chat': 'error'})
        good, gbase = start_server({'models': 'none', 'chat': 'ok'})
        result = choose({'base_url': bbase, 'model': 'm', 'fallback': {'base_url': gbase, 'model': 'n'}})
        self.assertEqual(result['used'], 'fallback')
        self.assertEqual(result['model'], 'n')

    def test_choose_both_fail_raises(self):
        bad1, b1 = start_server({'models': 'none', 'chat': 'error'})
        bad2, b2 = start_server({'models': 'none', 'chat': 'auth'})
        with self.assertRaisesRegex(ValueError, '均无法连接'):
            choose({'base_url': b1, 'model': 'm', 'fallback': {'base_url': b2, 'model': 'n'}})

    def test_choose_primary_fail_no_fallback_returns_primary(self):
        bad, bbase = start_server({'models': 'none', 'chat': 'error'})
        result = choose({'base_url': bbase, 'model': 'm'})
        self.assertEqual(result['used'], 'primary')

    def test_choose_missing_config_raises(self):
        with self.assertRaisesRegex(ValueError, '保存'):
            choose({})


if __name__ == '__main__':
    unittest.main()

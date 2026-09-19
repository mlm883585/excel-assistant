"""OpenAI-compatible model endpoint matrix (Ollama/vLLM/Xinference/SGLang/llama.cpp/MindIE).

All supported intranet backends expose the OpenAI `/v1/models` + `/chat/completions`
surface. This module is the single place that talks HTTP to them: URL validation,
model listing, a minimal completion probe, and primary→fallback selection. API keys
are read from the process environment only, never from configuration files.
"""
import json
import os
import time
from urllib.parse import urlparse

import httpx

PRIMARY_KEY_ENV = 'EXCEL_ASSISTANT_API_KEY'
FALLBACK_KEY_ENV = 'EXCEL_ASSISTANT_FALLBACK_API_KEY'


class ModelError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def validate_base_url(base):
    parsed = urlparse(base)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        raise ValueError('请输入内网 HTTP(S) 模型地址')
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('模型地址不能包含账户信息、查询参数或片段')
    return base.rstrip('/')


def api_key(key_env=PRIMARY_KEY_ENV):
    if key_env in os.environ:
        return os.environ[key_env]
    if key_env == FALLBACK_KEY_ENV:
        return os.environ.get(PRIMARY_KEY_ENV, 'EMPTY')
    return 'EMPTY'


def _server_root(base):
    base = base.rstrip('/')
    return base[:-3] if base.lower().endswith('/v1') else base


def _headers(api_key):
    return {'Authorization': 'Bearer ' + (api_key or 'EMPTY')}


def list_models(base_url, api_key=None, timeout=8):
    """Return `{'ok', 'models': [...], 'error'}` from `/v1/models` then Ollama `/api/tags`."""
    base = base_url.rstrip('/')
    try:
        with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
            response = client.get(base + '/models', headers=_headers(api_key))
            if response.status_code == 200:
                body = response.json()
                data = body.get('data')
                if isinstance(data, list):
                    models = sorted({str(m['id']) for m in data if isinstance(m, dict) and m.get('id')})
                    if models:
                        return {'ok': True, 'models': models, 'error': None}
            response = client.get(_server_root(base) + '/api/tags', headers=_headers(api_key))
            if response.status_code == 200:
                body = response.json()
                data = body.get('models')
                if isinstance(data, list):
                    models = sorted({str(m['name']) for m in data if isinstance(m, dict) and m.get('name')})
                    if models:
                        return {'ok': True, 'models': models, 'error': None}
            return {'ok': False, 'models': [], 'error': f'模型列表接口返回 HTTP {response.status_code} 或格式不支持'}
    except httpx.TimeoutException:
        return {'ok': False, 'models': [], 'error': '模型列表请求超时'}
    except httpx.TransportError:
        return {'ok': False, 'models': [], 'error': '模型服务连接失败，请检查内网地址与防火墙'}
    except (ValueError, KeyError, TypeError):
        return {'ok': False, 'models': [], 'error': '模型列表返回格式不支持'}


def chat(base_url, model, messages, api_key=None, timeout=60, max_tokens=None,
         tools=None, tool_choice=None, response_format=None):
    """Non-streaming Chat Completions; returns `{'content', 'tool_calls', 'finish_reason'}` or raises ModelError.

    `tool_calls` is a list of `{'id', 'name', 'arguments'}` with `arguments` JSON-decoded
    to a dict (or `None` when the endpoint returned malformed arguments)."""
    body = {'model': model, 'messages': messages, 'stream': False}
    if max_tokens is not None:
        body['max_tokens'] = max_tokens
    if tools:
        body['tools'] = tools
    if tool_choice:
        body['tool_choice'] = tool_choice
    if response_format:
        body['response_format'] = response_format
    try:
        with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
            response = client.post(base_url.rstrip('/') + '/chat/completions', headers=_headers(api_key), json=body)
    except httpx.TimeoutException:
        raise ModelError('timeout', '模型响应超时') from None
    except httpx.TransportError:
        raise ModelError('network', '模型连接或 TLS 验证失败，请检查内网服务、证书与防火墙') from None
    if response.status_code in {401, 403}:
        raise ModelError('authentication', '认证失败，请由 IT 核对密钥及访问权限')
    if response.status_code == 404:
        raise ModelError('model_or_endpoint', '模型或接口不存在，请核对地址和 model 标识')
    if not 200 <= response.status_code < 300:
        raise ModelError(f'http_{response.status_code}', f'模型服务返回 HTTP {response.status_code}；请核对服务协议与模型配置')
    try:
        payload = response.json()
        choices = payload.get('choices')
        if not isinstance(choices, list) or not choices or not isinstance(choices[0].get('message'), dict):
            raise ModelError('protocol', '返回内容不是支持的 Chat Completions 格式')
        message = choices[0]['message']
        content = message.get('content') or ''
        content = content if isinstance(content, str) else str(content)
        tool_calls = []
        for call in message.get('tool_calls') or []:
            if not isinstance(call, dict):
                continue
            function = call.get('function') or {}
            arguments = function.get('arguments')
            raw = arguments
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except (ValueError, TypeError):
                    arguments = None
            elif not isinstance(arguments, dict):
                arguments = None
            tool_calls.append({'id': call.get('id'), 'name': function.get('name'),
                               'arguments': arguments, 'raw_arguments': raw})
        return {'content': content, 'tool_calls': tool_calls, 'finish_reason': choices[0].get('finish_reason')}
    except ModelError:
        raise
    except (ValueError, KeyError, TypeError):
        raise ModelError('protocol', '返回内容不是支持的 Chat Completions 格式') from None


def complete(base_url, model, messages, api_key=None, timeout=30, max_tokens=None):
    """Non-streaming chat completion; returns the assistant text or raises ModelError."""
    return chat(base_url, model, messages, api_key=api_key, timeout=timeout, max_tokens=max_tokens)['content']


def probe(base_url, model, api_key=None, timeout=10):
    """Minimal completion check; returns `{'status','code','message','latency_ms'}`."""
    started = time.monotonic()
    try:
        complete(base_url, model, [{'role': 'user', 'content': 'Reply OK.'}], api_key=api_key, timeout=timeout, max_tokens=8)
        return {'status': 'pass', 'code': 'connected', 'message': '模型最小请求通过；工具调用能力仍需业务验收',
                'latency_ms': int((time.monotonic() - started) * 1000)}
    except ModelError as exc:
        return {'status': 'fail', 'code': exc.code, 'message': exc.message,
                'latency_ms': int((time.monotonic() - started) * 1000)}


def resolve(settings):
    """Pure ordering of configured endpoints: primary then optional fallback."""
    endpoints = []
    base = (settings.get('base_url') or '').strip()
    model = (settings.get('model') or '').strip()
    if base and model:
        endpoints.append({'base_url': base, 'model': model, 'key_env': PRIMARY_KEY_ENV, 'label': '主'})
    fallback = settings.get('fallback') or {}
    fbase = (fallback.get('base_url') or '').strip()
    fmodel = (fallback.get('model') or '').strip()
    if fbase and fmodel:
        endpoints.append({'base_url': fbase, 'model': fmodel, 'key_env': FALLBACK_KEY_ENV, 'label': '备用'})
    return endpoints


def choose(settings, timeout=5):
    """Probe endpoints in order and return the first that passes (or primary when no fallback)."""
    endpoints = resolve(settings)
    if not endpoints:
        raise ValueError('请先保存内网模型服务地址与 model 标识')
    failures = []
    for endpoint in endpoints:
        result = probe(endpoint['base_url'], endpoint['model'], api_key(endpoint['key_env']), timeout)
        if result['status'] == 'pass':
            used = 'fallback' if endpoint['label'] == '备用' else 'primary'
            return {**endpoint, 'used': used, 'latency_ms': result.get('latency_ms')}
        failures.append(f"{endpoint['label']}服务 {endpoint['model']}：{result['message']}")
    if len(endpoints) > 1:
        raise ValueError('主/备用模型服务均无法连接：' + '；'.join(failures))
    return {**endpoints[0], 'used': 'primary', 'latency_ms': None}

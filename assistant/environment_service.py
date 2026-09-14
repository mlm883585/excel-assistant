"""Application-owned asynchronous diagnostics; never requires the business database."""
from collections import OrderedDict
from copy import deepcopy
import threading
import uuid

from .diagnostics import item, report, local_check, export_report
from .diagnostic_process import run_probe


class EnvironmentService:
    def __init__(self, runtime):
        self.runtime = runtime
        self.lock = threading.RLock()
        self.runs = OrderedDict()
        self.thread = None
        self.stop = threading.Event()
        self.closed = False
        self.last_report = report([])
        self.results = {}
        self.installing = False
        self.on_select = None

    def start(self, kind, operation):
        with self.lock:
            if self.closed:
                raise ValueError('检测服务已关闭')
            if self.thread and self.thread.is_alive():
                raise ValueError('已有检测或安装正在进行，请等待或取消检测')
            self.stop = threading.Event()
            run_id = uuid.uuid4().hex
            self.runs[run_id] = {'run_id': run_id, 'kind': kind, 'state': 'running', 'message': '正在检测，请稍候'}
            while len(self.runs) > 20:
                self.runs.popitem(last=False)
            self.installing = kind == 'install'
            self.thread = threading.Thread(target=self._run, args=(run_id, kind, operation, self.stop), daemon=True)
            self.thread.start()
            return {'run_id': run_id}

    def _run(self, run_id, kind, operation, stop):
        try:
            result = operation(stop)
            if stop.is_set() and kind != 'install':
                result = {'status': 'cancelled', 'message': '检测已取消', 'code': 'cancelled'}
        except (ValueError, KeyError, OSError) as exc:
            result = {'status': 'fail', 'message': str(exc) if isinstance(exc, ValueError) else '环境检测失败，请检查运行文件与权限', 'code': type(exc).__name__}
        except Exception as exc:
            result = {'status': 'fail', 'message': '检测组件发生错误，请导出报告交由 IT 排查', 'code': type(exc).__name__}
        with self.lock:
            self.runs[run_id].update(state='finished', result=result, message=result.get('message', '检测完成'))
            self.results[kind] = result
            if 'checks' in result:
                for check in result['checks']:
                    self._record(check)
            else:
                self._record(item({'model': '模型连接', 'excel': 'Excel COM', 'agent': 'Agent 协议', 'automatic': '优先复用', 'install': 'WebView2 安装'}.get(kind, kind),
                                  result.get('status', 'fail'), result.get('message', '') + ('；错误码：' + result['code'] if result.get('code') else '')))
            self.installing = False

    def _record(self, check):
        checks = [c for c in self.last_report['checks'] if c['name'] != check['name']]
        self.last_report = report([*checks, check])

    def get(self, run_id):
        with self.lock:
            if run_id not in self.runs:
                raise ValueError('检测记录已过期，请重新检测')
            return deepcopy(self.runs[run_id])

    def cancel(self, run_id):
        with self.lock:
            value = self.get(run_id)
            if value['kind'] == 'install':
                raise ValueError('请在微软安装窗口取消安装；本应用不会强制终止系统安装')
            if value['state'] == 'running':
                self.stop.set()
        return True

    def check(self, kind, config=None):
        if kind == 'local':
            return self.start(kind, lambda stop: local_check(self.runtime, cancel=stop))
        if kind == 'agent':
            candidate = self.runtime.selected()
            with self.runtime.lock:
                self.runtime.candidates[candidate['id']] = candidate
            return self.validate(candidate['id'])
        if kind not in {'model', 'excel'}:
            raise ValueError('不支持的检测类型')
        return self.start(kind, lambda stop: run_probe(kind, config or {}, timeout=15 if kind == 'model' else 20, cancel=stop))

    def validate(self, candidate_id):
        return self.start('agent', lambda stop: self.runtime.validate(candidate_id, stop))

    def automatic(self, legacy=None):
        def operation(stop):
            # An existing (even stale) selection requires an explicit user decision.
            if self.runtime.path.exists():
                selected = self.runtime.selected()
                return {'status': 'pass', 'message': '继续使用已验证的运行环境', 'selected': selected}
            candidates = self.runtime.discover(legacy)
            attempts = []
            for candidate in candidates:
                if stop.is_set():
                    return {'status': 'cancelled', 'message': '检测已取消'}
                if candidate['source'] != '已有安装' or not candidate['compatible']:
                    continue
                result = self.runtime.validate(candidate['id'], stop)
                attempts.append({'id': candidate['id'], 'message': result['message']})
                if result['status'] == 'pass' and not stop.is_set():
                    selected = self.on_select(candidate['id'])
                    return {'status': 'pass', 'message': '已验证并复用已有 Qwen Code', 'selected': selected, 'candidates': candidates}
            return {'status': 'warn', 'message': '没有通过验证的已有组合；请查看原因并点击验证内置版本', 'candidates': candidates, 'attempts': attempts}
        return self.start('automatic', operation)

    def export(self):
        with self.lock:
            return export_report(self.last_report)

    def close(self):
        with self.lock:
            self.closed = True
            self.stop.set()
            thread, installing = self.thread, self.installing
        if thread and not installing:
            thread.join()

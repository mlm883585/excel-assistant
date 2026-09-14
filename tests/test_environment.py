import asyncio
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
import subprocess
from unittest.mock import patch

from assistant.runtime import RuntimeManager, candidate_at, fingerprint, CLI_VERSION
from assistant.environment_service import EnvironmentService
from assistant.diagnostic_process import run_probe
from assistant.diagnostics import export_report, item, report, startup_check, storage_check


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / '已有 安装 中文/node_modules/@qwen-code/qwen-code'
        self.package.mkdir(parents=True)
        (self.package / 'package.json').write_text(json.dumps({'name': '@qwen-code/qwen-code', 'version': CLI_VERSION, 'engines': {'node': '>=22.0.0'}}))
        (self.package / 'cli.js').write_text('// synthetic fixture')
        self.node = self.root / 'node.exe'
        self.node.write_bytes(b'synthetic fixture, never executed')
        self.manager = RuntimeManager(self.root / 'data', self.root)

    def candidate(self):
        with patch('assistant.runtime.node_version', return_value='v24.13.0'):
            value = candidate_at(self.package, [self.node], '已有安装')[0]
        self.manager.candidates[value['id']] = value
        return value

    def validate(self, candidate):
        with patch('assistant.runtime.node_version', return_value='v24.13.0'), patch('assistant.diagnostic_process.run_probe', return_value={'status': 'pass', 'message': 'synthetic pass'}):
            return self.manager.validate(candidate['id'])

    def test_selection_requires_validation_and_invalidates_changed_file(self):
        candidate = self.candidate()
        with self.assertRaises(ValueError):
            self.manager.select(candidate['id'])
        self.validate(candidate)
        selected = self.manager.select(candidate['id'])
        self.assertEqual(self.manager.selected()['node_executable'], str(self.node))
        (self.package / 'cli.js').write_text('// changed')
        with self.assertRaisesRegex(ValueError, '发生变化'):
            self.manager.selected()
        self.assertEqual(json.loads(self.manager.path.read_text(encoding='utf-8')), selected)

    def test_old_version_and_missing_node_are_visible_not_compatible(self):
        meta = self.package / 'package.json'
        body = json.loads(meta.read_text()); body['version'] = '0.21.0'; meta.write_text(json.dumps(body))
        with patch('assistant.runtime.node_version', return_value='v24.13.0'):
            self.assertFalse(candidate_at(self.package, [self.node], '已有安装')[0]['compatible'])
        self.assertFalse(candidate_at(self.package, [], '已有安装')[0]['compatible'])

    def test_stale_discovery_cannot_validate_upgraded_cli(self):
        candidate = self.candidate()
        meta = self.package / 'package.json'
        body = json.loads(meta.read_text()); body['version'] = '99.0.0'; meta.write_text(json.dumps(body))
        with self.assertRaisesRegex(ValueError, '发生变化'):
            self.validate(candidate)

    def test_corrupt_selection_requires_revalidation(self):
        self.manager.path.parent.mkdir()
        for value in ['{', '[]', '{}']:
            self.manager.path.write_text(value)
            with self.assertRaises(ValueError):
                self.manager.selected()

    def test_frozen_frontend_uses_ppx_web_resource_directory(self):
        from assistant.runtime import frontend_entry
        with patch('assistant.runtime.sys.frozen', True, create=True), patch('assistant.runtime.resources_root', return_value=self.root):
            self.assertEqual(frontend_entry(), self.root / 'web/index.html')

    def test_discovery_deduplicates_and_offers_bundled_node(self):
        bundled = self.root / 'runtime/node.exe'; bundled.parent.mkdir(); bundled.write_bytes(b'fixture')
        folder = self.package.parents[2]
        with patch.dict(os.environ, {'PATH': str(folder) + os.pathsep + str(folder), 'APPDATA': str(self.root)}), patch('assistant.runtime.shutil.which', return_value=str(self.node)), patch('assistant.runtime.node_version', return_value='v24.13.0'):
            candidates = self.manager.discover()
        self.assertEqual(len(candidates), 2)
        self.assertEqual(len({c['id'] for c in candidates}), 2)
        self.assertTrue(any(c['node_source'] == '内置' for c in candidates))

    def test_background_detection_cancel_and_close(self):
        service = EnvironmentService(self.manager)
        entered = threading.Event()
        def operation(stop):
            entered.set(); stop.wait(5)
            return {'status': 'pass', 'message': 'done'}
        run = service.start('model', operation)
        self.assertTrue(entered.wait(1))
        with self.assertRaises(ValueError):
            service.start('excel', operation)
        service.cancel(run['run_id']); service.close()
        self.assertEqual(service.get(run['run_id'])['result']['status'], 'cancelled')
        self.assertFalse(service.thread.is_alive())

    def test_automatic_falls_back_only_after_explicit_selection(self):
        candidate = self.candidate(); candidate['compatible'] = False
        service = EnvironmentService(self.manager)
        with patch.object(self.manager, 'discover', return_value=[candidate]):
            run = service.automatic(); service.thread.join(3)
        self.assertEqual(service.get(run['run_id'])['result']['status'], 'warn')
        self.assertFalse(self.manager.path.exists())
        service.close()

    def test_sdk_uses_explicit_node_even_when_path_contains_another(self):
        from qwen_code_sdk.types import QueryOptions
        from qwen_code_sdk.transport import prepare_spawn_info, ProcessTransport
        path = str(self.root / '不存在/node.exe')
        options = QueryOptions.from_mapping({'path_to_qwen_executable': str(self.package / 'cli.js'), 'node_executable': path})
        self.assertEqual(prepare_spawn_info(options.path_to_qwen_executable, options.node_executable).command, path)
        async def launch():
            with self.assertRaises(OSError):
                await ProcessTransport(options).start()
        asyncio.run(launch())

    def test_storage_failure_does_not_block_diagnostic_desktop(self):
        with patch('assistant.diagnostics.local_check', return_value=report([item('数据目录', 'fail', 'unwritable', '任务执行')])):
            self.assertTrue(startup_check())
        file = self.root / 'not-a-directory'; file.write_text('fixture')
        self.assertEqual(storage_check(file)['status'], 'fail')

    def test_report_redacts_secrets_paths_and_endpoint(self):
        with patch.dict(os.environ, {'USERNAME': 'synthetic-user', 'EXCEL_ASSISTANT_API_KEY': 'synthetic-secret'}):
            safe, text = export_report(report([item('Model', 'fail', 'synthetic-user synthetic-secret https://internal.example/v1\nD:\\customer\\data', action='contact IT')]))
        serialized = json.dumps(safe) + text
        for private in ['synthetic-user', 'synthetic-secret', 'internal.example', 'customer']:
            self.assertNotIn(private, serialized)

    def test_worker_cancellation_and_timeout_are_bounded(self):
        stop = threading.Event(); stop.set()
        self.assertEqual(run_probe('dependencies', timeout=20, cancel=stop)['status'], 'cancelled')
        self.assertEqual(run_probe('dependencies', timeout=0)['code'], 'timeout')

    def test_api_import_does_not_load_data_dependencies_and_switch_rejected_while_busy(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'vendor/ppx-py/src'))
        from api import api
        from unittest.mock import Mock
        with patch.object(api, '_jobs', Mock(processes={'task': Mock(is_alive=lambda: True)})):
            with self.assertRaisesRegex(ValueError, '正在执行'):
                api.ensure_idle()
        code = '''import sys, importlib.abc
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'vendor/ppx-py/src'))
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'pandas', 'openpyxl', 'qwen_code_sdk'}:
            raise ImportError('synthetic missing dependency')
sys.meta_path.insert(0, Block())
from api import api
assert api.runtime_status()['ready'] is False
assert api.settings_get() == {'base_url': '', 'model': ''}
api.shutdown()
'''
        result = subprocess.run([sys.executable, '-c', code], env={**os.environ, 'EXCEL_ASSISTANT_HOME': str(self.root / 'isolated')}, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_model_errors_do_not_include_response_or_credentials(self):
        from assistant.probes import model_probe
        import httpx
        from unittest.mock import Mock
        for status, body, expected in [(401, {'secret': 'server-private'}, 'authentication'), (404, {}, 'model_or_endpoint'), (200, {}, 'protocol'), (200, {'choices': [{'message': {'content': 'OK'}}]}, 'connected')]:
            response = httpx.Response(status, json=body)
            client = Mock(); client.__enter__ = Mock(return_value=client); client.__exit__ = Mock(return_value=False)
            client.post.return_value = response
            with patch('httpx.Client', return_value=client):
                result = model_probe({'base_url': 'http://synthetic.invalid/v1', 'model': 'fixture'})
            self.assertEqual(result['code'], expected)
            self.assertNotIn('server-private', str(result))

    def test_installer_uac_and_cancellation_are_reported_without_executing(self):
        from assistant import windows_repair
        elevation = OSError('fixture'); elevation.winerror = 740
        cancelled = OSError('fixture'); cancelled.winerror = 1223
        with patch.object(windows_repair, 'installer_path', return_value=self.node), patch.object(windows_repair.subprocess, 'Popen', side_effect=elevation), patch.object(windows_repair, 'elevated_install', return_value=0) as elevated:
            self.assertEqual(windows_repair.install_webview(self.root)['status'], 'pass')
            elevated.assert_called_once_with(self.node)
        with patch.object(windows_repair, 'installer_path', return_value=self.node), patch.object(windows_repair.subprocess, 'Popen', side_effect=cancelled):
            with self.assertRaisesRegex(ValueError, '取消'):
                windows_repair.install_webview(self.root)

    def test_real_cli_environment_probe(self):
        root = Path(__file__).resolve().parents[1]
        cli = root / 'node_modules/@qwen-code/qwen-code/cli.js'
        if not cli.is_file() or not shutil.which('node'):
            if os.environ.get('REQUIRE_QWEN_CLI') == '1':
                self.fail('Pinned CLI and Node required')
            self.skipTest('Install the pinned CLI and Node')
        result = run_probe('agent', {'cli': str(cli), 'node_executable': shutil.which('node')}, timeout=90)
        self.assertEqual(result['status'], 'pass', result)

    def test_installer_missing_tampered_and_duplicate(self):
        from assistant import windows_repair
        with self.assertRaises(ValueError):
            windows_repair.installer_path(self.root)
        target = self.root / 'prerequisites/WebView2StandaloneX64.exe'; target.parent.mkdir(); target.write_bytes(b'tampered fixture')
        (self.root / 'manifest.sha256.json').write_text(json.dumps({str(target.relative_to(self.root)): 'wrong'}))
        with patch.object(windows_repair, 'verify_microsoft_signature') as verify:
            with self.assertRaisesRegex(ValueError, '哈希'):
                windows_repair.installer_path(self.root)
            verify.assert_not_called()
        with windows_repair._install_lock:
            with self.assertRaisesRegex(ValueError, '重复'):
                windows_repair.install_webview(self.root)


if __name__ == '__main__':
    unittest.main()

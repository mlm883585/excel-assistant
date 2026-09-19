import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from assistant.update_service import (
    DEFAULT_UPDATE_BASE_URL, check_update, is_newer, resolve_base_url, validate_update_url,
)


class UpdateServiceTests(unittest.TestCase):
    def test_is_newer(self):
        self.assertTrue(is_newer("0.2.0", "0.1.0"))
        self.assertFalse(is_newer("0.1.0", "0.2.0"))
        self.assertFalse(is_newer("0.1.0", "0.1.0"))
        self.assertTrue(is_newer("1.10.0", "1.9.0"))          # 数值比较，非字符串
        self.assertFalse(is_newer("1.0.0-rc", "1.0.0"))       # 预发布低于正式版
        self.assertFalse(is_newer("", "0.1.0"))
        self.assertFalse(is_newer("0.2.0", "not-a-version"))

    def test_validate_update_url(self):
        self.assertEqual(validate_update_url(""), "")
        self.assertEqual(validate_update_url("http://host:8000/"), "http://host:8000")
        with self.assertRaises(ValueError):
            validate_update_url("ftp://host/x")
        with self.assertRaises(ValueError):
            validate_update_url("http://host/x?q=1")
        with self.assertRaises(ValueError):
            validate_update_url("http://user:pass@host/x")

    def test_resolve_base_url_priority(self):
        self.assertEqual(DEFAULT_UPDATE_BASE_URL, "")
        self.assertEqual(resolve_base_url("http://panel/x"), "http://panel/x")  # 面板优先
        with mock.patch.dict("os.environ", {"EXCEL_ASSISTANT_UPDATE_URL": "http://env.local/x"}):
            self.assertEqual(resolve_base_url(""), "http://env.local/x")  # 环境变量
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(resolve_base_url(""), "")  # 默认空


class CheckUpdateTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.manifest = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                outer.requests.append(self.path)
                if outer.manifest is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                if isinstance(outer.manifest, dict):
                    data = json.dumps(outer.manifest).encode("utf-8")
                else:
                    data = str(outer.manifest).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

        def _stop():
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=2)

        self.addCleanup(_stop)

    def _manifest(self, version):
        return {"name": "ExcelAssistant", "version": version,
                "published_at": "2026-09-20T10:00:00+08:00", "notes": "更新说明",
                "asset": {"url": f"ExcelAssistant-{version}.zip", "sha256": "abc", "size_bytes": 100}}

    def test_newer_available(self):
        self.manifest = self._manifest("0.2.0")
        result = check_update(self.base, "0.1.0")
        self.assertTrue(result["update_available"])
        self.assertEqual(result["latest_version"], "0.2.0")
        self.assertEqual(result["url"], self.base + "/ExcelAssistant-0.2.0.zip")

    def test_same_version_not_available(self):
        self.manifest = self._manifest("0.1.0")
        result = check_update(self.base, "0.1.0")
        self.assertFalse(result["update_available"])
        self.assertEqual(result["reason"], "已是最新版本")

    def test_absolute_asset_url(self):
        self.manifest = {"name": "ExcelAssistant", "version": "0.2.0",
                         "asset": {"url": "http://other.local/a.zip", "sha256": "", "size_bytes": 1}}
        result = check_update(self.base, "0.1.0")
        self.assertEqual(result["url"], "http://other.local/a.zip")

    def test_not_found(self):
        self.manifest = None
        result = check_update(self.base, "0.1.0")
        self.assertFalse(result["update_available"])
        self.assertIn("error", result)

    def test_bad_json(self):
        self.manifest = "{not json"
        result = check_update(self.base, "0.1.0")
        self.assertFalse(result["update_available"])
        self.assertIn("error", result)

    def test_empty_base_no_request(self):
        result = check_update("", "0.1.0")
        self.assertFalse(result["update_available"])
        self.assertEqual(result["reason"], "未配置更新服务地址")
        self.assertEqual(self.requests, [])  # 未发任何网络请求


if __name__ == "__main__":
    unittest.main()

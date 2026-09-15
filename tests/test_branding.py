"""Regression tests for resource reintroduction and desktop compatibility."""
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'vendor/ppx-py/src')]


class BrandingTests(unittest.TestCase):
    def test_bootstrap_excludes_artwork_but_preserves_licenses(self):
        from scripts import bootstrap_sources as bootstrap
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, 'w') as archive:
            archive.writestr('snapshot/ppx/assets/logo.png', b'old-logo')
            archive.writestr('snapshot/ppx/packages/ppx-py/src/ppx_py/template/assets/logo.ico', b'old-icon')
            archive.writestr('snapshot/ppx/packages/ppx-py/LICENSE', 'original license')
            archive.writestr('snapshot/ppx/packages/ppx-py/README.md',
                             '<p align="center"><img src="old.png" /></p>\n\n# ppx-py\nAPI\n'
                             '## 支持 PPX\n<img src="donation.png">\n## 开源协议\nAGPL-3.0-only\n')
        payload.seek(0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(bootstrap, 'ROOT', root), patch.object(bootstrap.urllib.request, 'urlopen', return_value=payload):
                bootstrap.fetch('fixture/repo', 'fixed', [('ppx/assets', 'ppx/assets'),
                                ('ppx/packages/ppx-py', 'vendor/ppx-py')],
                                exclude=bootstrap.PPX_EXCLUDED, clean_readmes=True)
            self.assertFalse((root / 'ppx/assets').exists())
            self.assertFalse((root / 'vendor/ppx-py/src').exists())
            self.assertEqual((root / 'vendor/ppx-py/LICENSE').read_text(), 'original license')
            readme = (root / 'vendor/ppx-py/README.md').read_text(encoding='utf-8')
            self.assertIn('AGPL-3.0-only', readme)
            self.assertIn('API', readme)
            self.assertNotIn('<img', readme)

    def test_missing_scaffold_fails_before_creating_directory(self):
        from ppx_py.scaffold import create_project
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'new-app'
            with self.assertRaisesRegex(RuntimeError, '不提供新项目模板'):
                create_project('Example', str(target))
            self.assertFalse(target.exists())

    def test_native_branding_keeps_legacy_title_default(self):
        from ppx_py.application import Application
        from ppx_py.settings import Settings
        import webview
        settings = Settings.load(ROOT / 'ppx.toml')
        screen = Mock(width=1600, height=1000)
        with patch.object(webview, 'screens', [screen]), patch.object(webview, 'create_window') as create, patch.object(webview, 'start') as start:
            app = Application(settings)
            app.run(dev=True)
            self.assertEqual(create.call_args.kwargs['title'], 'ExcelAssistant')
            self.assertIsNone(start.call_args.kwargs['icon'])
            app.run(dev=True, title='Excel 数据助手', icon=settings.asset_dir / 'logo.ico')
            self.assertEqual(create.call_args.kwargs['title'], 'Excel 数据助手')
            self.assertEqual(start.call_args.kwargs['icon'], str(settings.asset_dir / 'logo.ico'))
            self.assertEqual(start.call_args.kwargs['gui'], 'edgechromium')


if __name__ == '__main__':
    unittest.main()

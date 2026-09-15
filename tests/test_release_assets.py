import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from scripts.package_media import package_media
from scripts.source_archive import source_files, write_source_archive


class ReleaseAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        for name in ['README.md', 'THIRD_PARTY_NOTICES.md', 'docs/OFFLINE_ACCEPTANCE.md', 'gui/src/main.ts']:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic source\n', encoding='utf-8')
        subprocess.run(['git', '-C', str(self.root), 'add', '.'], check=True, capture_output=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_untracked_local_configuration_never_enters_archive(self):
        (self.root / 'gui/.env.local').write_text('fixture-only secret')
        (self.root / 'gui/local-settings.json').write_text('{"private":"fixture"}')
        target = self.root / 'source.zip'
        write_source_archive(self.root, target)
        with zipfile.ZipFile(target) as archive:
            self.assertIn('gui/src/main.ts', archive.namelist())
            self.assertNotIn('gui/.env.local', archive.namelist())
            self.assertNotIn('gui/local-settings.json', archive.namelist())
            self.assertIn('source-files.json', archive.namelist())

    def test_sensitive_file_rejected_even_if_tracked(self):
        (self.root / 'gui/.env.local').write_text('fixture-only secret')
        subprocess.run(['git', '-C', str(self.root), 'add', 'gui/.env.local'], check=True)
        with self.assertRaisesRegex(ValueError, '禁止归档'):
            source_files(self.root)

    def test_corresponding_source_rebuilds_without_git(self):
        target = self.root / 'source.zip'
        write_source_archive(self.root, target)
        unpacked = self.root / 'unpacked'
        with zipfile.ZipFile(target) as archive:
            archive.extractall(unpacked)
        self.assertEqual(len(source_files(unpacked)), 4)
        (unpacked / 'local-note.md').write_text('not tracked')
        write_source_archive(unpacked, unpacked / 'rebuilt.zip')
        with zipfile.ZipFile(unpacked / 'rebuilt.zip') as archive:
            self.assertNotIn('local-note.md', archive.namelist())

    def test_manifest_cannot_escape_source_root(self):
        unpacked = self.root / 'unpacked'
        unpacked.mkdir()
        (unpacked / 'source-files.json').write_text(json.dumps(['../README.md']))
        with self.assertRaisesRegex(ValueError, '越界'):
            source_files(unpacked)

    def test_sources_generated_without_webview_installer(self):
        for name in ('logo.svg', 'logo.png', 'logo.ico'):
            path = self.root / 'assets/branding' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'branding fixture')
        destination = self.root / 'build/ExcelAssistant'
        destination.mkdir(parents=True)
        (destination / 'ExcelAssistant.exe').write_bytes(b'test fixture, not an executable')
        self.assertFalse(package_media(self.root))
        self.assertTrue((destination / 'corresponding-source.zip').is_file())
        manifest = json.loads((destination / 'manifest.sha256.json').read_text())
        self.assertIn('corresponding-source.zip', manifest)
        self.assertEqual((destination / 'assets/branding/logo.svg').read_bytes(), b'branding fixture')
        self.assertTrue(any(name.replace('\\', '/') == 'assets/branding/logo.ico' for name in manifest))


if __name__ == '__main__':
    unittest.main()

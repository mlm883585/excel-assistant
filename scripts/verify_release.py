"""Verify that the portable media exactly corresponds to the current source and UI."""
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.source_archive import source_files
from scripts.verify_branding import verify_branding


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    bundle = ROOT / 'build/ExcelAssistant'
    manifest = json.loads((bundle / 'manifest.sha256.json').read_text(encoding='utf-8'))
    manifest_files = set()
    for name, expected in manifest.items():
        path = (bundle / name).resolve()
        if not path.is_relative_to(bundle.resolve()) or not path.is_file():
            raise ValueError(f'交付文件缺失或越界：{name}')
        if digest(path) != expected:
            raise ValueError(f'交付文件哈希不符：{name}')
        manifest_files.add(path.relative_to(bundle.resolve()).as_posix())
    actual = {path.relative_to(bundle).as_posix() for path in bundle.rglob('*')
              if path.is_file() and path.name != 'manifest.sha256.json'}
    if actual != manifest_files:
        raise ValueError(f'交付清单与实际文件不符：{sorted(actual ^ manifest_files)}')

    frontend = ROOT / 'gui/dist'
    packaged_frontend = bundle / '_internal/web'
    ui_files = {path.relative_to(frontend) for path in frontend.rglob('*') if path.is_file()}
    packaged_files = {path.relative_to(packaged_frontend) for path in packaged_frontend.rglob('*') if path.is_file()}
    if ui_files != packaged_files:
        raise ValueError('便携包包含缺失或遗留的前端资源')
    for name in ui_files:
        if digest(frontend / name) != digest(packaged_frontend / name):
            raise ValueError(f'便携包前端不是当前构建：{name}')

    sources = {path.relative_to(ROOT).as_posix(): path for path in source_files(ROOT)}
    with ZipFile(bundle / 'corresponding-source.zip') as archive:
        if set(archive.namelist()) != set(sources) | {'source-files.json'}:
            raise ValueError('对应源码归档与 Git 跟踪清单不一致')
        for name, path in sources.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != digest(path):
                raise ValueError(f'对应源码内容不是当前文件：{name}')

    licenses = json.loads((ROOT / 'vendor/licenses/gui/manifest.json').read_text(encoding='utf-8'))
    for package in licenses:
        if not package['files']:
            raise ValueError(f'运行依赖缺少许可证：{package["name"]}')
        for name in package['files']:
            packaged = bundle / name.removeprefix('vendor/')
            if not packaged.is_file() or digest(ROOT / name) != digest(packaged):
                raise ValueError(f'随包许可证缺失或不一致：{name}')
    result = {
        'passed': True, 'manifest_files': len(manifest), 'source_files': len(sources),
        'runtime_licenses': len(licenses), 'frontend_files': len(ui_files),
        'total_mib': round(sum((bundle / name).stat().st_size for name in manifest) / 1024 ** 2, 1),
        'offline_webview2_installer': (bundle / 'prerequisites/WebView2StandaloneX64.exe').is_file(),
        'branding': verify_branding(ROOT, bundle),
    }
    (ROOT / 'build/release-verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()

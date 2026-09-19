"""Bundle the offline material + source into a single transferable archive.

Produces build/offline-build-kit.zip containing:
  offline/                             (wheels + npm cache + node.exe + manifest.json)
  prerequisites/WebView2StandaloneX64.exe
  source/corresponding-source.zip

Copy this one file to the intranet to rebuild with zero network.
"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.source_archive import write_source_archive


def main():
    offline = ROOT / 'offline'
    if not (offline / 'manifest.json').is_file():
        raise SystemExit('Run scripts/refresh_offline.py first (offline/manifest.json missing).')

    target = ROOT / 'build' / 'offline-build-kit.zip'
    target.parent.mkdir(parents=True, exist_ok=True)

    temporary = target.with_suffix('.tmp.zip')
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(offline.rglob('*')):
                if path.is_file():
                    archive.write(path, path.relative_to(ROOT).as_posix())

            webview = ROOT / 'runtime' / 'WebView2StandaloneX64.exe'
            if webview.is_file():
                archive.write(webview, 'prerequisites/WebView2StandaloneX64.exe')
            else:
                print('warning: WebView2 installer missing; omitted from the kit')

            source_zip = ROOT / 'build' / 'cache' / 'kit-source.zip'
            source_zip.parent.mkdir(parents=True, exist_ok=True)
            write_source_archive(ROOT, source_zip)
            archive.write(source_zip, 'source/corresponding-source.zip')
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)

    print(target)


if __name__ == '__main__':
    main()

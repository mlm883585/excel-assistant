"""Regenerate the offline build kit: wheels + npm cache + node + WebView2.

Single entry point for keeping the offline material in sync with the lockfiles.
Run on an internet-connected Windows machine with Python 3.13 + Node 24.13.0.

After this, `scripts/check_offline.py` should pass.
"""
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OFFLINE = ROOT / 'offline'

# Files whose drift invalidates the offline kit.
MANIFEST_FILES = [
    'requirements.lock.txt',
    'requirements-optional.txt',
    'package-lock.json',
    'gui/package-lock.json',
]

SCRIPT_VERSION = '1'


def sha256(path):
    return hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()


def run_py(script):
    subprocess.run([sys.executable, str(ROOT / 'scripts' / script)], check=True, cwd=ROOT)


def run_ps(script):
    subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                    str(ROOT / 'scripts' / script)], check=True, cwd=ROOT)


def main():
    OFFLINE.mkdir(exist_ok=True)

    run_py('fetch_wheels.py')
    run_ps('fetch_npm_cache.ps1')
    run_ps('fetch_node.ps1')

    webview = ROOT / 'runtime' / 'WebView2StandaloneX64.exe'
    if not webview.is_file():
        print('WebView2 installer missing; downloading via fetch_webview2.ps1')
        run_ps('fetch_webview2.ps1')
    else:
        print('WebView2 installer already present')

    node_exe = OFFLINE / 'node' / 'node.exe'
    manifest = {
        'schema': 1,
        'script_version': SCRIPT_VERSION,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'files': {name: sha256(ROOT / name) for name in MANIFEST_FILES},
        'node_exe_sha256': sha256(node_exe) if node_exe.is_file() else None,
    }
    (OFFLINE / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Offline kit refreshed; manifest.json written')


if __name__ == '__main__':
    main()

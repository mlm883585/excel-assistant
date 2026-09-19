"""Verify the offline kit is present and in sync with the lockfiles.

Exit codes:
  0  kit is consistent, or not yet generated (nothing to compare against);
  1  drift detected: a lockfile changed after the kit was generated, or a kit
     asset is missing. Regenerate with scripts/refresh_offline.py.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OFFLINE = ROOT / 'offline'
MANIFEST = OFFLINE / 'manifest.json'

MANIFEST_FILES = [
    'requirements.lock.txt',
    'requirements-optional.txt',
    'package-lock.json',
    'gui/package-lock.json',
]

ASSETS = [
    OFFLINE / 'wheels',
    OFFLINE / 'npm',
    OFFLINE / 'node' / 'node.exe',
]


def sha256(path):
    return hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()


def main():
    if not MANIFEST.is_file():
        print('offline kit not generated yet (no offline/manifest.json); nothing to check.')
        return 0

    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    errors = []

    recorded = manifest.get('files', {})
    for name in MANIFEST_FILES:
        path = ROOT / name
        if not path.is_file():
            errors.append(f'manifest file missing: {name}')
            continue
        if recorded.get(name) != sha256(path):
            errors.append(f'{name} changed since the offline kit was generated')

    for asset in ASSETS:
        if not asset.exists():
            errors.append(f'offline asset missing: {asset.relative_to(ROOT)}')

    if errors:
        print('Offline kit is stale or incomplete:')
        for error in errors:
            print('  - ' + error)
        print('Run `python scripts/refresh_offline.py` on a connected machine to regenerate.')
        return 1

    print('Offline kit is up to date.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

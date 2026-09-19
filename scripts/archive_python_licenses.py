"""Extract license texts from every wheel in offline/wheels into vendor/licenses/python.

Run on the internet-connected machine after `scripts/refresh_offline.py` has populated
`offline/wheels/`. The wheels themselves are gitignored and only reach the offline
rebuild kit; the portable app freezes the Python packages into the EXE without their
license texts. This script archives those texts (and the SPDX/license field from each
wheel's METADATA) into a committed `vendor/licenses/python/` directory that
`scripts/package_media.py` copies into `build/ExcelAssistant/licenses/python/`.

License resolution order per wheel:
1. PEP 639 `*.dist-info/licenses/**` (recursive — preserves bundled third-party notices);
2. legacy `*.dist-info/LICENSE*` / `COPYING*` / `NOTICE*`;
3. a top-level `LICENSE*` / `COPYING*` at the wheel root (older sdists).
The declared SPDX expression (`License-Expression:`) or legacy `License:` line is also
recorded even when no license file is present, so the manifest stays a complete index.
"""
import json
import re
import shutil
import sys
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
WHEELHOUSE = ROOT / 'offline' / 'wheels'
TARGET = ROOT / 'vendor' / 'licenses' / 'python'

LICENSE_RE = re.compile(r'^(licen[sc]e|copying|notice)(\b|\.|-)', re.I)


def _dist_info(wheel: ZipFile):
    for name in wheel.namelist():
        if name.endswith('.dist-info/METADATA'):
            return name.rsplit('/', 1)[0]
    return None


def _metadata(wheel: ZipFile, dist_info: str):
    raw = wheel.read(f'{dist_info}/METADATA').decode('utf-8', 'replace')
    fields = {}
    for line in raw.splitlines():
        for key in ('Name', 'Version', 'License-Expression', 'License'):
            prefix = f'{key}:'
            if line.startswith(prefix):
                fields[key] = line[len(prefix):].strip()
    return fields


def _license_files(wheel: ZipFile, dist_info: str):
    """Return {archive_name: relative_path} for license files inside this wheel."""
    prefix = dist_info + '/'
    result = {}
    for name in wheel.namelist():
        if name.endswith('/') or not name.startswith(prefix):
            continue
        rel = name[len(prefix):]
        if rel.startswith('licenses/'):
            result[name] = rel
        elif '/' not in rel and LICENSE_RE.match(rel):
            result[name] = rel
    if result:
        return result
    for name in wheel.namelist():
        if name.endswith('/') or '/' in name:
            continue
        if LICENSE_RE.match(name):
            result[name] = name
    return result


def _safe(component: str) -> str:
    return re.sub(r'[^\w.+-]', '_', component)


def archive():
    if not WHEELHOUSE.is_dir() or not list(WHEELHOUSE.glob('*.whl')):
        raise SystemExit('缺少 offline/wheels/*.whl，请先运行 scripts/refresh_offline.py')
    TARGET.mkdir(parents=True, exist_ok=True)
    entries = []
    for wheel_path in sorted(WHEELHOUSE.glob('*.whl')):
        with ZipFile(wheel_path) as wheel:
            dist_info = _dist_info(wheel)
            if dist_info is None:
                entries.append({'name': wheel_path.name, 'version': '', 'license': '',
                                'source': '', 'files': [], 'error': 'no dist-info'})
                continue
            meta = _metadata(wheel, dist_info)
            name = meta.get('Name', '')
            version = meta.get('Version', '')
            declared = meta.get('License-Expression') or meta.get('License') or ''
            dest = TARGET / f'{_safe(name)}-{_safe(version)}' if name else None
            files = []
            if name and version:
                dest.mkdir(parents=True, exist_ok=True)
                for archive_name, rel in _license_files(wheel, dist_info).items():
                    target = dest / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(wheel.read(archive_name))
                    files.append(target.relative_to(ROOT).as_posix())
                # Some wheels declare a license but ship no license file; fall back
                # to a hand-authored supplement (same convention as the npm archive).
                if not files:
                    supplement = ROOT / 'vendor/licenses/supplements' / f'{name}.txt'
                    if supplement.is_file():
                        target = dest / 'LICENSE-UPSTREAM.txt'
                        shutil.copyfile(supplement, target)
                        files.append(target.relative_to(ROOT).as_posix())
            entries.append({'name': name or wheel_path.name, 'version': version,
                            'license': declared, 'source': f'offline/wheels/{wheel_path.name}',
                            'files': files})
    (TARGET / 'manifest.json').write_text(json.dumps(entries, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    no_license = [e['name'] for e in entries if not e['files']]
    print(json.dumps({
        'archive': TARGET.relative_to(ROOT).as_posix(),
        'packages': len(entries),
        'no_license_file': no_license,
    }, ensure_ascii=False))
    return entries


if __name__ == '__main__':
    archive()

"""Archive licenses from installed runtime npm packages in a package-lock.json.

Produces two archives:

* `vendor/licenses/gui/` — the frontend runtime deps pinned by gui/package-lock.json
  (dev and optional build-time packages excluded, as the shipped artifact is the
  compiled `gui/dist`, not the build toolchain);
* `vendor/licenses/cli/` — the bundled Qwen Code CLI (`@qwen-code/qwen-code`) and
  its transitive deps pinned by the root package-lock.json, including installed
  optional packages (sharp/@img/@emnapi) since the whole root `node_modules` tree
  is copied verbatim into the portable app.

Both archives are committed and later copied into `build/ExcelAssistant/licenses/`.
"""
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Match LICENSE / LICENCE / COPYING / NOTICE, case-insensitive, at a file-name start.
LICENSE_RE = re.compile(r'^(licen[sc]e|copying|notice)(\b|\.|-)', re.I)


def _archive(lockfile: Path, base_dir: Path, target: Path, include_optional: bool):
    lock = json.loads(lockfile.read_text(encoding='utf-8'))
    target.mkdir(parents=True, exist_ok=True)
    entries = []
    skipped_missing = []
    for relative, package in sorted(lock['packages'].items()):
        if not relative.startswith('node_modules/'):
            continue
        if package.get('dev'):
            continue
        if package.get('optional') and not include_optional:
            continue
        installed = base_dir / relative
        metadata_path = installed / 'package.json'
        # Platform-specific optional deps (e.g. @img/sharp-darwin-*) are absent on
        # this platform; they are not shipped, so there is nothing to archive.
        if not metadata_path.is_file():
            skipped_missing.append(relative)
            continue
        metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        name, version = metadata['name'], metadata['version']
        destination = target / (name.replace('/', '__') + '@' + version)
        destination.mkdir(exist_ok=True)
        files = []
        for path in sorted(installed.iterdir()):
            if path.is_file() and LICENSE_RE.match(path.name):
                shutil.copyfile(path, destination / path.name)
                files.append(str((destination / path.name).relative_to(ROOT)).replace('\\', '/'))
        if not files:
            for path in sorted(installed.iterdir()):
                if path.is_file() and path.name.lower() == 'readme.md':
                    text = path.read_text(encoding='utf-8')
                    match = re.search(r'^#+\s*license', text, re.I | re.M)
                    if match:
                        extracted = destination / 'LICENSE-FROM-README.md'
                        extracted.write_text(text[match.start():], encoding='utf-8')
                        files.append(extracted.relative_to(ROOT).as_posix())
                        break
            # Package metadata is retained when npm omitted a standalone license.
            shutil.copyfile(metadata_path, destination / 'package.json')
            supplement = ROOT / 'vendor/licenses/supplements' / (name.replace('/', '__') + '.txt')
            if supplement.is_file():
                shutil.copyfile(supplement, destination / 'LICENSE-UPSTREAM.txt')
                files.append((destination / 'LICENSE-UPSTREAM.txt').relative_to(ROOT).as_posix())
            if name == '@univerjs/protocol':
                core_license = base_dir / 'node_modules/@univerjs/core/LICENSE'
                if core_license.is_file():
                    shutil.copyfile(core_license, destination / 'LICENSE')
                    files.append((destination / 'LICENSE').relative_to(ROOT).as_posix())
        entries.append({
            'name': name, 'version': version,
            'license': metadata.get('license', package.get('license', '见组件元数据')),
            'source': metadata.get('repository', package.get('resolved', '')),
            'files': files,
        })
    (target / 'manifest.json').write_text(json.dumps(entries, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    missing = [e['name'] for e in entries if not e['files']]
    print(json.dumps({
        'archive': target.relative_to(ROOT).as_posix(),
        'packages': len(entries),
        'missing_license_files': missing,
        'skipped_missing': skipped_missing,
    }, ensure_ascii=False))
    return entries


def archive_gui():
    return _archive(ROOT / 'gui/package-lock.json', ROOT / 'gui',
                    ROOT / 'vendor/licenses/gui', include_optional=False)


def archive_cli():
    return _archive(ROOT / 'package-lock.json', ROOT,
                    ROOT / 'vendor/licenses/cli', include_optional=True)


if __name__ == '__main__':
    if '--cli' in sys.argv[1:]:
        archive_cli()
    else:
        archive_gui()

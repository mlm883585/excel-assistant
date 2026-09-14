"""Discover and pin an application-owned CLI/Node selection without changing installations."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

CLI_VERSION = '0.23.3'
VALIDATION_REVISION = 2


def app_root():
    return Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]


def resources_root():
    return Path(__file__).resolve().parents[1]


def frontend_entry():
    return resources_root() / ('web/index.html' if getattr(sys, 'frozen', False) else 'gui/dist/index.html')


def node_version(node):
    try:
        value = subprocess.check_output([str(node), '--version'], timeout=5, text=True,
                                        creationflags=0x08000000 if sys.platform == 'win32' else 0).strip()
        parts = value.removeprefix('v').split('.')
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            return None
        return value if int(parts[0]) >= 22 else None
    except (OSError, subprocess.SubprocessError):
        return None


def fingerprint(candidate):
    package = Path(candidate['cli']).parent
    digest = hashlib.sha256()
    # Content hashes cover the executable, entry points and package metadata;
    # the complete installed package inventory detects other upgrades/removals.
    for path in sorted(package.rglob('*')):
        if path.is_file():
            stat = path.stat()
            digest.update(f'{path.relative_to(package)}:{stat.st_size}:{stat.st_mtime_ns}'.encode())
    for path in [package / 'package.json', Path(candidate['cli']), Path(candidate['node_executable'])]:
        with path.open('rb') as stream:
            digest.update(hashlib.file_digest(stream, 'sha256').digest())
    digest.update(str(VALIDATION_REVISION).encode())
    return digest.hexdigest()


def candidate_at(location, node_paths, source, bundled_node=None):
    location = Path(location).expanduser().resolve()
    base = location.parent if location.is_file() else location
    packages = [base, base / 'node_modules/@qwen-code/qwen-code', base / '@qwen-code/qwen-code']
    results = []
    for package in packages:
        try:
            meta = json.loads((package / 'package.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict) or meta.get('name') != '@qwen-code/qwen-code':
            continue
        cli = package / 'cli.js'
        if not cli.is_file():
            continue
        nodes = list(dict.fromkeys(str(Path(n).resolve()) for n in node_paths if n and Path(n).is_file()))
        if bundled_node and Path(bundled_node).is_file() and str(Path(bundled_node).resolve()) not in nodes:
            nodes.append(str(Path(bundled_node).resolve()))
        # Include a visible failure candidate even when no Node can run it.
        for node in nodes or ['']:
            version = node_version(node) if node else None
            supported = meta.get('version') == CLI_VERSION and meta.get('engines', {}).get('node') == '>=22.0.0'
            key = hashlib.sha256(f'{cli.resolve()}|{node}'.encode()).hexdigest()[:20]
            results.append({'id': key, 'source': source, 'cli': str(cli.resolve()),
                            'node_executable': node, 'version': str(meta.get('version', '未知')),
                            'node_version': version or '不可用', 'compatible': bool(supported and version),
                            'reason': '待协议验证' if supported and version else 'CLI 版本尚未验证或 Node 不兼容',
                            'node_source': '内置' if bundled_node and node == str(Path(bundled_node).resolve()) else '本机'})
    return results


class RuntimeManager:
    def __init__(self, data_dir, root=None):
        self.data_dir = Path(data_dir)
        self.root = Path(root or app_root())
        self.path = self.data_dir / 'runtime-selection.json'
        self.candidates = {}
        self.validated = {}
        self.lock = threading.RLock()

    def discover(self, manual=None):
        bundled_node = self.root / 'runtime/node.exe'
        dev_node = shutil.which('node') if not getattr(sys, 'frozen', False) else None
        locations = []
        if manual:
            locations.append(Path(manual))
        locations.extend(Path(p) for p in os.environ.get('PATH', '').split(os.pathsep) if p)
        if os.environ.get('APPDATA'):
            locations.append(Path(os.environ['APPDATA']) / 'npm')
        nodes = [shutil.which('node')]
        found = []
        for location in dict.fromkeys(locations):
            adjacent = (location.parent if location.is_file() else location) / 'node.exe'
            found.extend(candidate_at(location, [adjacent, *nodes], '已有安装', bundled_node))
        found.extend(candidate_at(self.root / 'node_modules/@qwen-code/qwen-code',
                                  [bundled_node, dev_node], '随包版本', bundled_node))
        unique = {}
        for item in found:
            unique[item['id']] = item
        with self.lock:
            self.candidates.update(unique)
        return sorted(unique.values(), key=lambda c: (c['source'] == '随包版本', c['node_source'] == '内置', c['cli']))

    def validate(self, candidate_id, cancel=None):
        from .diagnostic_process import run_probe
        with self.lock:
            if candidate_id not in self.candidates:
                raise ValueError('候选运行环境已失效，请重新发现安装')
            candidate = dict(self.candidates[candidate_id])
            self.validated.pop(candidate_id, None)
        if not candidate['compatible']:
            raise ValueError(candidate['reason'])
        meta = json.loads((Path(candidate['cli']).parent / 'package.json').read_text(encoding='utf-8'))
        if meta.get('name') != '@qwen-code/qwen-code' or meta.get('version') != CLI_VERSION or not node_version(candidate['node_executable']):
            raise ValueError('候选安装在发现后发生变化或不再兼容，请重新发现安装')
        before = fingerprint(candidate)
        result = run_probe('agent', candidate, timeout=90, cancel=cancel)
        if result['status'] != 'pass':
            return result
        if fingerprint(candidate) != before:
            raise ValueError('检测期间运行文件发生变化，请重新检测')
        candidate.update(fingerprint=before, validation_revision=VALIDATION_REVISION)
        with self.lock:
            self.validated[candidate_id] = candidate
        return {**result, 'candidate': candidate}

    def select(self, candidate_id):
        with self.lock:
            candidate = self.validated.get(candidate_id)
            if not candidate or fingerprint(candidate) != candidate['fingerprint']:
                raise ValueError('请先完成该运行环境的协议验证')
            self.data_dir.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(self.path)
        return candidate

    def selected(self):
        try:
            candidate = json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            raise ValueError('尚未选择运行环境，请打开环境检测；优先验证已有 Qwen Code') from None
        except (OSError, ValueError):
            raise ValueError('运行环境记录损坏，请重新选择并验证') from None
        try:
            if candidate['validation_revision'] != VALIDATION_REVISION or candidate['version'] != CLI_VERSION or fingerprint(candidate) != candidate['fingerprint']:
                raise ValueError('已选运行环境发生变化，请重新验证；不会自动切换版本')
        except (OSError, KeyError, TypeError):
            raise ValueError('已选运行环境文件缺失，请重新检测；不会自动切换版本') from None
        return candidate

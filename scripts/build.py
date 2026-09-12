"""Build a portable Windows directory using PPX's spec generator."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor/ppx-py/src'))
sys.path.insert(0, str(ROOT))


def copy_changed(source, target):
    source, target = Path(source), Path(target)
    if not target.exists() or source.stat().st_size != target.stat().st_size or source.stat().st_mtime_ns != target.stat().st_mtime_ns:
        return shutil.copy2(source, target)
    return str(target)


def main():
    from ppx_py.settings import Settings
    from ppx_py.packaging.spec import create_spec
    subprocess.run(['npm.cmd', 'run', 'build', '--prefix', str(ROOT/'gui')], check=True)
    spec = create_spec(ROOT, Settings.load(ROOT/'ppx.toml'), False)
    # Keep PPX's collection model; replace only the app entry to retain our API restrictions.
    content = spec.read_text(encoding='utf-8')
    content = content.replace(str(ROOT/'build/cache/ppx_entry.py').__repr__(), str(ROOT/'main.py').__repr__())
    # PPX source is pinned locally, and pywebview/pythonnet require their managed assets.
    content = content.replace(f'pathex=[{str(ROOT)!r}]', f'pathex=[{str(ROOT)!r}, {str(ROOT / "vendor/ppx-py/src")!r}]')
    spec.write_text(content, encoding='utf-8')
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--distpath',str(ROOT/'build'),'--workpath',str(ROOT/'build/cache/work'),str(spec)],check=True,cwd=ROOT)
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--name','DataCraftMCP','--distpath',str(ROOT/'build/mcp'),'--workpath',str(ROOT/'build/cache/mcp'),'--specpath',str(ROOT/'build/cache'),'--paths',str(ROOT),str(ROOT/'mcp_entry.py')],check=True,cwd=ROOT)
    destination=ROOT/'build/ExcelAssistant'
    shutil.copytree(ROOT/'build/mcp/DataCraftMCP',destination/'mcp',dirs_exist_ok=True,copy_function=copy_changed)
    shutil.copytree(ROOT/'node_modules',destination/'node_modules',dirs_exist_ok=True,copy_function=copy_changed)
    runtime=destination/'runtime';runtime.mkdir(exist_ok=True)
    node=shutil.which('node')
    if not node:raise RuntimeError('Node executable missing')
    version=subprocess.check_output([node,'--version'],text=True).strip()
    if version!='v24.13.0':raise RuntimeError('Use pinned Node 24.13.0')
    shutil.copy2(node,runtime/'node.exe')
    for name in ['README.md','LICENSE','THIRD_PARTY_NOTICES.md']:
        shutil.copy2(ROOT/name,destination/name)
    for license_name in ['LICENSE','README.md']:
        shutil.copy2(ROOT/'vendor/ppx-py'/license_name,destination/f'PPX-{license_name}')
    shutil.copy2(ROOT/'vendor/QWEN-LICENSE',destination/'QWEN-LICENSE')
    shutil.copy2(ROOT/'vendor/NODE-LICENSE.txt',destination/'NODE-LICENSE.txt')
    shutil.copy2(ROOT/'docs/OFFLINE_ACCEPTANCE.md',destination/'OFFLINE_ACCEPTANCE.md')
    print('正在生成交付文件哈希清单',flush=True)
    manifest={}
    for p in destination.rglob('*'):
        if p.is_file() and p.name!='manifest.sha256.json':
            with p.open('rb') as stream:
                manifest[str(p.relative_to(destination))]=hashlib.file_digest(stream,'sha256').hexdigest()
    (destination/'manifest.sha256.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    from package_media import package_media
    package_media()
    print(destination)


if __name__=='__main__':main()

"""Attach the predownloaded Microsoft offline installer to a portable build."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import os
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.source_archive import write_source_archive


def verify_media(source):
    # Signature verification is done without executing the installer.
    shell=shutil.which('pwsh') or 'powershell.exe'
    quoted=str(source).replace("'", "''")
    command=f"$signature=Get-AuthenticodeSignature -LiteralPath '{quoted}'; if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') {{ exit 2 }}; 'Valid'"
    result=subprocess.check_output([shell,'-NoProfile','-Command',command],text=True,env={k:v for k,v in os.environ.items() if k.upper()!='PSMODULEPATH'}).strip()
    if result!='Valid':raise RuntimeError('WebView2 installer signature is not valid')


def package_media(root=None):
    root=Path(root or ROOT)
    source=root/'runtime/WebView2StandaloneX64.exe'
    destination=root/'build/ExcelAssistant'
    if not (destination/'ExcelAssistant.exe').is_file():
        raise ValueError('请先构建 Windows 应用，再附加交付资料')
    manifest_path=destination/'manifest.sha256.json'
    manifest=json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    updated=[]
    if source.exists():
        verify_media(source)
        target=destination/'prerequisites/WebView2StandaloneX64.exe'
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(source,target)
        updated.append(target)
    else:
        print('未附加 WebView2 离线安装包；对应源码仍正常归档')
    for name in ['README.md','THIRD_PARTY_NOTICES.md']:
        shutil.copy2(root/name,destination/name)
        updated.append(destination/name)
    shutil.copy2(root/'docs/OFFLINE_ACCEPTANCE.md',destination/'OFFLINE_ACCEPTANCE.md')
    updated.append(destination/'OFFLINE_ACCEPTANCE.md')
    if (root/'docs/ENVIRONMENT.md').is_file():
        shutil.copy2(root/'docs/ENVIRONMENT.md',destination/'ENVIRONMENT.md')
        updated.append(destination/'ENVIRONMENT.md')
    for name in ['WORKBENCH.md', 'PERFORMANCE.md', 'WORKBOOK_EDITOR.md', 'VALIDATION.md']:
        if (root/'docs'/name).is_file():
            shutil.copy2(root/'docs'/name, destination/name)
            updated.append(destination/name)
    # Preserve relative README/documentation links without copying local snapshots.
    public_docs = ['WORKBENCH.md', 'PERFORMANCE.md', 'WORKBOOK_EDITOR.md', 'VALIDATION.md',
                   'ENVIRONMENT.md', 'OFFLINE_ACCEPTANCE.md', 'REPOSITORY_HYGIENE.md', 'BRANDING.md',
                   'screenshots/workbench.png', 'screenshots/review.png', 'screenshots/editor.png']
    for name in public_docs:
        original = root / 'docs' / name
        if original.is_file():
            target = destination / 'docs' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
            updated.append(target)
    for name in ('logo.svg', 'logo.png', 'logo.ico'):
        target = destination / 'assets/branding' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / 'assets/branding' / name, target)
        updated.append(target)
    # Third-party license archives: frontend npm, bundled CLI npm, and Python wheels.
    for src_subdir, dst_subdir in [('vendor/licenses/gui', 'licenses/gui'),
                                   ('vendor/licenses/cli', 'licenses/cli'),
                                   ('vendor/licenses/python', 'licenses/python')]:
        if (root/src_subdir).is_dir():
            shutil.copytree(root/src_subdir, destination/dst_subdir, dirs_exist_ok=True)
            updated.extend(p for p in (destination/dst_subdir).rglob('*') if p.is_file())
    # WebView2 Runtime is redistributed under Microsoft's installer EULA; ship a notice.
    webview2_notice = root/'vendor/licenses/supplements/webview2.txt'
    if webview2_notice.is_file():
        notice_target = destination/'licenses/webview2/NOTICE.txt'
        notice_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(webview2_notice, notice_target)
        updated.append(notice_target)
    source_archive=destination/'corresponding-source.zip'
    write_source_archive(root,source_archive)
    updated.append(source_archive)
    for path in updated:
        with path.open('rb') as stream:
            manifest[str(path.relative_to(destination))]=hashlib.file_digest(stream,'sha256').hexdigest()
    manifest_path.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('RELEASE_ASSETS_OK')
    return source.exists()


if __name__=='__main__':package_media()

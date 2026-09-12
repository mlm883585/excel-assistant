"""Attach the predownloaded Microsoft offline installer to a portable build."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile
import os

ROOT=Path(__file__).resolve().parents[1]


def package_media():
    source=ROOT/'runtime/WebView2StandaloneX64.exe'
    if not source.exists():
        print('WebView2 离线介质未提供；执行 scripts/fetch_webview2.ps1 后重新附加')
        return False
    # Signature verification is done without executing the installer.
    shell=shutil.which('pwsh') or 'powershell.exe'
    quoted=str(source).replace("'", "''")
    command=f"$signature=Get-AuthenticodeSignature -LiteralPath '{quoted}'; if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') {{ exit 2 }}; 'Valid'"
    result=subprocess.check_output([shell,'-NoProfile','-Command',command],text=True,env={k:v for k,v in os.environ.items() if k.upper()!='PSMODULEPATH'}).strip()
    if result!='Valid':raise RuntimeError('WebView2 installer signature is not valid')
    destination=ROOT/'build/ExcelAssistant'
    target=destination/'prerequisites/WebView2StandaloneX64.exe'
    target.parent.mkdir(exist_ok=True)
    shutil.copy2(source,target)
    manifest_path=destination/'manifest.sha256.json'
    manifest=json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    updated=[target]
    for name in ['README.md','THIRD_PARTY_NOTICES.md']:
        shutil.copy2(ROOT/name,destination/name)
        updated.append(destination/name)
    shutil.copy2(ROOT/'docs/OFFLINE_ACCEPTANCE.md',destination/'OFFLINE_ACCEPTANCE.md')
    updated.append(destination/'OFFLINE_ACCEPTANCE.md')
    source_archive=destination/'corresponding-source.zip'
    files=[ROOT/name for name in ['main.py','mcp_entry.py','ppx.toml','requirements.txt','requirements.lock.txt','package.json','package-lock.json','LICENSE','THIRD_PARTY_NOTICES.md','README.md','AGENTS.md']]
    for folder in ['assistant','api','data_toolkit','vendor','scripts','tests','ppx/assets','gui/src']:
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    files.extend(p for p in (ROOT/'gui').iterdir() if p.is_file())
    files.extend(ROOT/'docs'/name for name in ['IMPLEMENTATION.md','OFFLINE_ACCEPTANCE.md','VALIDATION.md'])
    with zipfile.ZipFile(source_archive,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(files)):
            archive.write(path,str(path.relative_to(ROOT)))
    updated.append(source_archive)
    for path in updated:
        with path.open('rb') as stream:
            manifest[str(path.relative_to(destination))]=hashlib.file_digest(stream,'sha256').hexdigest()
    manifest_path.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('WEBVIEW2_OFFLINE_MEDIA_OK')
    return True


if __name__=='__main__':package_media()

"""Read-only deployment checks; no installation or outbound requests."""
import importlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
checks={"python":platform.python_version(),"platform":platform.platform()}
for module in ['pandas','openpyxl','xlsxwriter','mcp','qwen_code_sdk','webview','clr','psutil']:
    try:importlib.import_module(module);checks[module]='OK'
    except ImportError as exc:checks[module]=str(exc)
node=shutil.which('node')
checks['node']=subprocess.check_output([node,'--version'],text=True).strip() if node else 'MISSING'
cli=ROOT/'node_modules/@qwen-code/qwen-code/cli.js'
checks['qwen_cli']=subprocess.check_output([node,str(cli),'--version'],text=True).strip() if node and cli.exists() else 'MISSING'
checks['frontend']=(ROOT/'gui/dist/index.html').is_file()
if sys.platform=='win32':
    import winreg
    versions=[]
    for hive,path in [(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'),(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}')]:
        try:
            with winreg.OpenKey(hive,path) as key:versions.append(winreg.QueryValueEx(key,'pv')[0])
        except FileNotFoundError:pass
    checks['WebView2']=versions or 'NOT DETECTED: install offline standalone runtime'
print(json.dumps(checks,ensure_ascii=False,indent=2))

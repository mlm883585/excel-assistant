"""Shared startup, desktop and command-line environment checks."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import struct
import sys
import tempfile

from .runtime import app_root, frontend_entry
from .store import data_root


def item(name, status, message, impact='', action=''):
    return {'name': name, 'status': status, 'message': message, 'impact': impact, 'action': action}


def registry_value(hive, path, name, view=0):
    import winreg
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view) as key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def platform_checks():
    checks = []
    supported = sys.platform == 'win32' and struct.calcsize('P') == 8 and platform.machine().upper() in {'AMD64', 'X86_64'}
    if sys.platform == 'win32':
        supported = supported and sys.getwindowsversion().major >= 10
    checks.append(item('Windows / 架构', 'pass' if supported else 'fail', platform.platform(), '桌面启动', '使用 Windows 10/11 x64 交付环境'))
    if sys.platform != 'win32':
        return checks
    import winreg
    versions = []
    for hive in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
        for view in [winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY]:
            value = registry_value(hive, r'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', view)
            if isinstance(value, str):
                parts = value.split('.')
                if len(parts) == 4 and all(p.isdigit() for p in parts) and int(parts[0]) >= 86:
                    versions.append(value)
    checks.append(item('WebView2', 'pass' if versions else 'fail', ', '.join(sorted(set(versions))) or '未检测到可用运行时', '桌面启动', '安装随包 WebView2 后重新启动'))
    release = registry_value(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', 'Release', winreg.KEY_WOW64_64KEY)
    checks.append(item('.NET Framework', 'pass' if isinstance(release, int) and release >= 394802 else 'fail', f'Release: {release or "未检测到"}', '桌面启动', '由 IT 检查 .NET Framework 4.6.2 或更高版本'))
    return checks


def excel_installed():
    if sys.platform != 'win32':
        return False
    import winreg
    return any(registry_value(winreg.HKEY_CLASSES_ROOT, r'Excel.Application\CLSID', '', view) for view in [winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY])


def storage_check(root=None):
    root = Path(root or data_root())
    try:
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='environment-', dir=root) as folder:
            test = Path(folder) / 'probe.txt'
            test.write_text('environment-check', encoding='utf-8')
            if test.read_text(encoding='utf-8') != 'environment-check':
                raise OSError('read mismatch')
            db = sqlite3.connect(Path(folder) / 'probe.sqlite')
            try:
                db.execute('CREATE TABLE probe(value TEXT)')
                db.execute("INSERT INTO probe VALUES ('ok')")
                db.commit()
                if db.execute('SELECT value FROM probe').fetchone()[0] != 'ok':
                    raise OSError('database mismatch')
            finally:
                db.close()
        free = shutil.disk_usage(root).free // (1024 * 1024)
        return item('数据目录', 'pass', f'文件与 SQLite 读写通过；剩余 {free} MiB', '任务执行')
    except (OSError, sqlite3.Error):
        return item('数据目录', 'fail', '数据目录不可写或数据库读写失败', '任务执行', '由 IT 检查目录权限、磁盘空间与安全软件策略')


def report(checks):
    return {'checked_at': datetime.now(timezone.utc).isoformat(), 'checks': checks,
            'status': 'fail' if any(c['status'] == 'fail' for c in checks) else 'warn' if any(c['status'] in {'warn', 'untested'} for c in checks) else 'pass'}


def local_check(manager=None, deep=True, cancel=None):
    checks = platform_checks()
    frontend = frontend_entry()
    checks.append(item('界面资源', 'pass' if frontend.is_file() else 'fail', '资源完整' if frontend.is_file() else '缺少界面资源', '桌面启动', '开发环境先构建前端；客户重新解压完整交付包'))
    checks.append(storage_check())
    checks.append(item('模型连接', 'untested', '连接测试由用户手动触发，不在启动时发送请求', 'AI 任务', '保存模型设置后点击测试模型连接'))
    checks.append(item('Python', 'pass', f'{platform.python_version()}（{"随包" if getattr(sys, "frozen", False) else "当前开发环境"}）'))
    if deep:
        from .diagnostic_process import run_probe
        dependencies = run_probe('dependencies', timeout=20, cancel=cancel)
        checks.append(item('应用组件', dependencies['status'], dependencies['message'], '相关数据或 Agent 功能', '重新解压完整交付包'))
    installed = excel_installed()
    checks.append(item('Excel', 'pass' if installed else 'warn', '已注册；COM 能力需点击测试' if installed else '未检测到 Excel 注册信息', '原生重算；基础文件处理不受影响', '由 IT 检查 Excel 安装'))
    if manager:
        try:
            selected = manager.selected()
            checks.append(item('Agent 运行环境', 'pass', f"{selected['source']} · CLI {selected['version']} · Node {selected['node_version']}"))
        except ValueError as exc:
            checks.append(item('Agent 运行环境', 'warn', str(exc), 'AI 任务；常用操作仍可执行', '发现运行环境并完成协议验证'))
    return report(checks)


def require_storage():
    result = storage_check()
    if result['status'] != 'pass':
        raise ValueError(result['message'] + '；' + result['action'])


def native_message(message, question=False):
    import ctypes
    return ctypes.windll.user32.MessageBoxW(None, message, 'Excel 数据助手 · 环境检测', 0x24 if question else 0x10)


def startup_check():
    checks = local_check(deep=False)['checks']
    failures = [c for c in checks if c['status'] == 'fail' and c['impact'] == '桌面启动']
    if not failures:
        return True
    if sys.platform == 'win32':
        message = '\n\n'.join(f"{c['name']}：{c['message']}\n{c['action']}" for c in failures)
        webview_missing = any(c['name'] == 'WebView2' for c in failures)
        if webview_missing and native_message(message + '\n\n现在启动随包 WebView2 离线安装程序？可能需要管理员权限。', True) == 6:
            from .windows_repair import install_webview
            try:
                result = install_webview(app_root())
                remaining = [c for c in platform_checks() if c['status'] == 'fail']
                native_message(result['message'] + ('；请修复剩余环境问题后重新打开软件' if remaining else '；环境已就绪，请重新打开软件'))
            except (ValueError, OSError) as exc:
                native_message(str(exc))
        elif not webview_missing:
            native_message(message)
    return False


def export_report(value):
    # Export an allowlisted projection, never paths/configuration/payloads.
    checks = []
    for check in value.get('checks', []):
        checks.append({k: str(check.get(k, '')) for k in ['name', 'status', 'message', 'impact', 'action']})
    import re
    def redact(text):
        text = re.sub(r'https?://[^\s，；）]+', '[内网地址]', text)
        text = re.sub(r'(?i)(?:[a-z]:[\\/]|\\\\)[^\n，；]*', '[本机路径]', text)
        for secret in [os.environ.get('EXCEL_ASSISTANT_API_KEY'), os.environ.get('USERNAME')]:
            if secret:
                text = text.replace(secret, '[已脱敏]')
        return text
    safe = {'checked_at': value.get('checked_at', ''), 'checks': [{k: redact(v) for k, v in c.items()} for c in checks]}
    return safe, '\n\n'.join(f"{c['name']} [{c['status']}]\n{c['message']}\n影响：{c['impact']}\n建议：{c['action']}" for c in safe['checks'])

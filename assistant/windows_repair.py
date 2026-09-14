"""Offline-only trust verification and a fixed WebView2 installer action."""
import ctypes
from ctypes import wintypes as w
import hashlib
import json
from pathlib import Path
import subprocess
import threading
import uuid

_install_lock = threading.Lock()


def verify_microsoft_signature(path):
    class FileInfo(ctypes.Structure):
        _fields_ = [('size', w.DWORD), ('path', w.LPCWSTR), ('handle', w.HANDLE), ('subject', ctypes.c_void_p)]
    class TrustData(ctypes.Structure):
        _fields_ = [('size', w.DWORD), ('policy', ctypes.c_void_p), ('sip', ctypes.c_void_p),
                    ('ui', w.DWORD), ('revocation', w.DWORD), ('choice', w.DWORD), ('file', ctypes.POINTER(FileInfo)),
                    ('action', w.DWORD), ('state', w.HANDLE), ('url', w.LPCWSTR), ('flags', w.DWORD),
                    ('context', w.DWORD), ('signature', ctypes.c_void_p)]
    trust = ctypes.WinDLL('wintrust', use_last_error=True)
    trust.WinVerifyTrust.argtypes = [w.HWND, ctypes.c_void_p, ctypes.POINTER(TrustData)]
    trust.WinVerifyTrust.restype = ctypes.c_long
    guid = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID('00aac56b-cd44-11d0-8cc2-00c04fc295ee').bytes_le)
    info = FileInfo(ctypes.sizeof(FileInfo), str(path), None, None)
    data = TrustData()
    data.size, data.ui, data.choice, data.file = ctypes.sizeof(data), 2, 1, ctypes.pointer(info)
    data.flags = 0x1000  # WTD_CACHE_ONLY_URL_RETRIEVAL; no AIA/CRL network retrieval.
    data.action = 1
    try:
        code = trust.WinVerifyTrust(None, ctypes.byref(guid), ctypes.byref(data))
        if code:
            raise ValueError(f'无法通过离线签名校验（0x{code & 0xffffffff:08X}），请由 IT 核对证书与安装介质')
    finally:
        data.action = 2
        trust.WinVerifyTrust(None, ctypes.byref(guid), ctypes.byref(data))

    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    crypt.CryptQueryObject.argtypes = [w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.DWORD,
                                      ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.POINTER(w.HANDLE), ctypes.POINTER(w.HANDLE), ctypes.c_void_p]
    crypt.CryptMsgGetParam.argtypes = [w.HANDLE, w.DWORD, w.DWORD, ctypes.c_void_p, ctypes.POINTER(w.DWORD)]
    crypt.CertFindCertificateInStore.argtypes = [w.HANDLE, w.DWORD, w.DWORD, w.DWORD, ctypes.c_void_p, ctypes.c_void_p]
    crypt.CertFindCertificateInStore.restype = ctypes.c_void_p
    crypt.CertGetNameStringW.argtypes = [ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.c_void_p, w.LPWSTR, w.DWORD]
    crypt.CertFreeCertificateContext.argtypes = [ctypes.c_void_p]
    crypt.CertCloseStore.argtypes = [w.HANDLE, w.DWORD]
    crypt.CryptMsgClose.argtypes = [w.HANDLE]
    store, message, cert = w.HANDLE(), w.HANDLE(), None
    try:
        if not crypt.CryptQueryObject(1, ctypes.c_wchar_p(str(path)), 1 << 10, 2, 0, None, None, None, ctypes.byref(store), ctypes.byref(message), None):
            raise ValueError('无法读取安装程序签名')
        size = w.DWORD()
        if not crypt.CryptMsgGetParam(message, 7, 0, None, ctypes.byref(size)):
            raise ValueError('无法读取签名者证书')
        buffer = ctypes.create_string_buffer(size.value)
        if not crypt.CryptMsgGetParam(message, 7, 0, buffer, ctypes.byref(size)):
            raise ValueError('无法读取签名者证书')
        cert = crypt.CertFindCertificateInStore(store, 0x10001, 0, 0x000b0000, buffer, None)
        if not cert:
            raise ValueError('缺少签名者证书')
        name = ctypes.create_unicode_buffer(512)
        crypt.CertGetNameStringW(cert, 3, 0, ctypes.c_char_p(b'2.5.4.10'), name, len(name))
        if name.value != 'Microsoft Corporation':
            raise ValueError('安装程序签名者不是 Microsoft Corporation')
    finally:
        if cert:
            crypt.CertFreeCertificateContext(cert)
        if message:
            crypt.CryptMsgClose(message)
        if store:
            crypt.CertCloseStore(store, 0)


def installer_path(root):
    root = Path(root).resolve()
    target = root / 'prerequisites/WebView2StandaloneX64.exe'
    if not target.is_file() or not target.resolve().is_relative_to(root) or target.is_symlink():
        raise ValueError('缺少随包 WebView2 离线安装介质，请由 IT 提供完整交付包')
    manifest = json.loads((root / 'manifest.sha256.json').read_text(encoding='utf-8'))
    expected = manifest.get(str(target.relative_to(root))) or manifest.get(target.relative_to(root).as_posix())
    with target.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if not expected or expected != actual:
        raise ValueError('安装介质哈希不符，请重新获取完整交付包')
    verify_microsoft_signature(target)
    return target


def install_webview(root):
    if not _install_lock.acquire(blocking=False):
        raise ValueError('WebView2 安装正在进行，请勿重复启动')
    try:
        target = installer_path(root)
        try:
            try:
                process = subprocess.Popen([str(target), '/install'], shell=False)
                code = process.wait()
            except OSError as exc:
                if getattr(exc, 'winerror', None) != 740:
                    raise
                code = elevated_install(target)
        except OSError as exc:
            if getattr(exc, 'winerror', None) in {5, 740, 1223}:
                raise ValueError('安装被取消或需要管理员权限，请由 IT 运行随包安装程序') from None
            raise ValueError('安装程序无法启动，请由 IT 检查系统策略') from None
        return {'status': 'pass' if code == 0 else 'warn', 'message': f'安装程序已退出（代码 {code}），请以重新检测结果为准', 'code': str(code)}
    finally:
        _install_lock.release()


def elevated_install(target):
    """Only the already verified fixed installer can reach this UAC action."""
    class ExecuteInfo(ctypes.Structure):
        _fields_ = [('size', w.DWORD), ('mask', ctypes.c_ulong), ('window', w.HWND), ('verb', w.LPCWSTR),
                    ('file', w.LPCWSTR), ('parameters', w.LPCWSTR), ('directory', w.LPCWSTR), ('show', ctypes.c_int),
                    ('instance', w.HINSTANCE), ('idlist', ctypes.c_void_p), ('class_name', w.LPCWSTR),
                    ('class_key', w.HKEY), ('hotkey', w.DWORD), ('icon', w.HANDLE), ('process', w.HANDLE)]
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ExecuteInfo)]
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    info = ExecuteInfo()
    info.size, info.mask, info.verb, info.file = ctypes.sizeof(info), 0x40 | 0x100, 'runas', str(target)
    info.parameters, info.show = '/install', 1
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        kernel.WaitForSingleObject(info.process, 0xffffffff)
        code = w.DWORD()
        if not kernel.GetExitCodeProcess(info.process, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value
    finally:
        kernel.CloseHandle(info.process)

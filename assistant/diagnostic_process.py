"""Bounded diagnostic workers, separate from customer tasks and processes."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


class ProcessJob:
    def __init__(self):
        self.handle = None
        if sys.platform != 'win32':
            return
        class Basic(ctypes.Structure):
            _fields_ = [('user', ctypes.c_int64), ('job', ctypes.c_int64), ('flags', wintypes.DWORD),
                        ('min', ctypes.c_size_t), ('max', ctypes.c_size_t), ('active', wintypes.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ['r', 'w', 'o', 'rb', 'wb', 'ob']]
        class Limits(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_memory', ctypes.c_size_t),
                        ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        limits = Limits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.handle or not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise OSError('无法创建检测进程隔离容器')

    def assign(self, process):
        if self.handle and not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise OSError('无法将检测进程加入隔离容器')

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def cleanup_excel(folder):
    marker = Path(folder) / 'excel-owner.json'
    if not marker.exists():
        return
    import psutil
    try:
        owner = json.loads(marker.read_text())
        process = psutil.Process(owner['pid'])
        if process.name().lower() == 'excel.exe' and abs(process.create_time() - owner['created']) < 0.01:
            process.kill()
            process.wait(5)
    except (psutil.NoSuchProcess, psutil.TimeoutExpired, OSError, ValueError, KeyError):
        pass


def run_probe(kind, payload=None, timeout=15, cancel=None):
    from .runtime import resources_root
    with tempfile.TemporaryDirectory(prefix='excel-assistant-check-') as folder:
        root = Path(folder)
        (root / 'request.json').write_text(json.dumps({'kind': kind, 'payload': payload or {}}), encoding='utf-8')
        command = [sys.executable]
        if not getattr(sys, 'frozen', False):
            command.append(str(resources_root() / 'main.py'))
        command += ['--diagnostic-worker', str(root)]
        job = ProcessJob()
        process = None
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, creationflags=0x08000000 if sys.platform == 'win32' else 0)
            job.assign(process)
            (root / 'ready').touch()  # Worker cannot spawn descendants before assignment.
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if cancel is not None and cancel.is_set():
                    return {'status': 'cancelled', 'message': '检测已取消', 'code': 'cancelled'}
                if time.monotonic() >= deadline:
                    return {'status': 'fail', 'message': f'检测超过 {timeout} 秒，已停止检测进程', 'code': 'timeout'}
                time.sleep(0.05)
            result = root / 'result.json'
            if process.returncode or not result.is_file():
                return {'status': 'fail', 'message': '检测进程启动或组件加载失败，请检查完整交付包', 'code': 'worker_failed'}
            return json.loads(result.read_text(encoding='utf-8'))
        finally:
            if process is not None:
                if sys.platform != 'win32' and process.poll() is None:
                    import psutil
                    try:
                        children = psutil.Process(process.pid).children(recursive=True)
                        for child in children:
                            child.kill()
                    except psutil.NoSuchProcess:
                        pass
                job.close()
                if process.poll() is None:
                    process.kill()
                process.wait(5)
            else:
                job.close()
            cleanup_excel(root)


def worker_main(folder):
    root = Path(folder)
    deadline = time.monotonic() + 10
    while not (root / 'ready').exists():
        if time.monotonic() > deadline:
            return 2
        time.sleep(0.02)
    request = json.loads((root / 'request.json').read_text(encoding='utf-8'))
    try:
        from .probes import probe, ProbeFailure
        result = probe(request['kind'], request['payload'], root)
    except Exception as exc:
        result = {'status': 'fail', 'message': '组件检测失败，请检查安装文件和兼容版本', 'code': type(exc).__name__}
        # A bounded diagnostic code is safe to export; never include model bodies or secrets.
        if isinstance(exc, ImportError):
            result['message'] = '缺少检测依赖，请重新解压交付包或重新安装固定开发依赖'
        elif type(exc).__name__ == 'ProbeFailure':
            result.update(code=exc.code, message=str(exc))
    (root / 'result.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return 0

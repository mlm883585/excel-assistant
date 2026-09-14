"""Desktop entry; the PPX bridge exposes only application-owned methods."""
import multiprocessing
from pathlib import Path
import sys
import os

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor/ppx-py/src"))


def main():
    if '--diagnostic-worker' in sys.argv:
        from assistant.diagnostic_process import worker_main
        return worker_main(sys.argv[sys.argv.index('--diagnostic-worker') + 1])
    from assistant.diagnostics import startup_check
    if not startup_check():
        return 1
    from ppx_py.runtime import create_application
    from ppx_py.settings import Settings
    import webview

    app = create_application(Settings.load(ROOT / "ppx.toml"))
    # Disable broad upstream file/storage/update methods in this task-oriented UI.
    from ppx_py.bridge import Bridge
    from api import api
    app.bridge = Bridge()
    app.register_api(api)
    import atexit
    atexit.register(api.shutdown)
    if '--smoke' in sys.argv:
        original = app._on_shown
        def smoke(*args):
            original(*args)
            import threading
            def check():
                import time
                time.sleep(3)
                app.window.evaluate_js("document.title")
                from assistant.store import data_root
                data_root().mkdir(parents=True, exist_ok=True)
                (data_root() / 'desktop-smoke.ok').write_text('WebView2 window loaded', encoding='utf-8')
                print('DESKTOP_SMOKE_OK', flush=True)
                app.window.destroy()
            threading.Thread(target=check, daemon=True).start()
        app._on_shown = smoke
    app.run(dev="--dev" in sys.argv)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        sys.exit(main() or 0)
    except Exception:
        if sys.platform == 'win32' and '--diagnostic-worker' not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, '应用组件加载或启动失败。请重新解压完整交付包，并按随包排障说明检查依赖。', 'Excel 数据助手', 0x10)
        raise

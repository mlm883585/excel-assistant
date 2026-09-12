"""Desktop entry; the PPX bridge exposes only application-owned methods."""
import multiprocessing
from pathlib import Path
import sys
import os

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor/ppx-py/src"))
if getattr(sys, "frozen", False):
    # Windows resolves executable names using the parent's PATH, not only the
    # environment passed to CreateProcess. Include the bundled Node before spawn.
    os.environ["PATH"] = str(Path(sys.executable).parent / "runtime") + os.pathsep + os.environ.get("PATH", "")


def main():
    from ppx_py.runtime import create_application
    from ppx_py.settings import Settings
    from api.api import services
    import webview

    app = create_application(Settings.load(ROOT / "ppx.toml"))
    # Disable broad upstream file/storage/update methods in this task-oriented UI.
    from ppx_py.bridge import Bridge
    from api import api
    app.bridge = Bridge()
    app.register_api(api)
    store, jobs = services()
    import atexit
    atexit.register(jobs.close)
    if '--smoke' in sys.argv:
        original = app._on_shown
        def smoke(*args):
            original(*args)
            import threading
            def check():
                import time
                time.sleep(3)
                app.window.evaluate_js("document.title")
                (store.root / 'desktop-smoke.ok').write_text('WebView2 window loaded', encoding='utf-8')
                print('DESKTOP_SMOKE_OK', flush=True)
                app.window.destroy()
            threading.Thread(target=check, daemon=True).start()
        app._on_shown = smoke
    app.run(dev="--dev" in sys.argv)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()

"""Verify the actual bundled multiprocessing entry and cached pages."""
import json
import multiprocessing
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from assistant.preview import PreviewService
    from assistant.store import Store
    exe = ROOT / 'build/ExcelAssistant/ExcelAssistant.exe'
    with tempfile.TemporaryDirectory(prefix='excel-preview-') as directory:
        folder = Path(directory)
        source = folder / '业务 表.csv'
        source.write_text('编码,数量\n' + ''.join(f'{i:08d},NA\n' for i in range(100000)), encoding='utf-8-sig')
        store = Store(folder / 'state'); task = store.create()['id']; info = store.import_file(task, source)
        service = PreviewService(store)
        previous = multiprocessing.spawn.get_executable()
        try:
            started = time.perf_counter(); first = None
            # The test parent runs in a venv. Disable its cached redirect-to-base-Python
            # branch so the child really launches the frozen application executable.
            with patch.object(sys, 'executable', str(exe)), patch.object(sys, 'frozen', True, create=True), patch('multiprocessing.popen_spawn_win32.WINENV', False), patch('multiprocessing.spawn.WINEXE', True):
                multiprocessing.set_executable(str(exe))
                key = service.start(task, {'file_id':info['id'], 'sheet':0, 'header_row':1})['preview_id']
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                value = service.page(key)
                if value.get('rows') and first is None:
                    first = round(time.perf_counter() - started, 3)
                if value['state'] == 'ready':
                    break
                if value['state'] != 'indexing':
                    raise RuntimeError(value)
                time.sleep(.025)
            assert value['state'] == 'ready' and value['total'] == 100000, value
            samples = []
            for offset in range(0, 100000, 2000):
                start = time.perf_counter(); page = service.page(key, offset)
                samples.append((time.perf_counter() - start) * 1000)
                assert page['rows'][0]['编码'] == f'{offset:08d}'
                assert page['rows'][0]['数量'] == 'NA'
            result = {'frozen_preview': 'pass', 'rows':100000, 'first_page_seconds':first, 'cached_p95_ms':round(sorted(samples)[47], 3)}
            (ROOT / 'build/frozen-preview-metrics.json').write_text(json.dumps(result, indent=2))
            print(json.dumps(result), flush=True)
        finally:
            service.close(); multiprocessing.set_executable(previous)


if __name__ == '__main__':
    import multiprocessing.spawn
    multiprocessing.freeze_support()
    main()

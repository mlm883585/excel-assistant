"""Local synthetic benchmark; no customer files, models or network requests."""
import argparse
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def measure(function):
    import psutil
    stop = threading.Event()
    peak = [0]
    def sample():
        parent = psutil.Process()
        while not stop.is_set():
            processes = [parent] + parent.children(recursive=True)
            memory = 0
            for process in processes:
                try:
                    memory += process.memory_info().rss
                except psutil.Error:
                    pass
            peak[0] = max(peak[0], memory)
            stop.wait(.05)
    thread = threading.Thread(target=sample, daemon=True); thread.start()
    start = time.perf_counter()
    try:
        result = function()
        return result, {'seconds': round(time.perf_counter() - start, 3), 'peak_tree_rss_mb': round(peak[0] / 1024 ** 2, 1)}
    finally:
        stop.set(); thread.join()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=100000)
    parser.add_argument('--files', type=int, default=3)
    parser.add_argument('--skip-baseline', action='store_true')
    args = parser.parse_args()
    import psutil
    import xlsxwriter
    from assistant.preview import PreviewService
    from assistant.store import Store
    from assistant.tables import preview, run_operation
    folder = ROOT / 'build' / f'performance-{args.rows}-{args.files}'
    folder.mkdir(parents=True, exist_ok=True)
    store = Store(folder / 'state'); task = store.create()['id']; inputs = []
    for index in range(args.files):
        source = folder / f'synthetic-{index}.xlsx'
        if not source.exists():
            with xlsxwriter.Workbook(source, {'constant_memory': True}) as book:
                sheet = book.add_worksheet('数据')
                sheet.write_row(0, 0, ['物料编码','分类'] + [f'数量{i}' for i in range(28)])
                for row in range(args.rows):
                    sheet.write_row(row + 1, 0, [f'{row:08d}', 'NA' if row % 7 == 0 else '配件'] + [row % 100 + i for i in range(28)])
        info = store.import_file(task, source)
        inputs.append({'file_id': info['id'], 'sheet': '数据', 'header_row': 1})
    report = {'hardware': {'os': platform.platform(), 'cpu': platform.processor(), 'logical_cpus': os.cpu_count(), 'ram_gb': round(psutil.virtual_memory().total / 1024 ** 3, 1), 'python': platform.python_version()}, 'rows_per_file': args.rows, 'columns': 30, 'files': args.files}
    if not args.skip_baseline:
        print('BASELINE_START', flush=True)
        _, report['legacy_first_page'] = measure(lambda: preview(store, task, inputs[0]))
        _, report['legacy_next_page'] = measure(lambda: preview(store, task, inputs[0], 50))
    service = PreviewService(store)
    def indexed():
        start = time.perf_counter(); first = None
        key = service.start(task, inputs[0])['preview_id']
        while True:
            page = service.page(key)
            if page.get('rows') and first is None:
                first = time.perf_counter() - start
            if page['state'] == 'ready':
                assert page['total'] == args.rows
                break
            if page['state'] != 'indexing':
                raise RuntimeError(page)
            time.sleep(.025)
        samples = []
        for index in range(50):
            start_page = time.perf_counter()
            result = service.page(key, ((index * 37) % max(1, args.rows // 50)) * 50)
            assert result['rows']
            samples.append((time.perf_counter() - start_page) * 1000)
        return {'first_page_seconds': round(first, 3), 'cached_page_p95_ms': round(sorted(samples)[47], 3), 'cached_page_median_ms': round(statistics.median(samples), 3), 'samples': len(samples)}
    try:
        print('INDEX_START', flush=True)
        report['preview'], report['index'] = measure(indexed)
    finally:
        service.close()
    print('APPEND_START', flush=True)
    result, report['append'] = measure(lambda: run_operation(store, task, {'kind': 'append', 'inputs': inputs, 'params': {}}))
    assert result['statistics']['output_rows'] == args.rows * args.files
    report['append']['stages_ms'] = result['statistics']['timings_ms']
    report['append']['verified_output_rows'] = result['statistics']['output_rows']
    (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()

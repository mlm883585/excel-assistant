"""Loopback-only synthetic UI harness. Never serves real application state."""
import json
import multiprocessing
import os
from pathlib import Path
import sys
import threading
import uuid
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.path[:0] = [str(ROOT), str(ROOT / 'vendor/ppx-py/src')]
    folder = ROOT / 'build' / ('ui-workbench-' + uuid.uuid4().hex)
    os.environ['EXCEL_ASSISTANT_HOME'] = str(folder)
    from assistant.store import Store
    from ppx_py.bridge import Bridge
    from api import api
    store = Store(folder)
    task = store.create()['id']
    for name in ['库存.csv', '订单.csv']:
        path = folder / name
        path.write_text('物料编码,分类,数量\n' + ''.join(f'{i:06d},配件,{i % 10}\n' for i in range(400)), encoding='utf-8-sig')
        store.import_file(task, path)
    wide_task = store.create()['id']
    wide = folder / '宽表.csv'
    wide.write_text(','.join(f'字段{i}' for i in range(300)) + '\n' + (','.join(str(i) for i in range(300)) + '\n') * 400, encoding='utf-8-sig')
    store.import_file(wide_task, wide)
    large = ROOT / 'build/performance-100000-3/synthetic-0.xlsx'
    if large.exists():
        large_task = store.create()['id']
        store.import_file(large_task, large)
    with store.connect() as db:
        db.executemany("INSERT INTO tasks(id,body,updated) VALUES (?,?,'2000-01-01')", [(f'{i:032x}', json.dumps({'id':f'{i:032x}','status':'pending','files':[], 'outputs':[]})) for i in range(1000)])
        db.executemany('INSERT INTO events(task,body) VALUES (?,?)', [(task, json.dumps({'kind':'message','data':f'合成历史消息 {i}'})) for i in range(10000)])
    bridge = Bridge(); bridge.register_api(api)
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT / 'gui/dist'), **kwargs)
        def log_message(self, *args):
            pass
        def do_POST(self):
            if self.path == '/__shutdown':
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if payload.get('token') != shutdown_token:
                    self.send_error(403); return
                self.send_response(200); self.end_headers()
                threading.Thread(target=server.shutdown, daemon=True).start()
                return
            if self.path != '/__rpc':
                self.send_error(404); return
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            body = json.dumps(bridge.call(*payload), ensure_ascii=False).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    shutdown_token = uuid.uuid4().hex
    info = {'port': server.server_port, 'task_id': task, 'state': str(folder),
            'large_benchmark': large.exists(), 'shutdown_token': shutdown_token}
    (ROOT / 'build/workbench-server.json').write_text(json.dumps(info))
    print('UI_SERVER_READY ' + json.dumps(info), flush=True)
    timer = threading.Timer(600, server.shutdown); timer.daemon = True; timer.start()
    try:
        server.serve_forever()
    finally:
        timer.cancel(); api.shutdown(); server.server_close()


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()

"""Run the built frontend and native PPX RPC in a hidden, real WebView2 window."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'vendor/ppx-py/src')]


def main():
    import webview
    from ppx_py.bridge import Bridge
    from assistant.store import Store
    from assistant.workbooks import Workbooks
    from assistant.workbook_excel import export_workbook
    with tempfile.TemporaryDirectory(prefix='workbook-webview-') as directory:
        os.environ['EXCEL_ASSISTANT_HOME']=directory
        from api import api
        store=Store(Path(directory));task=store.create()['id'];service=Workbooks(store)
        snapshot=json.loads((ROOT/'build/workbook-formula-snapshot.json').read_text(encoding='utf-8'))
        expected={k:c['value'] for k,c in snapshot['sheets'][0]['cells'].items() if c.get('formula')}
        for sheet in snapshot['sheets']:
            for cell in sheet['cells'].values():
                if cell.get('formula'):cell.update(value=None,result_state='pending')
        service._insert(task,snapshot,'import')
        bridge=Bridge();bridge.register_api(api)
        class NativeAPI:
            def call(self,method,params=None,request_id=None):return bridge.call(method,params,request_id)
        window=webview.create_window('工作簿 WebView2 自动验收',str(ROOT/'gui/dist/index.html'),js_api=NativeAPI(),width=1600,height=1000,hidden=True)
        outcome={}
        def verify():
            try:
                deadline=time.monotonic()+70
                while time.monotonic()<deadline:
                    clicked=window.evaluate_js("(() => { const b=Array.from(document.querySelectorAll('.workbook-chips button')).find(b=>b.textContent.includes('公式验收')); if(b){b.click();return true}return false})()")
                    if clicked:break
                    time.sleep(.1)
                else:raise RuntimeError('WebView2 未载入任务工作簿入口')
                while time.monotonic()<deadline:
                    value=service.load(task,snapshot['id'])
                    if value['revision']>1 and all(value['snapshot']['sheets'][0]['cells'][k].get('result_state')=='ready' for k in expected):break
                    time.sleep(.1)
                else:raise RuntimeError('WebView2 公式计算或自动保存超时')
                for key,wanted in expected.items():assert value['snapshot']['sheets'][0]['cells'][key]['value']==wanted,(key,value['snapshot']['sheets'][0]['cells'][key],wanted)
                assert window.evaluate_js("Array.from(document.querySelectorAll('.univer-container canvas')).some(c=>c.width>0 && c.height>0)")
                resources=window.evaluate_js("performance.getEntriesByType('resource').map(r=>r.name)")
                assert not any(url.startswith(('http://','https://')) and not url.startswith(('http://127.0.0.1:','http://localhost:')) for url in resources),resources
                export_workbook(value['snapshot'],Path(directory)/'webview-result.xlsx')
                outcome.update(passed=True,formulas=len(expected),revision=value['revision'],renderer='edgechromium',user_agent=window.evaluate_js('navigator.userAgent'),external_requests=0)
            except BaseException as exc:outcome.update(passed=False,error=repr(exc))
            finally:window.destroy()
        window.events.loaded+=lambda:threading.Thread(target=verify,daemon=True).start()
        webview.start(gui='edgechromium',private_mode=True)
        api.shutdown()
        (ROOT/'build/webview-workbook-result.json').write_text(json.dumps(outcome,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(outcome,ensure_ascii=False))
        if not outcome.get('passed'):raise RuntimeError(outcome)


if __name__=='__main__':main()

"""Synthetic complete editor-format and large-result benchmarks, separate from preview."""
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import psutil
    from assistant.store import Store
    from assistant.workbooks import Workbooks
    from assistant.workbook_model import blank_workbook, validate_snapshot
    from assistant.workbook_excel import export_workbook, import_workbook
    from assistant.tables import run_operation
    folder = ROOT/'build'/('workbook-benchmark-'+uuid.uuid4().hex)
    folder.mkdir(parents=True)
    store = Store(folder/'state'); task = store.create()['id']; books=Workbooks(store)
    process=psutil.Process(); peak=[process.memory_info().rss]; stop=threading.Event()
    def memory():
        while not stop.wait(.05): peak[0]=max(peak[0],process.memory_info().rss)
    sampler=threading.Thread(target=memory,daemon=True);sampler.start()
    timings={}
    def measure(name, fn):
        start=time.perf_counter();value=fn();timings[name]=round(time.perf_counter()-start,3);print(name,timings[name],flush=True);return value
    try:
        snapshot=blank_workbook('20万格容量验收'); sheet=snapshot['sheets'][0];sheet['row_count']=10000
        sheet['cells']={f'{i//20},{i%20}':{'value':i,'type':'number'} for i in range(200000)}
        assert validate_snapshot(snapshot)==200000
        path=folder/'capacity.xlsx'
        measure('export_200000_seconds',lambda:export_workbook(snapshot,path))
        imported,issues=measure('import_200000_seconds',lambda:import_workbook(path))
        assert not issues and validate_snapshot(imported)==200000
        books._insert(task,imported,'import')
        measure('save_200000_seconds',lambda:books.save(task,imported,1))
        reopened=measure('reopen_200000_seconds',lambda:books.load(task,imported['id']))
        assert reopened['snapshot']['sheets'][0]['cells']['9999,19']['value']==199999
        source=folder/'large.csv'
        with source.open('w',encoding='utf-8-sig',newline='') as stream:
            stream.write('编号,数量,单价\n')
            for i in range(100000):stream.write(f'{i:08d},{i},2\n')
        file_id=store.import_file(task,source)['id']
        op={'kind':'calculate','inputs':[{'file_id':file_id}],'params':{'columns':[{'name':'金额','expression':{'op':'multiply','args':[{'field':'数量'},{'field':'单价'}]}}]}}
        output=measure('calculate_and_complete_review_100000_seconds',lambda:run_operation(store,task,op))
        review=books.review(task,output['id']);assert review['total']==100000 and not review['can_edit'],review
        last=measure('last_diff_page_seconds',lambda:books.changes(task,output['id'],99950,50))
        assert len(last['items'])==50 and last['items'][-1]['new']==199998
        assert last['items'][-1]['source']['__source_row']==100001
        results={'timings':timings,'peak_rss_mb':round(peak[0]/1024**2,1),'editor_cells':200000,'data_rows':100000,'changes':review['total'],'last_source_row':100001,'folder':str(folder)}
        (ROOT/'build/workbook-capacity-metrics.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(results,ensure_ascii=False),flush=True)
    finally:stop.set();sampler.join()


if __name__=='__main__':main()

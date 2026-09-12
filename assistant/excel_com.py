"""Excel-native recalculation in a task worker; never attaches to user Excel."""
from pathlib import Path
import shutil
import sys
import uuid
import json
import time


def recalculate(store, task_id, file_id):
    if sys.platform != 'win32':
        raise ValueError('Excel 重算仅支持 Windows')
    source, _ = store.resolve_file(task_id, file_id)
    if source.suffix != '.xlsx':
        raise ValueError('原生重算仅支持 xlsx 副本')
    import pythoncom
    import win32com.client
    from openpyxl import load_workbook
    output_id=uuid.uuid4().hex
    folder=store.directory(task_id)/'outputs';folder.mkdir(exist_ok=True)
    target=folder/f'{output_id}.xlsx'
    temp=folder/f'.{output_id}.tmp.xlsx'
    shutil.copyfile(source,temp)
    app=None;book=None;owned=False
    marker=store.directory(task_id)/'excel-process.json'
    started=time.time()
    pythoncom.CoInitialize()
    try:
        app=win32com.client.DispatchEx('Excel.Application')
        import win32process
        import psutil
        _,pid=win32process.GetWindowThreadProcessId(app.Hwnd)
        created=psutil.Process(pid).create_time()
        if created < started - 1:
            raise RuntimeError('无法确认独立 Excel 进程，拒绝附着到已有 Excel')
        owned=True
        marker.write_text(json.dumps({'pid':pid,'created':created}),encoding='utf-8')
        app.Visible=False
        app.DisplayAlerts=False
        app.EnableEvents=False
        app.AutomationSecurity=3
        book=app.Workbooks.Open(str(temp),UpdateLinks=0,ReadOnly=False,IgnoreReadOnlyRecommended=True)
        app.CalculateFullRebuild()
        book.Save()
        book.Close(SaveChanges=False);book=None
        check=load_workbook(temp,read_only=True,data_only=True)
        check.close()
        temp.rename(target)
    finally:
        try:
            if book is not None:book.Close(SaveChanges=False)
        finally:
            try:
                if app is not None and owned:app.Quit()
            finally:
                marker.unlink(missing_ok=True)
                pythoncom.CoUninitialize()
                temp.unlink(missing_ok=True)
    info={'id':output_id,'name':'Excel重算结果.xlsx','relative':str(target.relative_to(store.directory(task_id))),'statistics':{'recalculated':True},'issues':[],'validated':True}
    task=store.get(task_id);task['outputs'].append(info);store.save(task)
    return info

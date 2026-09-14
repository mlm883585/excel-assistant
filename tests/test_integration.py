import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from unittest.mock import patch
import sys
import tempfile
import threading
import time
import os
import unittest

from assistant.agent import AgentRunner
from assistant.jobs import Jobs
from assistant.store import Store

ROOT = Path(__file__).resolve().parents[1]


class IntegrationTests(unittest.TestCase):
    def test_close_waits_for_worker_observer(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'data')
            task = store.create()['id']
            source = Path(tmp) / 'input.csv'
            source.write_text('code,qty\nA,2\n')
            file = store.import_file(task, source)
            jobs = Jobs(store)
            observer_entered = threading.Event()
            release_observer = threading.Event()
            closed = threading.Event()
            original_watch = jobs._watch

            def delayed_watch(task_id, process):
                observer_entered.set()
                release_observer.wait(30)
                original_watch(task_id, process)

            def close():
                jobs.close()
                closed.set()

            closer = None
            try:
                with patch.object(jobs, '_watch', side_effect=delayed_watch):
                    jobs.start(task, plan={'steps': [{'kind': 'append', 'inputs': [{'file_id': file['id']}], 'params': {}}]})
                    self.assertTrue(observer_entered.wait(5))
                    jobs.processes[task].join(30)
                    self.assertFalse(jobs.processes[task].is_alive())
                    closer = threading.Thread(target=close)
                    closer.start()
                    self.assertFalse(closed.wait(0.1), 'close returned before observer released the database')
            finally:
                release_observer.set()
                if closer is not None:
                    closer.join(10)
                jobs.close()
            self.assertTrue(closed.is_set())
            self.assertTrue(all(not watcher.is_alive() for watcher in jobs.watchers))
            with self.assertRaisesRegex(ValueError, '已关闭'):
                jobs.start(task, prompt='must not restart after close')

    def test_mcp_stdio_real_transport(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'data')
            task = store.create()['id']
            source = Path(tmp) / 'input.csv'
            source.write_text('code,qty\n0001,2\nNA,3\n')
            file = store.import_file(task, source)
            async def run():
                command=os.environ.get('MCP_TEST_EXECUTABLE',sys.executable)
                arguments=[] if 'MCP_TEST_EXECUTABLE' in os.environ else [str(ROOT/'mcp_entry.py')]
                params = StdioServerParameters(command=command,args=[*arguments,'--root',str(store.root),'--task',task])
                async with stdio_client(params) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        self.assertEqual(len(tools.tools),5)
                        result = await session.call_tool('datacraft_execute',{'operation':{'kind':'append','inputs':[{'file_id':file['id']}],'params':{}}})
                        self.assertFalse(result.isError)
                        for operation in [
                            {'kind':'create_table','inputs':[],'params':{'columns':['编号','数量']}},
                            {'kind':'calculate','inputs':[{'file_id':file['id']}],'params':{'columns':[{'name':'金额','expression':{'op':'multiply','args':[{'field':'qty'},{'number':2}]}}]}},
                        ]:
                            result=await session.call_tool('datacraft_execute',{'operation':operation})
                            self.assertFalse(result.isError,result)
                        self.assertFalse(any(t.name.startswith(('outputs.','workbooks.')) for t in tools.tools))
                        rejected = await session.call_tool('datacraft_preview',{'selection':{'file_id':'../outside'}})
                        self.assertTrue(rejected.isError)
            asyncio.run(run())
            self.assertEqual(len(store.get(task)['outputs']),3)

    def test_spawned_job_and_recipe_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/'data')
            task = store.create()['id']
            source = Path(tmp)/'data.csv'; source.write_text('code,qty\nA,2\nA,3\n')
            file = store.import_file(task,source)
            jobs = Jobs(store)
            try:
                jobs.start(task,plan={'steps':[{'kind':'group','inputs':[{'file_id':file['id']}],'params':{'keys':['code'],'columns':['qty']}}]})
                process=jobs.processes[task]; process.join(30)
                self.assertFalse(process.is_alive())
                self.assertEqual(store.get(task)['status'],'succeeded')
                self.assertEqual(len(store.get(task)['outputs']),1)
            finally:
                jobs.close()

    def test_actual_qwen_cli_sdk_local_model_stub(self):
        cli=ROOT/'node_modules/@qwen-code/qwen-code/cli.js'
        if not cli.exists():
            if os.environ.get('REQUIRE_QWEN_CLI') == '1':
                self.fail('CI requires the pinned Qwen CLI; run npm ci first')
            self.skipTest('Run npm ci for the pinned CLI integration test')
        requests=[]
        fixture={"execute":False,"file_id":None}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(payload)
                if payload.get('stream'):
                    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                    events=[{'id':'local-test','object':'chat.completion.chunk','choices':[{'index':0,'delta':{'role':'assistant','content':'Local protocol test complete.'},'finish_reason':None}]},{'id':'local-test','object':'chat.completion.chunk','choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}]
                    if fixture['execute'] and not any(m.get('role')=='tool' for m in payload.get('messages',[])):
                        names=[t['function']['name'] for t in payload.get('tools',[])]
                        name=next((n for n in names if n.endswith('datacraft_execute')),None)
                        if name is None:
                            print('MISSING_EXECUTE_TOOLS',names,flush=True)
                            self.wfile.write(b'data: [DONE]\n\n');return
                        args=json.dumps({'operation':fixture.get('operation') or {'kind':'append','inputs':[{'file_id':fixture['file_id']}],'params':{}}})
                        events=[{'id':'local-test','object':'chat.completion.chunk','choices':[{'index':0,'delta':{'role':'assistant','tool_calls':[{'index':0,'id':'fixture-call','type':'function','function':{'name':name,'arguments':args}}]},'finish_reason':None}]},{'id':'local-test','object':'chat.completion.chunk','choices':[{'index':0,'delta':{},'finish_reason':'tool_calls'}]}]
                    for event in events:self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode())
                    self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
                else:
                    body=json.dumps({'id':'local-test','object':'chat.completion','choices':[{'index':0,'message':{'role':'assistant','content':'Local protocol test complete.'},'finish_reason':'stop'}],'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}).encode()
                    self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                store=Store(Path(tmp)/'data');task=store.create()['id']
                config={'base_url':f'http://127.0.0.1:{server.server_port}/v1','model':'protocol-fixture','cli':str(cli)}
                async def run():
                    with self.assertRaisesRegex(ValueError,'尚未生成'):
                        await asyncio.wait_for(AgentRunner(store,task,config).run('Say hello without using tools.'),90)
                asyncio.run(run())
                self.assertTrue(requests,'The real CLI must reach the local model fixture')
                self.assertTrue(store.get(task)['session_id'])
                # A second task exercises the real CLI -> permission callback -> MCP -> file path.
                task=store.create()['id']
                source=Path(tmp)/'fixture.csv';source.write_text('code,qty\n0001,2\n')
                fixture.update(execute=True,file_id=store.import_file(task,source)['id'])
                asyncio.run(asyncio.wait_for(AgentRunner(store,task,config).run('Execute the prepared fixture with datacraft_execute.'),90))
                self.assertEqual(len(store.get(task)['outputs']),1)
                task=store.create()['id']
                fixture['operation']={'kind':'create_table','inputs':[],'params':{'columns':['编号','数量']}}
                asyncio.run(asyncio.wait_for(AgentRunner(store,task,config).run('Create the empty table with datacraft_execute.'),90))
                self.assertEqual(store.get(task)['outputs'][0]['kind'],'workbook_candidate')
                names={t['function']['name'] for t in requests[-1].get('tools',[])}
                self.assertFalse({'run_shell_command','read_file','agent','web_fetch'} & names)
        finally:
            server.shutdown();server.server_close()

    def test_cancel_owned_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'data');task=store.create()['id']
            source=Path(tmp)/'data.csv';source.write_text('code,qty\nA,2\n')
            file=store.import_file(task,source)
            jobs=Jobs(store)
            try:
                jobs.start(task,plan={'steps':[{'kind':'append','inputs':[{'file_id':file['id']}]}]})
                self.assertTrue(jobs.cancel(task))
                self.assertFalse(jobs.processes[task].is_alive())
                self.assertEqual(store.get(task)['status'],'cancelled')
            finally:
                jobs.close()


if __name__=='__main__': unittest.main()

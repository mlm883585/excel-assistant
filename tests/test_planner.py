import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from assistant.planner import NativeAgent
from assistant.store import Store


class PlannerHandler(BaseHTTPRequestHandler):
    responses = []   # scripted /chat/completions response dicts, consumed in order
    requests = []    # recorded request bodies

    def log_message(self, *args):
        pass

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        self.requests.append(json.loads(self.rfile.read(length) or b'{}'))
        if not self.responses:
            self._json(500, {'error': 'no scripted response'})
            return
        self._json(200, self.responses.pop(0))


def start_server(responses):
    PlannerHandler.responses = list(responses)
    PlannerHandler.requests = []
    server = ThreadingHTTPServer(('127.0.0.1', 0), PlannerHandler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f'http://127.0.0.1:{server.server_port}/v1'


def tool_call(call_id, name, arguments):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def chat_response(content=None, tool_calls=None):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"index": 0, "message": message, "finish_reason": "stop"}]}


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.store = Store(self.root)
        self.task_id = self.store.create()["id"]
        csv = self.root / "data.csv"
        csv.write_text("物料,数量\nA,10\nB,20\nA,30\n", encoding="utf-8")
        self.file_id = self.store.import_file(self.task_id, csv)["id"]

    def group_op(self, keys):
        return {"kind": "group", "inputs": [{"file_id": self.file_id, "header_row": 1}],
                "params": {"keys": keys, "columns": ["数量"], "aggregate": "sum"}}

    def test_observation_collects_plan_and_executes(self):
        responses = [
            chat_response(tool_calls=[tool_call("c1", "datacraft_profile", {"selection": {"file_id": self.file_id, "header_row": 1}, "sample_limit": 5})]),
            chat_response(tool_calls=[tool_call("c2", "datacraft_execute", {"operation": self.group_op(["物料"])})]),
            chat_response(content="处理完成"),
        ]
        server, base = start_server(responses)
        NativeAgent(self.store, self.task_id, {"base_url": base, "model": "test"}).run("按物料汇总数量")

        self.assertEqual(len(PlannerHandler.requests), 3)
        second = PlannerHandler.requests[1]
        tool_msgs = [m for m in second["messages"] if m["role"] == "tool"]
        self.assertTrue(tool_msgs, second["messages"])
        self.assertTrue(any("物料" in m["content"] for m in tool_msgs), tool_msgs)

        kinds = [e["kind"] for e in self.store.events(self.task_id)]
        self.assertIn("step", kinds)
        self.assertIn("output", kinds)
        self.assertIn("message", kinds)
        self.assertTrue(self.store.get(self.task_id)["outputs"])

    def test_self_heal_replans_after_failure(self):
        responses = [
            chat_response(tool_calls=[tool_call("c1", "datacraft_execute", {"operation": self.group_op(["不存在"])})]),
            chat_response(content="计划如下"),
            chat_response(tool_calls=[tool_call("c2", "datacraft_execute", {"operation": self.group_op(["物料"])})]),
            chat_response(content="已修正"),
        ]
        server, base = start_server(responses)
        NativeAgent(self.store, self.task_id, {"base_url": base, "model": "test"}).run("按物料汇总数量")

        self.assertEqual(len(PlannerHandler.requests), 4)
        self.assertTrue(self.store.get(self.task_id)["outputs"])
        kinds = [e["kind"] for e in self.store.events(self.task_id)]
        self.assertIn("step", kinds)

    def test_ask_user_question_waits_for_answer(self):
        responses = [
            chat_response(tool_calls=[tool_call("c1", "ask_user_question", {"questions": [{"question": "是否继续？", "options": [{"label": "是", "value": "是"}]}]})]),
            chat_response(tool_calls=[tool_call("c2", "datacraft_execute", {"operation": self.group_op(["物料"])})]),
            chat_response(content="收到"),
        ]
        server, base = start_server(responses)
        agent = NativeAgent(self.store, self.task_id, {"base_url": base, "model": "test"})
        failure = []
        thread = threading.Thread(target=lambda: self._run(agent, failure))
        thread.start()
        # Wait until the worker emits the question event. The status flips to
        # "waiting" one DB write before the event lands, so poll for the event
        # itself rather than assuming it is present the instant status changes.
        deadline = time.monotonic() + 5
        question = []
        while time.monotonic() < deadline:
            if self.store.get(self.task_id)["status"] == "waiting":
                question = [e for e in self.store.events(self.task_id) if e["kind"] == "question"]
                if question:
                    break
            time.sleep(0.02)
        self.assertEqual(self.store.get(self.task_id)["status"], "waiting")
        self.assertTrue(question, "question event was not emitted")
        self.assertEqual(question[0]["data"]["questions"][0]["question"], "是否继续？")
        answer_path = self.store.directory(self.task_id) / "answer.json"
        answer_path.write_text(json.dumps({"0": "是"}, ensure_ascii=False), encoding="utf-8")
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive(), "agent loop did not finish")
        self.assertEqual(failure, [])
        self.assertEqual(len(PlannerHandler.requests), 3)

    def _run(self, agent, failure):
        try:
            agent.run("是否继续")
        except Exception as exc:  # pragma: no cover - surfaced through failure list
            failure.append(exc)


class SqlOperationTests(unittest.TestCase):
    def test_run_operation_sql_joins_two_tables(self):
        from assistant.models import Operation
        from assistant.tables import run_operation
        root = Path(tempfile.mkdtemp())
        store = Store(root)
        task_id = store.create()["id"]
        orders = root / "orders.csv"
        orders.write_text("订单,金额\nO1,100\nO2,200\n", encoding="utf-8")
        customers = root / "customers.csv"
        customers.write_text("订单,客户\nO1,甲\nO2,乙\n", encoding="utf-8")
        order_id = store.import_file(task_id, orders)["id"]
        customer_id = store.import_file(task_id, customers)["id"]
        operation = Operation.model_validate({
            "kind": "sql",
            "inputs": [{"file_id": order_id, "header_row": 1}, {"file_id": customer_id, "header_row": 1}],
            "params": {"aliases": ["o", "c"], "query": "SELECT o.订单, o.金额, c.客户 FROM o JOIN c ON o.订单 = c.订单"},
        })
        info = run_operation(store, task_id, operation.model_dump())
        self.assertEqual(info["statistics"]["output_rows"], 2)
        self.assertEqual(info["statistics"]["input_rows"], [2, 2])
        self.assertTrue(info["validated"])


if __name__ == "__main__":
    unittest.main()

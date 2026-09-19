import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path

from assistant.agent import AgentRunner
from assistant.store import Store
from assistant.tables import emit_step
from assistant.workbooks import Workbooks


class FakeStream:
    def __init__(self, messages, on_message=None):
        self.messages = list(messages)
        self.on_message = on_message

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.messages:
            raise StopAsyncIteration
        message = self.messages.pop(0)
        if self.on_message:
            self.on_message(message)
        return message


class FakeQuery:
    """Stand-in for qwen_code_sdk.query: async CM returning an async message iterator."""

    def __init__(self, messages, on_message=None):
        self.messages = messages
        self.on_message = on_message

    def __call__(self, prompt, options):
        return _FakeContext(self.messages, self.on_message)


class _FakeContext:
    def __init__(self, messages, on_message):
        self.stream = FakeStream(messages, on_message)

    async def __aenter__(self):
        return self.stream

    async def __aexit__(self, *exc):
        return False


class FakeRunner(AgentRunner):
    def options(self):
        return {}


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.store = Store(self.root)
        self.task_id = self.store.create()["id"]

    def runner(self, messages):
        def on_message(message):
            if message.get("type") == "result":
                record = self.store.get(self.task_id)
                record["outputs"].append({"id": "out-1"})
                self.store.save(record)
        return FakeRunner(self.store, self.task_id, {}, query_factory=FakeQuery(messages, on_message))

    def test_stream_events_carry_text_deltas_and_skip_thinking(self):
        messages = [
            {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "你"}, "index": 0}},
            {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "好"}, "index": 0}},
            {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "secret"}, "index": 1}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "你好"}]}},
            {"type": "result", "subtype": "success", "is_error": False, "result": "完成"},
        ]
        asyncio.run(self.runner(messages).run("hi"))
        events = self.store.events(self.task_id)
        streams = [e for e in events if e["kind"] == "stream"]
        messages_out = [e for e in events if e["kind"] == "message"]
        self.assertTrue(streams, "expected stream events")
        self.assertEqual("".join(s["data"]["text"] for s in streams), "你好")
        self.assertNotIn("secret", json.dumps(events, ensure_ascii=False))
        self.assertEqual(messages_out[-1]["data"], "完成")

    def test_emit_step_records_label_and_row_counts(self):
        info = {"id": "o1", "name": "处理结果.xlsx",
                "statistics": {"input_rows": [100, 20], "output_rows": 80, "issues": 3}}
        emit_step(self.store, self.task_id, "group", info)
        steps = [e for e in self.store.events(self.task_id) if e["kind"] == "step"]
        self.assertEqual(len(steps), 1)
        data = steps[0]["data"]
        self.assertEqual(data["label"], "分组汇总")
        self.assertEqual(data["rows_in"], [100, 20])
        self.assertEqual(data["rows_out"], 80)
        self.assertEqual(data["issues"], 3)


class UndoTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.store = Store(self.root)
        self.task_id = self.store.create()["id"]

    def test_undo_rolls_back_one_revision(self):
        service = Workbooks(self.store)
        record = service.open(self.task_id)
        book = record["snapshot"]["id"]
        original_name = record["snapshot"]["name"]
        changed = copy.deepcopy(record["snapshot"])
        changed["name"] = "改名.xlsx"
        service.save(self.task_id, changed, 1)
        self.assertEqual(service.load(self.task_id, book)["current_revision"], 2)
        result = service.undo(self.task_id, book, 2)
        self.assertEqual(result["revision"], 3)
        self.assertEqual(result["snapshot"]["name"], original_name)

    def test_undo_at_initial_revision_raises(self):
        service = Workbooks(self.store)
        record = service.open(self.task_id)
        with self.assertRaisesRegex(ValueError, "已是初始版本"):
            service.undo(self.task_id, record["snapshot"]["id"], 1)

    def test_undo_stale_version_raises(self):
        service = Workbooks(self.store)
        record = service.open(self.task_id)
        book = record["snapshot"]["id"]
        changed = copy.deepcopy(record["snapshot"])
        changed["name"] = "v2"
        service.save(self.task_id, changed, 1)
        with self.assertRaisesRegex(ValueError, "已改变"):
            service.undo(self.task_id, book, 1)


if __name__ == "__main__":
    unittest.main()

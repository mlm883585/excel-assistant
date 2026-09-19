import json
import tempfile
import unittest
import uuid
from datetime import datetime
from pathlib import Path

from assistant.cron import CronError, next_run, parse_expr
from assistant.models import OperationPlan
from assistant.scheduler import SchedulerService, validate_schedule
from assistant.store import Store
from assistant.tables import emit_step, run_operation


class FakeJobs:
    """In-process stand-in for Jobs (avoids Windows spawn re-importing unittest __main__)."""

    def __init__(self, store):
        self.store = store
        self.started = []
        self.cancelled = []
        self.start_attempts = 0
        self.busy_countdown = 0
        self.fail_first_start = False

    def busy(self):
        if self.busy_countdown > 0:
            self.busy_countdown -= 1
            return True
        return False

    def start(self, task_id, plan=None, prompt=None, config=None):
        self.start_attempts += 1
        if self.fail_first_start:
            self.fail_first_start = False
            raise ValueError("首版一次执行一个任务，请等待或取消当前任务")
        self.started.append(task_id)
        record = self.store.get(task_id)
        record.update(status="running", error=None)
        self.store.save(record)
        try:
            validated = OperationPlan.model_validate(plan)
            for operation in validated.steps:
                output = run_operation(self.store, task_id, operation.model_dump())
                emit_step(self.store, task_id, operation.kind, output)
            record = self.store.get(task_id)
            record["status"] = "succeeded"
            self.store.save(record)
        except Exception as exc:
            record = self.store.get(task_id)
            record.update(status="failed", error=str(exc))
            self.store.save(record)
        return {"task_id": task_id}

    def cancel(self, task_id):
        self.cancelled.append(task_id)
        record = self.store.get(task_id)
        record.update(status="cancelled", error=None)
        self.store.save(record)
        return True


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "state")


class CronParseTests(unittest.TestCase):
    def test_tokens(self):
        self.assertEqual(parse_expr("*/15 9 * * 1")["minute"], set(range(0, 60, 15)))
        self.assertEqual(parse_expr("0 9 * * 1-5")["dow"], {1, 2, 3, 4, 5})
        self.assertEqual(parse_expr("0 0 1,15 * *")["dom"], {1, 15})
        self.assertEqual(parse_expr("30 8-17/2 * * *")["hour"], {8, 10, 12, 14, 16})

    def test_dow_seven_normalised(self):
        self.assertEqual(parse_expr("0 0 * * 7")["dow"], {0})
        self.assertEqual(parse_expr("0 0 * * 5-7")["dow"], {5, 6, 0})

    def test_errors(self):
        for bad in ("", "0 0 * *", "0 0 * * * *", "60 * * * *", "*/0 * * * *", "a b c d e"):
            with self.assertRaises(CronError):
                parse_expr(bad)


class NextRunTests(unittest.TestCase):
    def test_strictly_after(self):
        self.assertEqual(next_run("0 9 * * *", datetime(2024, 1, 1, 9, 0, 0)), datetime(2024, 1, 2, 9, 0, 0))

    def test_step(self):
        self.assertEqual(next_run("*/15 * * * *", datetime(2024, 1, 1, 10, 0, 0)), datetime(2024, 1, 1, 10, 15, 0))

    def test_dom_short_month_skips(self):
        self.assertEqual(next_run("0 0 31 * *", datetime(2024, 1, 30, 0, 0, 0)), datetime(2024, 1, 31, 0, 0, 0))

    def test_dow_sunday(self):
        # 2024-01-01 is a Monday; next Sunday is 2024-01-07.
        self.assertEqual(next_run("0 0 * * 0", datetime(2024, 1, 1, 0, 0, 0)), datetime(2024, 1, 7, 0, 0, 0))

    def test_vixie_or_dom_dow(self):
        # "day 13 OR Friday": from 2024-01-01 the first hit is Friday 2024-01-05.
        self.assertEqual(next_run("0 0 13 * 5", datetime(2024, 1, 1, 0, 0, 0)), datetime(2024, 1, 5, 0, 0, 0))

    def test_impossible_expr(self):
        with self.assertRaises(CronError):
            next_run("0 0 31 2 *", datetime(2024, 1, 1, 0, 0, 0))


class ValidateScheduleTests(Base):
    def recipe(self, slots):
        rid = uuid.uuid4().hex
        with self.store.connect() as db:
            db.execute("INSERT INTO recipes VALUES(?,?)", (rid, json.dumps({"id": rid, "name": "规则", "plan": {"steps": []}, "slots": slots}, ensure_ascii=False)))
        return rid

    def body(self, **overrides):
        body = {
            "name": "汇总", "recipe_id": self.recipe(["in.csv"]), "source_dir": str(self.root / "src"),
            "output_dir": str(self.root / "out"), "trigger": {"type": "manual"},
        }
        (self.root / "src").mkdir(parents=True, exist_ok=True)
        body.update(overrides)
        return body

    def test_valid_manual(self):
        schedule = validate_schedule(self.store, self.body())
        self.assertTrue(schedule["id"])
        self.assertTrue(schedule["enabled"])
        self.assertIsNone(schedule["next_run_at"])

    def test_valid_cron_sets_next_run(self):
        schedule = validate_schedule(self.store, self.body(trigger={"type": "cron", "cron": "0 9 * * *"}))
        self.assertIsNotNone(schedule["next_run_at"])

    def test_rejects(self):
        with self.assertRaisesRegex(ValueError, "名称"):
            validate_schedule(self.store, self.body(name=""))
        with self.assertRaisesRegex(ValueError, "规则不存在"):
            validate_schedule(self.store, self.body(recipe_id="z" * 32))
        with self.assertRaisesRegex(ValueError, "单输入槽位"):
            validate_schedule(self.store, self.body(recipe_id=self.recipe([])))
        with self.assertRaisesRegex(ValueError, "单输入槽位"):
            validate_schedule(self.store, self.body(recipe_id=self.recipe(["a.csv", "b.csv"])))
        with self.assertRaisesRegex(ValueError, "输入文件夹不存在"):
            validate_schedule(self.store, self.body(source_dir=str(self.root / "missing")))
        with self.assertRaisesRegex(ValueError, "输出文件夹不能"):
            validate_schedule(self.store, self.body(source_dir=str(self.root / "src"), output_dir=str(self.root / "src" / "out")))
        with self.assertRaisesRegex(ValueError, "输出文件夹不能"):
            validate_schedule(self.store, self.body(source_dir=str(self.root / "src"), output_dir=str(self.root / "src")))
        with self.assertRaisesRegex(ValueError, "触发"):
            validate_schedule(self.store, self.body(trigger={"type": "weekly"}))
        with self.assertRaises(CronError):
            validate_schedule(self.store, self.body(trigger={"type": "cron", "cron": "nonsense"}))


class ScheduleCrudTests(Base):
    def setUp(self):
        super().setUp()
        (self.root / "src").mkdir()
        self.service = SchedulerService(self.store, FakeJobs(self.store))
        self.rid = "r" * 32
        with self.store.connect() as db:
            db.execute("INSERT INTO recipes VALUES(?,?)", (self.rid, json.dumps({"id": self.rid, "name": "规则", "plan": {"steps": []}, "slots": ["in.csv"]}, ensure_ascii=False)))

    def test_roundtrip(self):
        saved = self.service.save({"name": "任务", "recipe_id": self.rid, "source_dir": str(self.root / "src"), "output_dir": str(self.root / "out"), "trigger": {"type": "manual"}})
        self.assertTrue(any(s["id"] == saved["id"] for s in self.service.list()))
        toggled = self.service.toggle(saved["id"], False)
        self.assertFalse(toggled["enabled"])
        self.assertIsNone(toggled["next_run_at"])
        self.assertEqual(self.store.get_schedule(saved["id"])["enabled"], False)
        self.assertTrue(self.service.delete(saved["id"]))
        self.assertFalse(self.service.delete(saved["id"]))
        with self.assertRaisesRegex(ValueError, "自动化任务不存在"):
            self.store.get_schedule(saved["id"])


class BatchEndToEndTests(Base):
    def make_recipe(self):
        task = self.store.create()
        seed = self.root / "seed.csv"
        seed.write_text("code,qty\nA,2\n", encoding="utf-8-sig")
        file = self.store.import_file(task["id"], seed)
        plan = {"steps": [{"kind": "group", "inputs": [{"file_id": file["id"]}], "params": {"keys": ["code"], "columns": ["qty"]}}]}
        record = self.store.get(task["id"])
        record["plan"] = plan
        record["status"] = "succeeded"
        self.store.save(record)
        return self.store.save_recipe(task["id"], "按编码汇总")

    def test_single_file_batch(self):
        recipe = self.make_recipe()
        src = self.root / "src"
        src.mkdir()
        source = src / "a.csv"
        source.write_text("code,qty\nX,1\nX,2\n", encoding="utf-8-sig")
        before = source.read_bytes()
        jobs = FakeJobs(self.store)
        service = SchedulerService(self.store, jobs)
        schedule = service.save({"name": "批量", "recipe_id": recipe["id"], "source_dir": str(src), "output_dir": str(self.root / "out"), "trigger": {"type": "manual"}})
        record = service.run_batch(schedule["id"], "manual")
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(record["total"], 1)
        self.assertEqual(record["succeeded"], 1)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(jobs.start_attempts, 1)
        run_folder = self.root / "out" / next(p.name for p in (self.root / "out").iterdir())
        names = [p.name for p in run_folder.iterdir()]
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].startswith("a."))
        persisted = self.store.get_schedule(schedule["id"])
        self.assertEqual(persisted["runs"][0]["status"], "succeeded")
        self.assertEqual(persisted["last_run_at"], record["finished_at"])

    def test_skips_non_table_files(self):
        recipe = self.make_recipe()
        src = self.root / "src"
        src.mkdir()
        (src / "a.csv").write_text("code,qty\nA,1\n", encoding="utf-8-sig")
        (src / "b.csv").write_text("code,qty\nB,2\n", encoding="utf-8-sig")
        (src / "notes.txt").write_text("ignore me")
        service = SchedulerService(self.store, FakeJobs(self.store))
        schedule = service.save({"name": "批量", "recipe_id": recipe["id"], "source_dir": str(src), "output_dir": str(self.root / "out"), "trigger": {"type": "manual"}})
        record = service.run_batch(schedule["id"], "manual")
        self.assertEqual(record["total"], 2)
        self.assertEqual(record["succeeded"], 2)
        run_folder = self.root / "out" / next(p.name for p in (self.root / "out").iterdir())
        stems = sorted(Path(p.name).stem for p in run_folder.iterdir())
        self.assertEqual(stems, ["a", "b"])

    def test_gate_retries_when_busy(self):
        recipe = self.make_recipe()
        src = self.root / "src"
        src.mkdir()
        (src / "a.csv").write_text("code,qty\nA,1\n", encoding="utf-8-sig")
        jobs = FakeJobs(self.store)
        jobs.fail_first_start = True
        jobs.busy_countdown = 1
        service = SchedulerService(self.store, jobs)
        service.gate_poll = 0.01
        schedule = service.save({"name": "批量", "recipe_id": recipe["id"], "source_dir": str(src), "output_dir": str(self.root / "out"), "trigger": {"type": "manual"}})
        record = service.run_batch(schedule["id"], "manual")
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(jobs.start_attempts, 2)
        self.assertEqual(len(jobs.started), 1)


class RunNowWorkerTests(Base):
    def make_recipe(self):
        task = self.store.create()
        seed = self.root / "seed.csv"
        seed.write_text("code,qty\nA,2\n", encoding="utf-8-sig")
        file = self.store.import_file(task["id"], seed)
        plan = {"steps": [{"kind": "group", "inputs": [{"file_id": file["id"]}], "params": {"keys": ["code"], "columns": ["qty"]}}]}
        record = self.store.get(task["id"])
        record["plan"] = plan
        record["status"] = "succeeded"
        self.store.save(record)
        return self.store.save_recipe(task["id"], "按编码汇总")

    def test_run_now_enqueues_and_runs(self):
        recipe = self.make_recipe()
        src = self.root / "src"
        src.mkdir()
        (src / "a.csv").write_text("code,qty\nA,1\n", encoding="utf-8-sig")
        service = SchedulerService(self.store, FakeJobs(self.store))
        try:
            service.start()
            schedule = service.save({"name": "批量", "recipe_id": recipe["id"], "source_dir": str(src), "output_dir": str(self.root / "out"), "trigger": {"type": "manual"}})
            service.run_now(schedule["id"])
            for _ in range(100):
                runs = self.store.get_schedule(schedule["id"]).get("runs", [])
                if runs and runs[0]["status"] != "running":
                    break
                import time
                time.sleep(0.02)
            runs = self.store.get_schedule(schedule["id"])["runs"]
            self.assertEqual(runs[0]["status"], "succeeded")
            self.assertEqual(runs[0]["trigger"], "manual")
        finally:
            service.close()


if __name__ == "__main__":
    unittest.main()

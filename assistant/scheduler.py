"""In-process batch + cron automation service (方向 10).

A schedule replays a saved single-slot recipe (a deterministic OperationPlan) over
every spreadsheet in a folder, one file per task, through the existing single-task
``Jobs`` gate. Results are copied into a per-run timestamped sub-folder of the
configured output directory — the source folder and any previous run's outputs are
never overwritten.

Two daemon threads: a tick that enqueues due cron schedules and a worker that runs
one batch at a time. ``self.lock`` guards schedule body mutations; it is never held
across ``jobs.start`` / ``store.get`` polls.
"""

import json
import os
import queue
import re
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from .cron import next_run, parse_expr

SUPPORTED_SUFFIXES = {".xlsx", ".xls", ".csv"}
MAX_RUNS = 50
MAX_RUN_ITEMS = 200
TICK_SECONDS = 20


def sanitize(name):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name)).strip().strip(".")
    return cleaned or "输出"


def validate_schedule(store, body):
    """Normalise and validate a schedule body (pure wrt the store; only reads recipes)."""
    name = str(body.get("name") or "").strip()
    if not 1 <= len(name) <= 100:
        raise ValueError("自动化任务名称需为 1-100 个字符")
    recipe_id = body.get("recipe_id")
    recipe = next((r for r in store.recipes() if r["id"] == recipe_id), None)
    if not recipe:
        raise ValueError("规则不存在，请先在规则库中保存规则")
    if len(recipe.get("slots", [])) != 1:
        raise ValueError("批量自动化仅支持单输入槽位的规则")
    if not body.get("source_dir"):
        raise ValueError("请选择输入文件夹")
    source_dir = Path(str(body["source_dir"])).resolve()
    if not source_dir.is_dir():
        raise ValueError("输入文件夹不存在，请检查路径")
    if not body.get("output_dir"):
        raise ValueError("请选择输出文件夹")
    output_dir = Path(str(body["output_dir"])).resolve()
    if output_dir == source_dir or output_dir.is_relative_to(source_dir):
        raise ValueError("输出文件夹不能与输入文件夹相同或位于其内部")
    trigger = body.get("trigger") or {}
    trigger_type = trigger.get("type")
    if trigger_type not in {"manual", "cron"}:
        raise ValueError("请选择手动触发或定时触发")
    cron = None
    if trigger_type == "cron":
        cron = str(trigger.get("cron") or "").strip()
        parse_expr(cron)
    enabled = bool(body.get("enabled", True))
    now = datetime.now().isoformat(timespec="seconds")
    schedule = {
        "id": body.get("id") or uuid.uuid4().hex,
        "name": name,
        "recipe_id": recipe_id,
        "source_dir": str(source_dir),
        "output_dir": str(output_dir),
        "trigger": {"type": trigger_type, "cron": cron} if trigger_type == "cron" else {"type": "manual"},
        "enabled": enabled,
        "created_at": body.get("created_at") or now,
        "last_run_at": body.get("last_run_at"),
        "next_run_at": None,
        "runs": (body.get("runs") or [])[-MAX_RUNS:],
    }
    if enabled and trigger_type == "cron":
        schedule["next_run_at"] = next_run(cron, datetime.now()).isoformat(timespec="seconds")
    return schedule


class SchedulerService:
    gate_poll = 1.0

    def __init__(self, store, jobs):
        self.store = store
        self.jobs = jobs
        self.lock = threading.RLock()
        self._queue = queue.Queue()
        self._queued = set()
        self._cancelled = set()
        self._active = None
        self._active_id = None
        self._stop = threading.Event()
        self._closed = False
        self._tick = None
        self._worker = None

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        if self._tick is not None:
            return
        self._reschedule_all()
        self._tick = threading.Thread(target=self._tick_loop, daemon=True, name="scheduler-tick")
        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="scheduler-worker")
        self._tick.start()
        self._worker.start()

    def close(self):
        with self.lock:
            self._closed = True
            self._stop.set()
            if self._active_id:
                self._cancelled.add(self._active_id)
        self._queue.put(None)
        for thread in (self._worker, self._tick):
            if thread is not None and thread.is_alive():
                thread.join(timeout=5)

    # -- public API --------------------------------------------------------

    def list(self):
        recipes = {r["id"]: r for r in self.store.recipes()}
        result = []
        for schedule in self.store.schedules():
            schedule = dict(schedule)
            recipe = recipes.get(schedule["recipe_id"])
            schedule["recipe_name"] = recipe["name"] if recipe else None
            result.append(schedule)
        return result

    def save(self, body):
        schedule = validate_schedule(self.store, body)
        self.store.save_schedule(schedule)
        return schedule

    def delete(self, schedule_id):
        with self.lock:
            self._cancelled.add(schedule_id)
            return self.store.delete_schedule(schedule_id)

    def toggle(self, schedule_id, enabled):
        def mutate(body):
            body["enabled"] = bool(enabled)
            if body["enabled"] and body["trigger"]["type"] == "cron":
                body["next_run_at"] = next_run(body["trigger"]["cron"], datetime.now()).isoformat(timespec="seconds")
            elif not body["enabled"]:
                body["next_run_at"] = None
        return self._update_schedule(schedule_id, mutate)

    def run_now(self, schedule_id):
        self.store.get_schedule(schedule_id)
        self._enqueue(schedule_id, "manual")
        return {"scheduled": True}

    def status(self):
        with self.lock:
            active = json.loads(json.dumps(self._active, ensure_ascii=False)) if self._active else None
            queued = list(self._queued)
        return {"active": active, "queue_len": len(queued)}

    # -- threads -----------------------------------------------------------

    def _tick_loop(self):
        while not self._stop.wait(TICK_SECONDS):
            if self._closed:
                return
            self._enqueue_due()

    def _worker_loop(self):
        while True:
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                if self._closed:
                    return
                continue
            if item is None or self._closed:
                return
            schedule_id, trigger = item
            self._queued.discard(schedule_id)
            try:
                self.run_batch(schedule_id, trigger)
            except Exception:
                # run_batch records what it can; never let the worker die.
                pass

    def _enqueue_due(self):
        now = datetime.now()
        for schedule in self.store.schedules():
            if not schedule["enabled"] or schedule["trigger"]["type"] != "cron":
                continue
            nxt = schedule.get("next_run_at")
            if not nxt or datetime.fromisoformat(nxt) > now:
                continue
            def mutate(body, cron=schedule["trigger"]["cron"]):
                body["next_run_at"] = next_run(cron, now).isoformat(timespec="seconds")
            self._update_schedule(schedule["id"], mutate)
            self._enqueue(schedule["id"], "cron")

    def _enqueue(self, schedule_id, trigger):
        with self.lock:
            if schedule_id in self._queued:
                return False
            self._queued.add(schedule_id)
            self._queue.put((schedule_id, trigger))
            return True

    def _reschedule_all(self):
        now = datetime.now()
        for schedule in self.store.schedules():
            if not (schedule["enabled"] and schedule["trigger"]["type"] == "cron"):
                continue
            def mutate(body, cron=schedule["trigger"]["cron"]):
                body["next_run_at"] = next_run(cron, now).isoformat(timespec="seconds")
            self._update_schedule(schedule["id"], mutate)

    # -- store mutation ----------------------------------------------------

    def _update_schedule(self, schedule_id, mutate):
        with self.lock:
            try:
                schedule = self.store.get_schedule(schedule_id)
            except ValueError:
                return None
            mutate(schedule)
            self.store.save_schedule(schedule)
            return schedule

    # -- batch execution ---------------------------------------------------

    def run_batch(self, schedule_id, trigger):
        run_id = uuid.uuid4().hex
        try:
            schedule = self.store.get_schedule(schedule_id)
        except ValueError:
            return None
        recipe = next((r for r in self.store.recipes() if r["id"] == schedule["recipe_id"]), None)
        if not recipe:
            return None
        if len(recipe.get("slots", [])) != 1:
            return None
        source_dir = Path(schedule["source_dir"])
        if not source_dir.is_dir():
            return None
        files = sorted(
            (p for p in source_dir.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES),
            key=lambda p: p.name.lower(),
        )
        record = {
            "run_id": run_id,
            "trigger": trigger,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": None,
            "status": "running",
            "total": len(files),
            "succeeded": 0,
            "failed": 0,
            "items": [],
        }
        with self.lock:
            self._active = record
            self._active_id = schedule_id
        self._persist_run(schedule_id, record)
        run_folder = Path(schedule["output_dir"]) / f"{datetime.now():%Y%m%d_%H%M%S}_{run_id[:6]}"
        run_folder.mkdir(parents=True, exist_ok=True)
        for path in files:
            if self._stop.is_set() or schedule_id in self._cancelled:
                break
            item = {"input": path.name, "status": "running", "outputs": [], "error": None, "task_id": None, "finished_at": None}
            record["items"].append(item)
            self._persist_run(schedule_id, record)
            try:
                task = self.store.create()
                task["batch_run_id"] = run_id
                self.store.save(task)
                item["task_id"] = task["id"]
                self.store.import_file(task["id"], path)
                plan = self.store.recipe_plan(recipe["id"], task["id"])
                self._start_with_gate(task["id"], plan)
                self._await_terminal(task["id"], schedule_id)
                final = self.store.get(task["id"])
                if final["status"] == "succeeded":
                    item["outputs"] = self._copy_outputs(task["id"], run_folder, path.stem)
                    item["status"] = "succeeded"
                    record["succeeded"] += 1
                else:
                    item["status"] = "failed"
                    item["error"] = final.get("error") or ("已取消" if final["status"] == "cancelled" else "执行失败")
                    record["failed"] += 1
            except Exception as exc:
                item["status"] = "failed"
                item["error"] = str(exc)
                record["failed"] += 1
            item["finished_at"] = datetime.now().isoformat(timespec="seconds")
            self._persist_run(schedule_id, record)
        if schedule_id in self._cancelled:
            record["status"] = "cancelled"
        elif self._stop.is_set():
            record["status"] = "partial"
        elif record["failed"] == 0:
            record["status"] = "succeeded"
        elif record["succeeded"] == 0:
            record["status"] = "failed"
        else:
            record["status"] = "partial"
        record["finished_at"] = datetime.now().isoformat(timespec="seconds")
        self._finalize_run(schedule_id, record)
        with self.lock:
            if self._active_id == schedule_id:
                self._active = None
                self._active_id = None
        return record

    def _persist_run(self, schedule_id, record):
        def mutate(body):
            runs = body.get("runs", [])
            for i, run in enumerate(runs):
                if run["run_id"] == record["run_id"]:
                    runs[i] = record
                    break
            else:
                runs.append(record)
            body["runs"] = runs[-MAX_RUNS:]
        self._update_schedule(schedule_id, mutate)

    def _finalize_run(self, schedule_id, record):
        def mutate(body):
            body["last_run_at"] = record["finished_at"]
            runs = body.get("runs", [])
            for i, run in enumerate(runs):
                if run["run_id"] == record["run_id"]:
                    runs[i] = record
                    break
            else:
                runs.append(record)
            body["runs"] = runs[-MAX_RUNS:]
        self._update_schedule(schedule_id, mutate)

    def _start_with_gate(self, task_id, plan, timeout=1800):
        deadline = time.monotonic() + timeout
        while True:
            if self._closed or self._stop.is_set():
                raise ValueError("自动化服务已关闭")
            try:
                return self.jobs.start(task_id, plan=plan)
            except ValueError:
                if self.jobs.busy():
                    if time.monotonic() >= deadline:
                        raise ValueError("等待前序任务超时，请稍后重试")
                    time.sleep(self.gate_poll)
                    continue
                raise

    def _await_terminal(self, task_id, schedule_id):
        while True:
            if self._closed or self._stop.is_set() or schedule_id in self._cancelled:
                self.jobs.cancel(task_id)
                return
            record = self.store.get(task_id)
            if record["status"] in {"succeeded", "failed", "cancelled"}:
                return
            time.sleep(0.5)

    def _copy_outputs(self, task_id, run_folder, stem):
        record = self.store.get(task_id)
        outputs = record.get("outputs", [])
        copied = []
        for output in outputs:
            source, _ = self.store.resolve_file(task_id, output["id"])
            ext = source.suffix or ".xlsx"
            label = Path(str(output.get("name") or "输出")).stem
            base = sanitize(stem) if len(outputs) == 1 else f"{sanitize(stem)}_{sanitize(label)}"
            target = self._unique_path(run_folder, f"{base}{ext}")
            with source.open("rb") as src, target.open("xb") as dst:
                shutil.copyfileobj(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
            copied.append({"name": target.name, "path": str(target)})
        return copied

    def _unique_path(self, folder, name):
        target = folder / name
        if not target.exists():
            return target
        stem, ext = Path(name).stem, Path(name).suffix
        for n in range(2, 1000):
            candidate = folder / f"{stem}_{n}{ext}"
            if not candidate.exists():
                return candidate
        raise ValueError("输出文件名冲突过多")

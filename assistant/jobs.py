import asyncio
import multiprocessing
import threading
from pathlib import Path
import json
import uuid

from .store import Store
from .models import OperationPlan
from .tables import run_operation
from .agent import AgentRunner


def worker(root, task_id, plan, prompt, config):
    store = Store(Path(root))
    try:
        if prompt is not None:
            asyncio.run(AgentRunner(store, task_id, config).run(prompt))
        else:
            validated = OperationPlan.model_validate(plan)
            for i, operation in enumerate(validated.steps):
                store.event(task_id, "progress", f"正在执行第 {i + 1}/{len(validated.steps)} 步：{operation.kind}")
                output = run_operation(store, task_id, operation.model_dump())
                store.event(task_id, "output", output)
        store.finish_reviews(task_id, True)
        record = store.get(task_id)
        record["status"] = "succeeded"
        store.save(record)
    except Exception as exc:
        store.finish_reviews(task_id, False)
        record = store.get(task_id)
        record.update(status="failed", error=str(exc))
        store.save(record)
        store.event(task_id, "error", str(exc))


class Jobs:
    def __init__(self, store):
        self.store = store
        self.processes = {}
        self.watchers = []
        self.closed = False
        self.lock = threading.Lock()
        for task in store.list():
            if task["status"] in {"running", "waiting"}:
                store.finish_reviews(task['id'], False)
                task.update(status="failed", error="应用上次退出时任务中断，请重新执行")
                store.save(task)

    def start(self, task_id, plan=None, prompt=None, config=None):
        if prompt is None:
            plan = OperationPlan.model_validate(plan).model_dump()
        with self.lock:
            if self.closed:
                raise ValueError("任务管理器已关闭")
            # Reap handles only after observers finish using the Process objects.
            if not any(w.is_alive() for w in self.watchers):
                for old_id, old_process in list(self.processes.items()):
                    if not old_process.is_alive():
                        old_process.close()
                        del self.processes[old_id]
            if any(p.is_alive() for p in self.processes.values()):
                raise ValueError("首版一次执行一个任务，请等待或取消当前任务")
            record = self.store.get(task_id)
            record.update(status="running", error=None, run_id=uuid.uuid4().hex)
            if prompt is None:
                record["plan"] = plan
                record['editing_scope'] = None
            self.store.save(record)
            (self.store.directory(task_id) / "answer.json").unlink(missing_ok=True)
            process = multiprocessing.get_context("spawn").Process(target=worker, args=(str(self.store.root), task_id, plan, prompt, config or {}))
            process.start()
            self.processes[task_id] = process
            watcher = threading.Thread(target=self._watch, args=(task_id, process), daemon=True)
            self.watchers = [w for w in self.watchers if w.is_alive()]
            self.watchers.append(watcher)
            watcher.start()
        return {"task_id": task_id}

    def _watch(self, task_id, process):
        process.join(1800)
        if process.is_alive():
            self.cancel(task_id)
            self.store.event(task_id, "error", "任务超过 30 分钟，已取消")
        else:
            with self.lock:
                record = self.store.get(task_id)
                if record["status"] in {"running", "waiting"}:
                    self.store.finish_reviews(task_id, False)
                    record.update(status="failed", error="工作进程异常退出")
                    self.store.save(record)

    def cancel(self, task_id):
        import psutil
        with self.lock:
            process = self.processes.get(task_id)
            if not process or not process.is_alive():
                return False
            # Target only this task's owned process tree, never all Excel processes.
            try:
                parent = psutil.Process(process.pid)
                children = parent.children(recursive=True)
                for child in children:
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                parent.kill()
                psutil.wait_procs(children, timeout=5)
            except psutil.NoSuchProcess:
                pass
            process.join(5)
            self.store.finish_reviews(task_id, False)
            marker = self.store.directory(task_id) / "excel-process.json"
            if marker.exists():
                owner = json.loads(marker.read_text(encoding="utf-8"))
                try:
                    excel = psutil.Process(owner["pid"])
                    if abs(excel.create_time() - owner["created"]) < 0.01 and excel.name().lower() == "excel.exe":
                        excel.kill()
                        excel.wait(5)
                except psutil.NoSuchProcess:
                    pass
                marker.unlink(missing_ok=True)
            record = self.store.get(task_id)
            record.update(status="cancelled", error=None)
            self.store.save(record)
            self.store.event(task_id, "cancelled", "任务已取消；已完成的输出保留")
            return True

    def close(self):
        with self.lock:
            self.closed = True
            task_ids = list(self.processes)
            watchers = list(self.watchers)
        for task_id in task_ids:
            self.cancel(task_id)
        # A worker can finish before its watcher releases the SQLite connection.
        # Finish all observers before callers dispose of the task directory.
        for watcher in watchers:
            watcher.join()

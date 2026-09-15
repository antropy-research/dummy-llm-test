"""Bounded, round-robin scheduling with durable completion before refill."""

from __future__ import annotations

import signal
import threading
import time
from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait


class RunInterrupted(Exception):
    """The run drained and saved its results after an interrupt."""


class RunControl:
    def __init__(self):
        self.event = threading.Event()
        self.reason = None
        self._previous = None

    def stop(self, reason="interrupted"):
        if self.reason is None or reason == "interrupted":
            self.reason = reason
        self.event.set()

    def __enter__(self):
        if threading.current_thread() is threading.main_thread():
            self._previous = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, lambda *_: self.stop())
        return self

    def __exit__(self, *_):
        if self._previous is not None:
            signal.signal(signal.SIGINT, self._previous)


def dispatch(
    queues,
    concurrency,
    target_limits,
    execute,
    reserve,
    save,
    control,
    progress,
    total,
    completed=0,
    interval=10,
    on_dispatch=None,
):
    """Only submitted tasks consume slots; never enqueue work inside the executor.

    reserve(task) returns a stop reason or None and persists budget before dispatch.
    save(result) persists the response and may return a stop reason (unknown usage).
    """
    rotation = deque(queues)
    active = Counter()
    pending = {}
    started = time.monotonic()
    last_progress = started
    announced_stop = False
    worker_error = None

    def show():
        nonlocal last_progress
        last_progress = time.monotonic()
        descriptions = [
            f"{task[1]}/{task[0].id} (第 {task[2] + 1} 次, {last_progress - since:.0f}s)"
            for task, since in pending.values()
        ]
        detail = "; ".join(descriptions[:4]) or "无"
        if len(descriptions) > 4:
            detail += f"; 另 {len(descriptions) - 4} 题"
        progress(
            f"进度 {completed}/{total} · 运行中 {len(pending)}/{concurrency} · "
            f"本次耗时 {last_progress - started:.0f}s · {detail}"
        )

    show()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        while True:
            # Drain *all* observed completions before admitting another paid request.
            ready = [future for future in pending if future.done()]
            for future in ready:
                task, _ = pending[future]
                try:
                    result = future.result()
                except Exception as exc:
                    # A failing worker must not discard other already-paid responses.
                    worker_error = worker_error or exc
                    control.stop("harness_error")
                    del pending[future]
                    active[task[1]] -= 1
                    continue
                reason = save(result)
                del pending[future]
                active[task[1]] -= 1
                completed += 1
                if reason:
                    control.stop(reason)

            launched = False
            while len(pending) < concurrency and not control.event.is_set():
                chosen = None
                for _ in range(len(rotation)):
                    name = rotation[0]
                    rotation.rotate(-1)
                    if queues[name] and active[name] < target_limits[name]:
                        chosen = name
                        break
                if chosen is None:
                    break
                task = queues[chosen][0]
                reason = reserve(task)
                if reason:
                    control.stop(reason)
                    break
                # SIGINT can arrive during reservation: retain the conservative reservation,
                # but leave the unsubmitted task available for resume.
                if control.event.is_set():
                    break
                queues[chosen].popleft()
                if on_dispatch:
                    on_dispatch(task)
                pending[pool.submit(execute, task)] = (task, time.monotonic())
                active[chosen] += 1
                launched = True

            if control.event.is_set() and not announced_stop:
                progress(
                    f"停止派发 ({control.reason})；等待 {len(pending)} 个在途调用结束并保存，之后可续跑。"
                )
                announced_stop = True
                show()
            elif ready or launched or time.monotonic() - last_progress >= interval:
                show()
            if not pending:
                break
            wait(pending, timeout=min(0.25, interval), return_when=FIRST_COMPLETED)
    if worker_error is not None:
        raise worker_error
    return control.reason

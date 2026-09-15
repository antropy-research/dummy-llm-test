import signal
import threading
from collections import Counter, deque
from types import SimpleNamespace

import pytest

from dummy_llm_test.scheduler import RunControl, dispatch


def task(name, index):
    return SimpleNamespace(id=str(index)), name, 0, f"{name}-{index}"


def test_refills_while_first_request_is_still_running():
    third_started = threading.Event()
    saved = []

    def execute(item):
        if item[0].id == "0":
            assert third_started.wait(3), "Slow request blocked the next request"
        if item[0].id == "2":
            third_started.set()
        return item[3]

    dispatch(
        {"a": deque(task("a", i) for i in range(4))},
        2,
        {"a": 2},
        execute,
        lambda _: None,
        lambda result: saved.append(result),
        RunControl(),
        lambda _: None,
        4,
    )
    assert sorted(saved) == [f"a-{i}" for i in range(4)]


def test_global_and_target_limits_with_round_robin():
    first_wave = threading.Event()
    lock = threading.Lock()
    active = Counter()
    peak = Counter()
    order = []
    saved = []

    def execute(item):
        name = item[1]
        with lock:
            active[name] += 1
            active["total"] += 1
            for k, value in active.items():
                peak[k] = max(peak[k], value)
        try:
            assert first_wave.wait(3)
            return item[3]
        finally:
            with lock:
                active[name] -= 1
                active["total"] -= 1

    def reserve(item):
        order.append(item[1])

    def progress(_):
        if len(order) >= 3:
            first_wave.set()

    dispatch(
        {n: deque(task(n, i) for i in range(6)) for n in ("a", "b")},
        3,
        {"a": 1, "b": 2},
        execute,
        reserve,
        lambda r: saved.append(r),
        RunControl(),
        progress,
        12,
    )
    assert order[:3] == ["a", "b", "b"]
    assert peak["a"] <= 1 and peak["b"] <= 2 and peak["total"] <= 3
    assert len(saved) == len(set(saved)) == 12


def test_sigint_drains_without_dispatching_more_and_restores_handler():
    previous = signal.getsignal(signal.SIGINT)
    release = threading.Event()
    reserved, saved, messages = [], [], []
    queues = {"a": deque(task("a", i) for i in range(5))}
    control = RunControl()

    def execute(item):
        assert release.wait(3)
        return item[3]

    def progress(message):
        messages.append(message)
        if len(reserved) == 2 and not release.is_set():
            signal.raise_signal(signal.SIGINT)
            release.set()

    with control:
        reason = dispatch(
            queues,
            2,
            {"a": 2},
            execute,
            lambda t: reserved.append(t[3]),
            lambda r: saved.append(r),
            control,
            progress,
            5,
        )
    assert reason == "interrupted"
    assert set(saved) == set(reserved) == {"a-0", "a-1"}
    assert len(queues["a"]) == 3
    assert signal.getsignal(signal.SIGINT) == previous
    assert any("停止派发" in m for m in messages)


def test_missing_usage_drains_inflight_and_never_refills():
    release = threading.Event()
    reserved, saved = [], []

    def execute(item):
        assert release.wait(3)
        return item[3]

    def save(result):
        saved.append(result)
        return "usage_unknown"

    def progress(_):
        if len(reserved) == 2:
            release.set()

    reason = dispatch(
        {"a": deque(task("a", i) for i in range(5))},
        2,
        {"a": 2},
        execute,
        lambda t: reserved.append(t[3]),
        save,
        RunControl(),
        progress,
        5,
    )
    assert reason == "usage_unknown" and len(reserved) == len(saved) == 2


def test_heartbeat_while_waiting_without_completed_samples():
    release = threading.Event()
    heartbeats = []

    def execute(item):
        assert release.wait(3)
        return item

    def progress(message):
        if "运行中 1/1" in message:
            heartbeats.append(message)
            if len(heartbeats) == 2:
                release.set()

    dispatch(
        {"a": deque([task("a", 0)])},
        1,
        {"a": 1},
        execute,
        lambda _: None,
        lambda _: None,
        RunControl(),
        progress,
        1,
        interval=0.01,
    )
    assert len(heartbeats) >= 2


def test_signal_handler_restored_on_failure():
    previous = signal.getsignal(signal.SIGINT)
    with pytest.raises(ValueError), RunControl():
        raise ValueError("failure")
    assert signal.getsignal(signal.SIGINT) == previous


def test_worker_failure_preserves_other_inflight_response():
    release = threading.Event()
    saved, reserved = [], []

    def execute(item):
        if item[0].id == "0":
            raise ValueError("worker failed")
        assert release.wait(3)
        return item[3]

    def progress(message):
        if "停止派发" in message:
            release.set()

    with pytest.raises(ValueError, match="worker failed"):
        dispatch(
            {"a": deque(task("a", i) for i in range(5))},
            2,
            {"a": 2},
            execute,
            lambda t: reserved.append(t[3]),
            lambda r: saved.append(r),
            RunControl(),
            progress,
            5,
        )
    assert reserved == ["a-0", "a-1"] and saved == ["a-1"]

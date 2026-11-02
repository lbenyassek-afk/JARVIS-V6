from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager


_LOCK = threading.Lock()
_VALUES: dict[str, deque] = defaultdict(lambda: deque(maxlen=80))


def record(name: str, seconds: float) -> None:
    with _LOCK:
        _VALUES[str(name)].append(max(0.0, float(seconds)))


@contextmanager
def measure(name: str):
    started = time.perf_counter()
    try:
        yield
    finally:
        record(name, time.perf_counter() - started)


def snapshot() -> list[dict]:
    with _LOCK:
        copy = {name: list(values) for name, values in _VALUES.items()}
    rows = []
    for name, values in sorted(copy.items()):
        if values:
            rows.append({"name": name, "count": len(values), "latest_ms": round(values[-1] * 1000),
                         "average_ms": round(sum(values) / len(values) * 1000),
                         "maximum_ms": round(max(values) * 1000)})
    return rows

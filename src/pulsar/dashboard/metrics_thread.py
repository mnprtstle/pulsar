"""One persistent background loop for periodic metric polling, built
on Textual's thread-worker API.

Self-correcting cadence: each cycle times itself with
`time.monotonic()` and sleeps `max(0, next_due - elapsed)` instead of
a fixed wait. A tick that runs long is compensated on the very next
cycle instead of compounding into permanent drift.

A producer is has `(tick_fn, apply_fn, interval)`:
- `tick_fn` runs on the background thread, does psutil/build
  work it needs (reads the widget's  plain attributes directly
  - single writer on the main thread, single reader here,
  atomic under the GIL, no lock needed), and returns a fully-built
  result (e.g. a Rich `Text`) or `None` to skip this cycle.
- `apply_fn` runs on the main thread via `call_from_thread` and should
  only hand the result to a widget's `.update()`, avoid including text
  building, formatting in this function

Both `tick_fn` and `apply_fn` are bound methods defined in the owning
widget's file, so all metric-specific state and naming lives
in widget files.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from textual.app import App
from textual.worker import (
    Worker,
    get_current_worker,  # pyright: ignore [reportUnknownVariableType]
)

logger = logging.getLogger("pulsar.metrics")

TickFn = Callable[[bool], Any]
ApplyFn = Callable[[Any], None]


@dataclass
class _Producer:
    tick: TickFn
    apply: ApplyFn
    interval: (
        float | None
    )  # if not None, it means that the metric has longer interval than rest of the app
    last_run: float = 0.0  # will be used if interval is not None
    # Kept only for future removal-by-widget / debugging - the thread
    # never inspects this beyond identity.
    widget: Any = field(default=None, repr=False)


class MetricsThread:
    def __init__(self, app: App[Any], name: str, update_interval: float) -> None:
        self._app = app
        self.name = name
        self._producers: dict[str, _Producer] = {}
        self._expected: set[str] = set()
        self._wake = threading.Event()
        self._redraw_only = threading.Event()
        self._worker: Worker[Any] | None = None
        self._thread_running = False
        self._lock = threading.Lock()  # guards _producers - see note below
        self._interval = update_interval
        self._last_cycle_run = 0.0

    def expect(self, *keys: str) -> None:
        """Declare which producer keys must all be primed before the
        loop starts ticking, so it never runs against a half-populated
        set right after app startup. Call before `start()`."""
        self._expected = set(keys)

    def start(self) -> None:
        """Launches the persistent worker. If `expect()` was never
        called, the loop starts ticking as soon as it's launched -
        producers can still be primed (or unprimed) at any time after
        that"""
        if (not self._expected) or (self._expected == self._producers.keys()):
            self._worker = self._app.run_worker(
                self._run, thread=True, exclusive=True, group=self.name, name=self.name
            )

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        self._wake.set()

    def prime(
        self,
        key: str,
        tick: TickFn,
        apply: ApplyFn,
        interval: float | None = None,
        widget: Any = None,
    ) -> None:
        """Register (or replace) a producer. Thread-safe against the
        loop itself. Lock makes it thread safe"""
        with self._lock:
            self._producers[key] = _Producer(
                tick=tick,
                apply=apply,
                interval=interval,
                widget=widget,
            )

        if self._thread_running:
            self._wake.set()
        else:
            self.start()

    def unprime(self, key: str) -> None:
        """Drop a producer, e.g. when a widget is removed. The thread
        keeps running for whatever producers remain."""
        with self._lock:
            self._producers.pop(key, None)

    def set_interval(self, new_interval: float) -> None:
        """updating interval float is thread safe under GIL"""
        self._interval = new_interval
        self._wake.set()

    def request_repaint(self) -> None:
        """Repaint/redraw text"""
        self._wake.set()
        self._redraw_only.set()

    # --- the loop itself (runs on the background thread) ---------------
    def _run(self) -> None:
        self._thread_running = True
        worker = get_current_worker()  # pyright: ignore [reportUnknownVariableType]

        while not worker.is_cancelled:
            if self._redraw_only.is_set():
                redraw_only = True
                self._redraw_only.clear()
                cycle_start = self._last_cycle_run
            else:
                redraw_only = False
                cycle_start = time.monotonic()

            # Snapshot the producer list for this cycle under the lock,
            # then run ticks outside it
            with self._lock:
                producers = list(self._producers.items())

            for key, producer in producers:
                if producer.interval and (not redraw_only):
                    time_since_last_run = cycle_start - producer.last_run
                    if time_since_last_run < producer.interval:
                        continue

                try:
                    result = producer.tick(redraw_only)
                except Exception:
                    logger.exception("%s: producer '%s' tick failed", self.name, key)
                    continue

                producer.last_run = cycle_start

                if worker.is_cancelled:
                    self._thread_running = False
                    return

                if result is not None:
                    self._push(producer.apply, result)

            elapsed = time.monotonic() - cycle_start
            print("cycle time: ", elapsed)
            sleep_for = max(0.0, self._interval - elapsed)
            self._wake.wait(timeout=sleep_for)
            self._wake.clear()

        self._thread_running = False

    def _push(self, apply: ApplyFn, result: Any) -> None:
        try:
            self._app.call_from_thread(apply, result)
        except RuntimeError:
            # app tore down between the check above and the call
            # which is due to exiting the app, thus, dont log the error
            pass

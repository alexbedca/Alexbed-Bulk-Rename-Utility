"""Background jobs on Qt's global thread pool.

A Job wraps ``fn(progress, cancelled) -> result``. Every job carries a
generation number so the UI can drop results that are already stale (for
example, the user kept typing while an older preview was still computing).
"""
from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

JobFn = Callable[[Callable[[int, int], None], Callable[[], bool]], Any]


class JobSignals(QObject):
    progress = Signal(int, int, int)   # generation, done, total
    result = Signal(int, object)       # generation, result
    error = Signal(int, str)           # generation, traceback
    finished = Signal(int)


class Job(QRunnable):
    def __init__(self, generation: int, fn: JobFn) -> None:
        super().__init__()
        self.setAutoDelete(False)  # the owner keeps a reference until `finished`
        self.generation = generation
        self.fn = fn
        self.signals = JobSignals()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:
        gen = self.generation
        try:
            result = self.fn(lambda d, t: self.signals.progress.emit(gen, d, t), lambda: self._cancelled)
        except Exception:  # noqa: BLE001
            self.signals.error.emit(gen, traceback.format_exc())
        else:
            if not self._cancelled:
                self.signals.result.emit(gen, result)
        finally:
            self.signals.finished.emit(gen)


class JobRunner(QObject):
    """Keeps jobs alive while they run and starts them on the global pool."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._jobs: set[Job] = set()

    def start(self, job: Job) -> Job:
        self._jobs.add(job)
        job.signals.finished.connect(lambda _g, j=job: self._jobs.discard(j))
        QThreadPool.globalInstance().start(job)
        return job

    def cancel_all(self) -> None:
        for job in list(self._jobs):
            job.cancel()

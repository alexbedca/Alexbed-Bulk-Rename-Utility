# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Smart Media skill: metadata providers plus a thread-safe, cached store."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterable

MetaDict = dict[str, Any]


class MetadataProvider:
    """Reads one namespace of tags (e.g. 'audio') from a file.

    Subclasses set ``namespace`` and optionally ``extensions`` (lower-case,
    without dot). ``read`` must never raise for bad files: return {} instead.
    """

    namespace: str = ""
    extensions: frozenset[str] | None = None  # None means every file
    label: str = ""

    def supports(self, path: Path) -> bool:
        return self.extensions is None or path.suffix[1:].lower() in self.extensions

    def read(self, path: Path) -> MetaDict:
        raise NotImplementedError


PROVIDERS: dict[str, MetadataProvider] = {}


def register_provider(cls: type[MetadataProvider]) -> type[MetadataProvider]:
    PROVIDERS[cls.namespace] = cls()
    return cls


class MetadataStore:
    """Lazily reads metadata and caches it per (path, namespace).

    ``get`` is safe to call from any thread. ``preload`` reads many files in
    parallel; metadata reading is I/O-bound, so threads help.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], MetaDict] = {}
        self._lock = threading.Lock()

    def get(self, path: Path, namespace: str) -> MetaDict | None:
        """Return tags for ``namespace``; None if the namespace is unknown."""
        provider = PROVIDERS.get(namespace)
        if provider is None:
            return None
        key = (str(path), namespace)
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached
        data: MetaDict = {}
        if provider.supports(path):
            try:
                data = provider.read(path)
            except Exception:  # noqa: BLE001  (a corrupt file must not break the batch)
                data = {}
        with self._lock:
            self._cache[key] = data
        return data

    def all_for(self, path: Path) -> dict[str, MetaDict]:
        """Every namespace this file supports (used for the details panel)."""
        return {ns: self.get(path, ns) or {} for ns, prov in PROVIDERS.items() if prov.supports(path)}

    def preload(self, paths: Iterable[Path], namespaces: set[str],
                progress: Callable[[int, int], None] | None = None,
                cancelled: Callable[[], bool] | None = None, workers: int = 8) -> None:
        jobs = [(p, ns) for p in paths for ns in namespaces
                if ns in PROVIDERS and (str(p), ns) not in self._cache]
        if not jobs:
            return
        total = len(jobs)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for done, _ in enumerate(pool.map(lambda j: self.get(*j), jobs), 1):
                if progress and (done % 50 == 0 or done == total):
                    progress(done, total)
                if cancelled and cancelled():
                    pool.shutdown(wait=False, cancel_futures=True)
                    return

    def invalidate(self, paths: Iterable[Path] | None = None) -> None:
        with self._lock:
            if paths is None:
                self._cache.clear()
                return
            gone = {str(p) for p in paths}
            for key in [k for k in self._cache if k[0] in gone]:
                del self._cache[key]

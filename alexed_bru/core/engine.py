# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""RenameEngine: the UI-independent facade over the whole renaming core.

    from alexed_bru.core.engine import RenameEngine
    from alexed_bru.skills.rules import RegexRule, TemplateRule

    engine = RenameEngine([RegexRule(pattern=r"(\\d+)", replacement=r"Track \\1")])
    for row in engine.preview(paths):
        print(row.original, "->", row.proposed, row.status.label, row.message)
    result = engine.apply(paths)       # transactional, journalled when history is set
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

import alexed_bru.skills  # noqa: F401  (registers built-in rules & providers)
from alexed_bru.core.history import History
from alexed_bru.core.models import FileItem, Proposal, Status
from alexed_bru.core.pipeline import required_namespaces, run_pipeline
from alexed_bru.core.transaction import RenameOp, TransactionResult, execute
from alexed_bru.core.validation import DirectoryLister, validate
from alexed_bru.skills.base import Rule
from alexed_bru.skills.metadata import MetadataStore


@dataclass(frozen=True)
class PreviewRow:
    path: Path
    original: str
    proposed: str
    status: Status
    message: str

    @property
    def target(self) -> Path:
        return self.path.with_name(self.proposed)


class RenameEngine:
    def __init__(self, rules: Sequence[Rule] = (), store: MetadataStore | None = None,
                 history: History | None = None, auto_number: bool = False) -> None:
        self.rules: list[Rule] = list(rules)
        self.store = store or MetadataStore()
        self.history = history
        # Clashing new names get " (1)", " (2)"... instead of being skipped as errors.
        self.auto_number = auto_number

    # ---- computation (pure: never touches names on disk) -------------------
    def compute(self, items: Sequence[FileItem],
                progress: Callable[[int, int], None] | None = None,
                cancelled: Callable[[], bool] | None = None) -> list[Proposal] | None:
        """Proposals for each item (preloads only the metadata the rules need)."""
        needed = required_namespaces(self.rules)
        if needed:
            self.store.preload((i.path for i in items if i.include), needed, progress, cancelled)
        proposals = run_pipeline(items, self.rules, self.store, cancelled)
        if proposals is None:
            return None
        validate(items, proposals, DirectoryLister(), cancelled, self.auto_number)
        return proposals

    @staticmethod
    def items_for(paths: Iterable[Path | str],
                  overrides: Mapping[Path | str, str] | None = None) -> list[FileItem]:
        """FileItems for paths; `overrides` maps a path to a hand-typed new name."""
        by_key = {_key(p): name for p, name in (overrides or {}).items()}
        return [FileItem(Path(p), manual=by_key.get(_key(p)) or None, is_dir=Path(p).is_dir()) for p in paths]

    def preview(self, paths: Iterable[Path | str],
                overrides: Mapping[Path | str, str] | None = None) -> list[PreviewRow]:
        items = self.items_for(paths, overrides)
        proposals = self.compute(items) or []
        return [PreviewRow(i.path, i.name, p.new_name, p.status, p.message)
                for i, p in zip(items, proposals)]

    # ---- execution ----------------------------------------------------------
    @staticmethod
    def plan(items: Sequence[FileItem], proposals: Sequence[Proposal]) -> list[RenameOp]:
        return [RenameOp(i.path, i.path.with_name(p.new_name))
                for i, p in zip(items, proposals) if i.include and p.status.appliable]

    def apply_plan(self, ops: list[RenameOp], label: str = "",
                   progress: Callable[[int, int], None] | None = None) -> TransactionResult:
        result = execute(ops, progress)
        if result.ok and result.ops:
            self.store.invalidate(op.src for op in result.ops)
            if self.history is not None:
                self.history.record(result.ops, label or f"Renamed {len(result.ops)} file(s)")
        return result

    def apply(self, paths: Iterable[Path | str],
              overrides: Mapping[Path | str, str] | None = None) -> TransactionResult:
        items = self.items_for(paths, overrides)
        proposals = self.compute(items) or []
        return self.apply_plan(self.plan(items, proposals))


def _key(path: Path | str) -> str:
    return os.path.normcase(os.path.abspath(str(path)))

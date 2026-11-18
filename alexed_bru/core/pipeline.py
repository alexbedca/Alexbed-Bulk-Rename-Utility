# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs a rule stack over a list of files. Pure: never touches the disk."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Sequence

from alexed_bru.core.models import FileItem, Proposal, Status, join_name
from alexed_bru.core.tags import namespaces_in
from alexed_bru.skills.base import Rule
from alexed_bru.skills.metadata import MetaDict, MetadataStore


@dataclass
class RuleContext:
    """Per-file state handed to every rule."""

    item: FileItem
    index: int                 # position among included files (0-based)
    folder_index: int          # position within its folder (0-based)
    total: int
    store: MetadataStore
    warnings: list[str] = field(default_factory=list)

    def metadata(self, namespace: str) -> MetaDict | None:
        return self.store.get(self.item.path, namespace)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)


def active_rules(rules: Sequence[Rule]) -> list[Rule]:
    """Enabled rules whose configuration is valid (e.g. regex compiles)."""
    return [r for r in rules if r.enabled and r.config_error() is None]


def required_namespaces(rules: Sequence[Rule]) -> set[str]:
    needed: set[str] = set()
    for rule in active_rules(rules):
        for text in rule.template_fields():
            needed |= namespaces_in(text)
    return needed


def run_pipeline(items: Sequence[FileItem], rules: Sequence[Rule], store: MetadataStore,
                 cancelled: Callable[[], bool] | None = None) -> list[Proposal] | None:
    """Compute a proposal per item. Returns None if cancelled mid-way."""
    rules = active_rules(rules)
    total = sum(1 for i in items if i.include)
    per_folder: dict[str, int] = defaultdict(int)
    proposals: list[Proposal] = []
    index = 0
    for n, item in enumerate(items):
        if cancelled and n % 500 == 0 and cancelled():
            return None
        if not item.include:
            proposals.append(Proposal(item.name, Status.UNCHANGED, ["Excluded"]))
            continue
        if item.manual:
            # Typed by hand: used as is. It still takes its place in the
            # counting, so other files' numbers don't shift.
            status = Status.UNCHANGED if item.manual == item.name else Status.PENDING
            proposals.append(Proposal(item.manual, status, [], manual=True))
            index += 1
            per_folder[item.folder_key] += 1
            continue
        ctx = RuleContext(item, index, per_folder[item.folder_key], total, store)
        stem, ext = item.stem, item.ext
        try:
            for rule in rules:
                stem, ext = rule.apply(stem, ext, ctx)
        except Exception as exc:  # noqa: BLE001  (rule bugs become row errors, not crashes)
            proposals.append(Proposal(item.name, Status.ERROR, [f"{rule.LABEL} failed: {exc}"]))
        else:
            new_name = join_name(stem, ext)
            status = Status.UNCHANGED if new_name == item.name else Status.PENDING
            proposals.append(Proposal(new_name, status, list(ctx.warnings)))
        index += 1
        per_folder[item.folder_key] += 1
    return proposals

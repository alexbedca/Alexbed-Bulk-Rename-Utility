# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Quick Recipes: one-click starting points for everyday jobs.

A recipe is a list of ordinary rules (editable afterwards like any rule) plus, optionally,
an order to sort the list in first, so counters follow it. Shown as cards while the rule
list is empty, and under Presets afterwards.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from alexed_bru.skills import rules as r
from alexed_bru.skills.base import Rule


@dataclass(frozen=True)
class Recipe:
    key: str
    title: str
    example: tuple[str, str]           # shown when no files are listed yet
    make: Callable[[], list[Rule]]
    sort: str | None = None            # core.sorting key applied before numbering


def _strip_endings() -> Rule:
    params = next(p for t, _s, p in r.RegexRule.EXAMPLES if t.startswith("Remove ' - Copy'"))
    return r.RegexRule(**params)


RECIPES = [
    Recipe("music", "Organize music",
           ("track01.flac", "01. Nina Simone - Feeling Good.flac"),
           lambda: [r.TemplateRule(template="<track:2>. <artist> - <title>"), r.TrimRule()],
           sort="track"),
    Recipe("photos", "Photos by date taken",
           ("IMG_2041.jpg", "2023-06-01 - 001.jpg"),
           lambda: [r.TemplateRule(template="<date:%Y-%m-%d> - <num:3>")],
           sort="taken"),
    Recipe("downloads", "Clean web downloads",
           ("my_report%20final (1).pdf", "my report final.pdf"),
           lambda: [r.ReplaceRule(find="%20", replace=" "), _strip_endings(),
                    r.TrimRule(separators_to_spaces=True)]),
    Recipe("endings", "Strip copy and number endings",
           ("Report - Copy (2).docx", "Report.docx"),
           lambda: [_strip_endings()]),
]

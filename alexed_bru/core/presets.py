# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Save, load and share rule stacks as JSON."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from alexed_bru import APP_NAME, APP_VERSION
from alexed_bru.skills.base import Rule

FORMAT = "alexed-bru-preset"


def dump(rules: Sequence[Rule], name: str = "") -> dict:
    return {"format": FORMAT, "version": 1, "app": f"{APP_NAME} {APP_VERSION}",
            "name": name, "rules": [r.to_dict() for r in rules]}


def load_dict(data: dict) -> list[Rule]:
    if data.get("format") != FORMAT:
        raise ValueError("Not an Alexed Bulk Rename Utility preset")
    return [Rule.from_dict(r) for r in data.get("rules", [])]


def save(path: Path, rules: Sequence[Rule]) -> None:
    path.write_text(json.dumps(dump(rules, path.stem), indent=2, ensure_ascii=False), encoding="utf-8")


def load(path: Path) -> list[Rule]:
    return load_dict(json.loads(path.read_text(encoding="utf-8")))


def samples() -> dict[str, list[Rule]]:
    """Built-in starter presets shown in the Presets menu."""
    from alexed_bru.skills import rules as r

    return {
        "Music: 01. Artist - Title": [r.TemplateRule(template="<track:2>. <artist> - <title>")],
        "Music: Artist - Album - 01 Title": [
            r.TemplateRule(template="<artist> - <album> - <track:2> <title>")],
        "Music: tidy messy names": [
            r.RemoveRule(mode="brackets"),
            r.TrimRule(separators_to_spaces=True),
            r.CaseRule(mode="smart_title"),
            r.PadNumbersRule(width=2, which="first"),
        ],
        "Photos: date taken + counter": [
            r.TemplateRule(template="<date:%Y-%m-%d_%H%M%S>"),
            r.CounterRule(placement="suffix", separator="_", padding=3, reset_per_folder=True),
        ],
        "Documents: date-prefixed names": [
            r.TemplateRule(template="<modified:%Y-%m-%d> <name>"),
            r.TrimRule(separators_to_spaces=True),
        ],
        "Video: TV episodes (Show S01E01 - Title)": [
            r.TemplateRule(template="<show> S<season:2>E<episode:2> - <title>")],
        "Video: phone clips by recording date": [
            r.TemplateRule(template="<date:%Y-%m-%d_%H%M%S>"),
            r.CounterRule(placement="suffix", separator="_", padding=2, reset_per_folder=True),
        ],
        "Video: add quality tag [1080p]": [r.PrefixSuffixRule(suffix=" [<quality>]")],
        "Renumber existing numbers (01, 02, ...)": [
            r.CounterRule(placement="renumber_first", padding=2, separator=" ",
                          reset_per_folder=True, no_number="end")],
        "Add date prefix": [r.PrefixSuffixRule(prefix="<modified:%Y-%m-%d> ")],
        "Numbered sequence per folder": [
            r.CounterRule(placement="replace", padding=3, reset_per_folder=True),
            r.InsertRule(text="<folder> - ", position=0),
        ],
    }

# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Export the file list to CSV/TXT for editing elsewhere, and import edited names back.

Imported names become hand-typed names (``FileItem.manual``), so they get exactly the same
checks, Auto-number, all-or-nothing rename and History undo as names typed in the preview.
Nothing here touches the files themselves.

Spreadsheet safety: a cell that starts with = + - @ (or a tab/CR) could run as a formula
in Excel, so export puts a ' in front of it, and import removes that ' again. Rows that
don't match a listed file are reported, never guessed.
"""
from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from alexed_bru.core.models import FileItem, Proposal

HEADER = ["Folder", "Original name", "New name", "Status", "Details"]
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(text: str) -> str:
    return "'" + text if text.startswith(FORMULA_START) else text


def unsafe_cell(text: str) -> str:
    return text[1:] if text.startswith("'") and text[1:].startswith(FORMULA_START) else text


def _key(folder: str, name: str) -> str:
    return os.path.normcase(os.path.join(os.path.normpath(folder), name))


# ---- export ----------------------------------------------------------------------
def export_csv(path: Path, items: Sequence[FileItem], proposals: Sequence[Proposal]) -> int:
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:  # BOM: Excel reads UTF-8 correctly
        w = csv.writer(fh)
        w.writerow(HEADER)
        for item, prop in zip(items, proposals):
            status = prop.status.label if item.include else "Excluded"
            new = prop.new_name if item.include else item.name
            w.writerow([safe_cell(c) for c in (str(item.folder), item.name, new, status, prop.message)])
    return len(items)


def export_txt(path: Path, items: Sequence[FileItem], proposals: Sequence[Proposal]) -> int:
    """One line per file: original name, a tab, new name (edit the part after the tab)."""
    with open(path, "w", encoding="utf-8-sig", newline="\r\n") as fh:
        for item, prop in zip(items, proposals):
            fh.write(f"{item.name}\t{prop.new_name if item.include else item.name}\n")
    return len(items)


# ---- import ----------------------------------------------------------------------
@dataclass
class ImportResult:
    names: dict[int, str] = field(default_factory=dict)   # row in the list -> typed new name
    problems: list[str] = field(default_factory=list)
    unchanged: int = 0                                     # rows whose name stays the same


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def import_list(path: Path, items: Sequence[FileItem],
                current: Sequence[str] | None = None) -> ImportResult:
    """Match an edited CSV/TXT back to the listed files (see module docs).

    `current`: the names the app proposes now. A row whose name equals it wasn't edited in
    the sheet, so it is left to the rules (changing a rule later still updates it).
    """
    text = _read_text(path)
    result = _import_csv(text, items) if _is_csv(text) else _import_txt(text, items)
    if current is not None:
        for index in [i for i, name in result.names.items() if name == current[i]]:
            del result.names[index]
            result.unchanged += 1
    return result


def _is_csv(text: str) -> bool:
    first = text.lstrip().splitlines()[0] if text.strip() else ""
    head = first.lower()
    return "original name" in head and "new name" in head  # our CSV header (any delimiter)


def _import_csv(text: str, items: Sequence[FileItem]) -> ImportResult:
    dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t")  # Excel may save with ;
    rows = list(csv.reader(io.StringIO(text), dialect))
    header = [h.strip().lower() for h in rows[0]]
    col = {name: header.index(name.lower()) for name in HEADER if name.lower() in header}
    result = ImportResult()
    if "Original name" not in col or "New name" not in col:
        result.problems.append("The CSV needs the columns 'Original name' and 'New name'.")
        return result
    by_path = {_key(i.folder_key, i.name): n for n, i in enumerate(items)}
    by_name: dict[str, list[int]] = {}
    for n, i in enumerate(items):
        by_name.setdefault(os.path.normcase(i.name), []).append(n)

    def cell(row, name):
        k = col.get(name)
        return unsafe_cell(row[k].strip()) if k is not None and k < len(row) else ""

    for line, row in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in row):
            continue
        original, new, folder = cell(row, "Original name"), cell(row, "New name"), cell(row, "Folder")
        if folder:
            index = by_path.get(_key(folder, original))
        else:
            matches = by_name.get(os.path.normcase(original), [])
            index = matches[0] if len(matches) == 1 else None
            if len(matches) > 1:
                result.problems.append(f"Row {line}: “{original}” is in the list more than once; add its Folder.")
                continue
        if index is None:
            result.problems.append(f"Row {line}: “{original}” isn't in the list.")
            continue
        _take(result, index, items[index], new)
    return result


def _import_txt(text: str, items: Sequence[FileItem]) -> ImportResult:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    result = ImportResult()
    if lines and all("\t" in ln for ln in lines):  # "original<TAB>new", as exported
        by_name: dict[str, list[int]] = {}
        for n, i in enumerate(items):
            by_name.setdefault(os.path.normcase(i.name), []).append(n)
        for line_no, ln in enumerate(lines, start=1):
            original, new = (unsafe_cell(p.strip()) for p in ln.split("\t", 1))
            matches = by_name.get(os.path.normcase(original), [])
            if len(matches) != 1:
                result.problems.append(f"Line {line_no}: “{original}” "
                                       + ("is in the list more than once." if matches else "isn't in the list."))
                continue
            _take(result, matches[0], items[matches[0]], new)
        return result
    if len(lines) != len(items):  # plain list of new names: only by position
        result.problems.append(f"The file has {len(lines):,} name(s) but the list has {len(items):,} file(s). "
                               "A plain list of names must have exactly one line per file, in list order.")
        return result
    for n, (ln, item) in enumerate(zip(lines, items)):
        _take(result, n, item, unsafe_cell(ln.strip()))
    return result


def _take(result: ImportResult, index: int, item: FileItem, new: str) -> None:
    if not new or new == item.name:
        result.unchanged += 1
        return
    result.names[index] = new

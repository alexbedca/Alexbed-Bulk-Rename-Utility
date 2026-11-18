# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Write a RegEx from one example: a sample name and how it should look.

    >>> r = infer("Adele - Hello.mp3", "Hello - Adele")
    >>> r.pattern, r.replacement
    ('^(.+?) - (.+?)$', '\\\\2 - \\\\1')

How it works:

1. The sample (without its extension) is split into *fields*. Fields are
   separated by punctuation such as `` - ``, ``_``, ``.``, brackets, or two
   or more spaces, and by every switch between digits and letters. Words
   joined by single spaces stay one field ("Ed Sheeran").
2. The desired result is read left to right. Each piece is either a whole
   text field, a run of digits taken from a digit field (so ``20230601`` can
   be split into ``2023``, ``06``, ``01``), or new literal text.
3. The pattern repeats the sample's shape: used fields are captured, unused
   fields are matched and dropped, separators are matched literally. It is
   anchored with ``^`` and ``$``, so names with a different shape are left
   unchanged rather than mangled.
4. The pattern is run on the sample. Unless that gives exactly the desired
   result, nothing general is offered: the fallback renames only names
   identical to the sample.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from alexed_bru.core.models import split_name

IGNORE_CASE = True  # RegexRule's default; the self-check uses the same setting

_SEP_CHARS = r"\-_.,;:+~=!()\[\]{}"
_SEP = re.compile(rf"\s*[{_SEP_CHARS}]+\s*|\s{{2,}}")
_SEP_WORDS = re.compile(rf"\s*[{_SEP_CHARS}]+\s*|\s+")  # second pass: every space splits
_SPECIAL = re.compile(r"([.^$*+?{}\[\]\\|()])")  # what RegEx treats as special
_EXT_LIKE = re.compile(r"\.([A-Za-z][A-Za-z0-9]{0,4})$")


@dataclass
class Field:
    kind: str   # "sep", "digit" or "text"
    text: str
    slices: list[tuple[int, int]] = field(default_factory=list)  # digit pieces used
    used: bool = False


@dataclass
class Inference:
    ok: bool                 # False: nothing to offer (message says why)
    pattern: str = ""
    replacement: str = ""
    general: bool = False    # True: a real pattern; False: exact-name fallback
    message: str = ""


def tokenize(stem: str, words: bool = False) -> list[Field]:
    """Split a name into separator, digit and text fields (`words`: one field per word)."""
    out: list[Field] = []

    def add(kind: str, text: str) -> None:
        if not text:
            return
        if kind == "sep" and out and out[-1].kind == "sep":
            out[-1].text += text
        else:
            out.append(Field(kind, text))

    pos = 0
    for m in (_SEP_WORDS if words else _SEP).finditer(stem):
        _add_chunk(stem[pos:m.start()], add)
        add("sep", m.group(0))
        pos = m.end()
    _add_chunk(stem[pos:], add)
    return out


def _add_chunk(chunk: str, add) -> None:
    for piece in re.split(r"(\d+)", chunk):
        if not piece:
            continue
        if piece.isdigit():
            add("digit", piece)
            continue
        # Spaces next to a digit boundary belong to the separator, not the text.
        body = piece.strip()
        lead = piece[:len(piece) - len(piece.lstrip())]
        trail = piece[len(piece.rstrip()):]
        add("sep", lead)
        add("text", body)
        add("sep", trail)


def _esc(text: str) -> str:
    """Escape only RegEx specials, so patterns stay readable ("-" and spaces stay as they are)."""
    return _SPECIAL.sub(r"\\\1", text)


def _literal(text: str) -> str:
    """Text for a replacement template (backslashes and $n would be read as groups)."""
    return text.replace("\\", "\\\\").replace("$", "\\$") if ("\\" in text or "$" in text) else text


def _free_slice(f: Field, run: str) -> tuple[int, int] | None:
    """Leftmost place in a digit field where `run` occurs without overlapping used pieces."""
    start = f.text.find(run)
    while start >= 0:
        end = start + len(run)
        if all(end <= a or start >= b for a, b in f.slices):
            return start, end
        start = f.text.find(run, start + 1)
    return None


def _whole_word(text: str, pos: int, length: int) -> bool:
    """A one-letter field only counts where it stands alone (so "a" isn't found inside "cat")."""
    before = text[pos - 1] if pos > 0 else " "
    after = text[pos + length] if pos + length < len(text) else " "
    return not before.isalnum() and not after.isalnum()


def _map(fields: list[Field], desired: str) -> list[tuple]:
    """Desired result as parts: ("lit", text) | ("text", field) | ("digit", field, (a, b))."""
    parts: list[tuple] = []
    pos = 0
    while pos < len(desired):
        best = None
        digits = re.match(r"\d+", desired[pos:])
        if digits:
            run = digits.group(0)
            for f in fields:
                if f.kind == "digit":
                    where = _free_slice(f, run)
                    if where:
                        best = ("digit", f, where)
                        break
        if best is None:
            length = 0
            for f in fields:
                if f.kind == "text" and len(f.text) > length and desired.startswith(f.text, pos) \
                        and (len(f.text) >= 2 or _whole_word(desired, pos, len(f.text))):
                    best, length = ("text", f), len(f.text)
        if best is None:
            # literal text; a digit run nobody owns is taken whole
            take = digits.group(0) if digits else desired[pos]
            if parts and parts[-1][0] == "lit":
                parts[-1] = ("lit", parts[-1][1] + take)
            else:
                parts.append(("lit", take))
            pos += len(take)
            continue
        if best[0] == "digit":
            best[1].slices.append(best[2])
            pos += best[2][1] - best[2][0]
        else:
            pos += len(best[1].text)
        best[1].used = True
        parts.append(best)
    return parts


def _build(fields: list[Field], parts: list[tuple]) -> tuple[str, str]:
    groups: dict[tuple, int] = {}   # (id(field), slice) -> group number
    regex = ["^"]
    n = 0
    for f in fields:
        if f.kind == "sep":
            regex.append(_esc(f.text))
        elif f.kind == "text":
            if f.used:
                n += 1
                groups[(id(f), None)] = n
                regex.append("(.+?)")
            else:
                regex.append(".+?")
        elif not f.slices:
            if f.used:  # cannot happen: digit use always records a slice
                n += 1
                groups[(id(f), (0, len(f.text)))] = n
                regex.append(r"(\d+)")
            else:
                regex.append(r"\d+")
        elif f.slices == [(0, len(f.text))]:
            n += 1
            groups[(id(f), f.slices[0])] = n
            regex.append(r"(\d+)")
        else:
            # Split the digit run into fixed-width pieces at every used boundary.
            cuts = sorted({0, len(f.text), *[c for s in f.slices for c in s]})
            for a, b in zip(cuts, cuts[1:]):
                width = b - a
                if (a, b) in f.slices:
                    n += 1
                    groups[(id(f), (a, b))] = n
                    regex.append(rf"(\d{{{width}}})" if width > 1 else r"(\d)")
                elif b == len(f.text):
                    regex.append(r"\d*")  # extra trailing digits vary (e.g. IMG_..._142209123)
                else:
                    regex.append(rf"\d{{{width}}}" if width > 1 else r"\d")
    regex.append("$")

    repl = []
    for i, part in enumerate(parts):
        if part[0] == "lit":
            repl.append(_literal(part[1]))
            continue
        key = (id(part[1]), None) if part[0] == "text" else (id(part[1]), part[2])
        g = groups[key]
        following = parts[i + 1] if i + 1 < len(parts) else None
        # "\1" followed by a digit would read as "\12": use \g<1> there.
        next_is_digit = following is not None and (following[0] == "digit" or (
            following[0] == "lit" and following[1][:1].isdigit()))
        repl.append(rf"\g<{g}>" if next_is_digit else rf"\{g}")
    return "".join(regex), "".join(repl)


def _check(pattern: str, replacement: str, stem: str, desired: str) -> bool:
    try:
        rx = re.compile(pattern, re.IGNORECASE if IGNORE_CASE else 0)
        return rx.sub(lambda m: m.expand(replacement), stem, count=0) == desired
    except (re.error, IndexError):
        return False


def _exact(stem: str, desired: str, message: str) -> Inference:
    return Inference(True, f"^{_esc(stem)}$", _literal(desired), general=False, message=message)


def infer(sample: str, desired: str) -> Inference:
    """Pattern + replacement that turn `sample` into `desired` (see module docs)."""
    stem, ext = split_name(sample)
    desired = desired.strip()
    if ext and desired.lower().endswith("." + ext.lower()):
        desired = desired[:-len(ext) - 1]
    if not stem or not desired:
        return Inference(False, message="Type how the name should look.")
    if ext:
        other = _EXT_LIKE.search(desired)
        # A new ".xyz" ending that isn't text from the sample looks like an extension change
        # ("Report" -> "Report.pdf"); "a.b.c" -> "c.b.a" just reorders parts.
        if other and other.group(1).lower() != ext.lower() and other.group(1).lower() not in stem.lower():
            return Inference(False, message="To change the extension, add an Extension rule. "
                                            "Type the new name without it here.")
    if desired == stem:
        return Inference(False, message="That is the same as the sample name.")

    # First by whole fields ("Ed Sheeran" stays together), then word by word.
    for words in (False, True):
        fields = tokenize(stem, words)
        parts = _map(fields, desired)
        if any(p[0] != "lit" for p in parts):
            pattern, replacement = _build(fields, parts)
            if _check(pattern, replacement, stem, desired):
                return Inference(True, pattern, replacement, general=True)

    if desired.casefold() == stem.casefold():
        return Inference(False, message="Only capital letters change. RegEx can't change case: "
                                        "add a Change case rule instead.")
    return _exact(stem, desired, "No pattern found, so this only renames files named exactly "
                                 f"“{stem}”. Try a sample that shares more text with the result.")


def count_matches(pattern: str, names: list[str]) -> int:
    """How many names (matched without their extension) the pattern would change."""
    try:
        rx = re.compile(pattern, re.IGNORECASE if IGNORE_CASE else 0)
    except re.error:
        return 0
    return sum(1 for n in names if rx.search(split_name(n)[0]))

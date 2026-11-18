# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Built-in renaming rules (the "Rules" skill).

Every rule is pure: (stem, ext, context) -> (stem, ext). Text parameters
marked TEMPLATE accept <tags>, which are expanded per file.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from alexed_bru.core import tags
from alexed_bru.skills.base import (BOOL, CHOICE, INT, REGEX, TEMPLATE, TEXT, Rule, TargetedRule,
                                    param, register_rule)

# ==========================================================================
# Plain-English summaries (shown on the rule cards)
# ==========================================================================
def show(text: str, limit: int = 28) -> str:
    """Quote a value for a summary; make spaces and long values readable."""
    if text == " ":
        return "a space"
    if text == "":
        return "nothing"
    if len(text) > limit:
        text = text[:limit - 1] + "…"
    return f"“{text}”"


def scoped(rule: "Rule", sentence: str) -> str:
    """Add where a targeted rule works when it isn't the usual name-only."""
    where = {"ext": " (in the extension)", "full": " (in the whole name)"}.get(getattr(rule, "target", "name"), "")
    return sentence + where


# ==========================================================================
# Search & replace
# ==========================================================================
OCCURRENCES = [("all", "All occurrences"), ("first", "First only"), ("last", "Last only")]


@register_rule
@dataclass
class ReplaceRule(TargetedRule):
    TYPE = "replace"
    LABEL = "Find & Replace"
    CATEGORY = "Text"
    DESCRIPTION = ("Find literal text and replace all occurrences (or just the first/last). "
                   "Leave 'Replace with' empty to delete it. The replacement can contain <tags>.")

    find: str = param("", "Find", TEXT)
    replace: str = param("", "Replace with", TEMPLATE)
    case_sensitive: bool = param(False, "Case sensitive", BOOL)
    occurrence: str = param("all", "Occurrence", CHOICE, choices=OCCURRENCES)

    def summary(self) -> str:
        if not self.find:
            return "Type the text to find"
        which = {"first": " (first one only)", "last": " (last one only)"}.get(self.occurrence, "")
        if not self.replace:
            return scoped(self, f"Removes {show(self.find)}{which}")
        return scoped(self, f"Replaces {show(self.find)} with {show(self.replace)}{which}")

    def transform(self, text: str, ctx) -> str:
        if not self.find:
            return text
        flags = 0 if self.case_sensitive else re.IGNORECASE
        matches = list(re.finditer(re.escape(self.find), text, flags))
        if not matches:
            return text
        if self.occurrence == "first":
            matches = matches[:1]
        elif self.occurrence == "last":
            matches = matches[-1:]
        replacement = tags.expand(self.replace, ctx)
        out, pos = [], 0
        for m in matches:
            out.append(text[pos:m.start()])
            out.append(replacement)
            pos = m.end()
        out.append(text[pos:])
        return "".join(out)


# ==========================================================================
# Regular expressions
# ==========================================================================
@lru_cache(maxsize=256)
def compile_regex(pattern: str, ignore_case: bool) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE if ignore_case else 0)


_DOLLAR_GROUP = re.compile(r"\$(?:(\d+)|\{(\w+)\})")


def normalise_replacement(text: str) -> str:
    """Accept PowerRename/JS style $1 and ${name} as well as Python's \\1 / \\g<name>."""
    return _DOLLAR_GROUP.sub(lambda m: rf"\g<{m.group(1) or m.group(2)}>", text)


def _present_tense(title: str) -> str:
    """Examples-menu title -> card summary: "Remove x" -> "Removes x", "Date a to b" -> "Changes date a to b"."""
    first, _, rest = title.partition(" ")
    if first in ("Remove", "Put", "Swap", "Squash", "Keep"):
        return f"{first}s {rest}"
    return f"Changes {title[:1].lower()}{title[1:]}"


@register_rule
@dataclass
class RegexRule(TargetedRule):
    TYPE = "regex"
    LABEL = "RegEx Replace"
    CATEGORY = "Text"
    DESCRIPTION = ("Find text by pattern and replace it. Brackets ( ) capture parts you can "
                   "reuse as \\1, \\2 in the replacement. Not sure? Pick one of the Examples.")
    EXAMPLES = [
        ("Remove leading track numbers", "01 - Song  →  Song",
         {"pattern": r"^\d+\s*[-._]?\s*", "replacement": ""}),
        ("Put 'Track' before the number", "07 Song  →  Track 07 Song",
         {"pattern": r"^(\d+)", "replacement": r"Track \1"}),
        ("Swap 'Artist - Title' to 'Title - Artist'", "Adele - Hello  →  Hello - Adele",
         {"pattern": r"^(.+?) - (.+)$", "replacement": r"\2 - \1"}),
        ("Remove text in ( ) or [ ]", "Song (Live) [HD]  →  Song",
         {"pattern": r"\s*[(\[][^)\]]*[)\]]", "replacement": ""}),
        ("Spaces to underscores", "My Holiday Photo  →  My_Holiday_Photo",
         {"pattern": r"\s+", "replacement": "_"}),
        ("Squash repeated spaces and underscores", "My__file   name  →  My file name",
         {"pattern": r"[\s_]{2,}", "replacement": " "}),
        ("Remove ' - Copy' and ' (2)' endings", "Report - Copy (2)  →  Report",
         {"pattern": r"(\s*-\s*Copy)?(\s*\(\d+\))?$", "replacement": ""}),
        ("Date DD-MM-YYYY to YYYY-MM-DD", "Invoice 31-12-2024  →  Invoice 2024-12-31",
         {"pattern": r"(\d{2})[-.](\d{2})[-.](\d{4})", "replacement": r"\3-\2-\1"}),
        ("Phone photo name to readable date", "IMG_20230601_142209  →  2023-06-01 14.22.09",
         {"pattern": r"^(?:IMG|VID|PXL)_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\d*",
          "replacement": r"\1-\2-\3 \4.\5.\6"}),
        ("Keep only the part after the last ' - '", "Artist - Album - Song  →  Song",
         {"pattern": r"^.* - ", "replacement": ""}),
    ]

    pattern: str = param("", "Pattern", REGEX)
    replacement: str = param("", "Replace with", TEMPLATE)
    ignore_case: bool = param(True, "Ignore case", BOOL)
    count: int = param(0, "Max replacements (0 = all)", INT, minimum=0, maximum=999)

    def summary(self) -> str:
        if not self.pattern:
            return "Type a pattern, or pick an Example"
        for title, _sample, params in self.EXAMPLES:
            if params["pattern"] == self.pattern and params["replacement"] == self.replacement:
                return scoped(self, _present_tense(title))
        pattern = self.pattern if len(self.pattern) <= 30 else self.pattern[:29] + "…"
        if not self.replacement:
            return scoped(self, f"Removes text matching {pattern}")
        return scoped(self, f"Replaces text matching {pattern} with {show(self.replacement)}")

    def config_error(self) -> str | None:
        if not self.pattern:
            return None
        try:
            compile_regex(self.pattern, self.ignore_case)
        except re.error as exc:
            return f"Invalid pattern: {exc}"
        return None

    def regex(self) -> re.Pattern[str] | None:
        if not self.pattern or self.config_error():
            return None
        return compile_regex(self.pattern, self.ignore_case)

    def transform(self, text: str, ctx) -> str:
        rx = self.regex()
        if rx is None:
            return text
        # Tags first (they are per-file constants), then group references.
        template = normalise_replacement(tags.expand(self.replacement, ctx))
        return rx.sub(lambda m: m.expand(template), text, count=self.count)


# ==========================================================================
# Case
# ==========================================================================
CASE_MODES = [("title", "Title Case"), ("smart_title", "Smart Title Case"), ("upper", "UPPERCASE"),
              ("lower", "lowercase"), ("sentence", "Sentence case"), ("swap", "sWAP cASE")]

SMALL_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into", "nor", "of",
               "on", "or", "over", "the", "to", "vs", "via", "with", "feat", "ft"}

_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")  # keeps don't / it’s together


def title_case(text: str, smart: bool) -> str:
    words = list(_WORD.finditer(text))
    out, pos = [], 0
    for i, m in enumerate(words):
        word = m.group(0)
        out.append(text[pos:m.start()])
        prev = text[max(0, m.start() - 2):m.start()]
        boundary = i == 0 or i == len(words) - 1 or any(c in prev for c in "-([{.:")
        if smart and word.lower() in SMALL_WORDS and not boundary:
            out.append(word.lower())
        elif smart and word.isupper() and len(word) > 1 and not word.isdigit():
            out.append(word)  # keep acronyms: "AC DC", "USA"
        else:
            out.append(word[:1].upper() + word[1:].lower())
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def sentence_case(text: str) -> str:
    lowered = text.lower()
    return re.sub(r"(^\s*|[.!?]\s+)([^\W_])", lambda m: m.group(1) + m.group(2).upper(), lowered)


@register_rule
@dataclass
class CaseRule(TargetedRule):
    TYPE = "case"
    LABEL = "Change Case"
    CATEGORY = "Text"
    DESCRIPTION = "Title, Smart Title (keeps small words and acronyms), UPPER, lower, Sentence, Swap."

    mode: str = param("title", "Case", CHOICE, choices=CASE_MODES)

    def summary(self) -> str:
        return scoped(self, {
            "title": "Capitalises Each Word",
            "smart_title": "Capitalises words, keeping small words and acronyms",
            "upper": "Makes everything UPPERCASE",
            "lower": "Makes everything lowercase",
            "sentence": "Sentence case: only the first letter is a capital",
            "swap": "Swaps capitals and small letters",
        }[self.mode])

    def transform(self, text: str, ctx) -> str:
        if self.mode == "upper":
            return text.upper()
        if self.mode == "lower":
            return text.lower()
        if self.mode == "swap":
            return text.swapcase()
        if self.mode == "sentence":
            return sentence_case(text)
        return title_case(text, smart=self.mode == "smart_title")


# ==========================================================================
# Insert / remove / trim / pad
# ==========================================================================
@register_rule
@dataclass
class InsertRule(TargetedRule):
    TYPE = "insert"
    LABEL = "Insert Text"
    CATEGORY = "Position"
    DESCRIPTION = "Insert text (or <tags>) at a character position from the start or end."

    text: str = param("", "Text", TEMPLATE)
    position: int = param(0, "Position", INT, minimum=0, maximum=9999)
    from_end: bool = param(False, "Count from end", BOOL)

    def summary(self) -> str:
        if not self.text:
            return "Type the text to insert"
        if self.position == 0:
            where = "at the end" if self.from_end else "at the start"
        elif self.from_end:
            where = f"{self.position} character{'s' if self.position != 1 else ''} before the end"
        else:
            where = f"after character {self.position}"
        return scoped(self, f"Inserts {show(self.text)} {where}")

    def transform(self, text: str, ctx) -> str:
        value = tags.expand(self.text, ctx)
        pos = min(self.position, len(text))
        idx = len(text) - pos if self.from_end else pos
        return text[:idx] + value + text[idx:]


@register_rule
@dataclass
class PrefixSuffixRule(TargetedRule):
    TYPE = "affix"
    LABEL = "Add Prefix / Suffix"
    CATEGORY = "Text"
    DESCRIPTION = "Add text before and/or after the name. Both fields accept <tags>."

    prefix: str = param("", "Prefix", TEMPLATE)
    suffix: str = param("", "Suffix", TEMPLATE)
    skip_if_present: bool = param(True, "Don't add twice", BOOL,
                                  help="Skip when the name already starts/ends with it")

    def summary(self) -> str:
        if self.prefix and self.suffix:
            return scoped(self, f"Adds {show(self.prefix)} to the start and {show(self.suffix)} to the end")
        if self.prefix:
            return scoped(self, f"Adds {show(self.prefix)} to the start")
        if self.suffix:
            return scoped(self, f"Adds {show(self.suffix)} to the end")
        return "Type a prefix or a suffix"

    def transform(self, text: str, ctx) -> str:
        pre = tags.expand(self.prefix, ctx)
        suf = tags.expand(self.suffix, ctx)
        if pre and not (self.skip_if_present and text.startswith(pre)):
            text = pre + text
        if suf and not (self.skip_if_present and text.endswith(suf)):
            text = text + suf
        return text


REMOVE_MODES = [("range", "Character range"), ("chars", "Specific characters"),
                ("digits", "All digits"), ("symbols", "Symbols & punctuation"),
                ("brackets", "Bracketed text (…) […] {…}"), ("accents", "Accents (é → e)")]


@register_rule
@dataclass
class RemoveRule(TargetedRule):
    TYPE = "remove"
    LABEL = "Remove"
    CATEGORY = "Position"
    DESCRIPTION = "Remove a character range, a set of characters, digits, symbols, bracketed text or accents."

    mode: str = param("range", "Remove", CHOICE, choices=REMOVE_MODES)
    start: int = param(0, "Start position", INT, minimum=0, maximum=9999)
    count: int = param(1, "Count", INT, minimum=0, maximum=9999)
    from_end: bool = param(False, "Count from end", BOOL)
    characters: str = param("", "Characters", TEXT, help="Used when Remove = Specific characters")

    def summary(self) -> str:
        if self.mode == "range":
            n = f"{self.count} character{'s' if self.count != 1 else ''}"
            if self.start == 0:
                where = "from the end" if self.from_end else "from the start"
            elif self.from_end:
                where = f"ending {self.start} from the end"
            else:
                where = f"after character {self.start}"
            return scoped(self, f"Removes {n} {where}")
        if self.mode == "chars":
            if not self.characters:
                return "Type the characters to remove"
            return scoped(self, f"Removes every {' '.join(show(c) for c in dict.fromkeys(self.characters))}")
        return scoped(self, {
            "digits": "Removes all digits",
            "symbols": "Removes symbols and punctuation",
            "brackets": "Removes text inside ( ), [ ] and { }",
            "accents": "Removes accents (é → e)",
        }[self.mode])

    def transform(self, text: str, ctx) -> str:
        if self.mode == "range":
            n = len(text)
            if self.from_end:
                end = max(0, n - self.start)
                return text[:max(0, end - self.count)] + text[end:]
            return text[:self.start] + text[self.start + self.count:]
        if self.mode == "chars":
            return text.translate({ord(c): None for c in self.characters})
        if self.mode == "digits":
            return re.sub(r"\d", "", text)
        if self.mode == "symbols":
            return "".join(c for c in text if c.isalnum() or c.isspace() or c in "-_.")
        if self.mode == "brackets":
            prev = None
            while prev != text:  # handles nesting
                prev, text = text, re.sub(r"\s*[(\[{][^()\[\]{}]*[)\]}]", "", text)
            return text
        if self.mode == "accents":
            decomposed = unicodedata.normalize("NFKD", text)
            return "".join(c for c in decomposed if not unicodedata.combining(c))
        return text


@register_rule
@dataclass
class TrimRule(TargetedRule):
    TYPE = "trim"
    LABEL = "Trim & Clean"
    CATEGORY = "Position"
    DESCRIPTION = "Trim whitespace, collapse spaces, turn _ and . into spaces, cut N chars from either end."

    strip_whitespace: bool = param(True, "Trim leading/trailing spaces", BOOL)
    collapse_spaces: bool = param(True, "Collapse repeated spaces", BOOL)
    separators_to_spaces: bool = param(False, "Underscores / dots → spaces", BOOL)
    trim_chars: str = param("", "Also trim these characters", TEXT)
    cut_left: int = param(0, "Cut N chars from start", INT, minimum=0, maximum=9999)
    cut_right: int = param(0, "Cut N chars from end", INT, minimum=0, maximum=9999)

    def summary(self) -> str:
        bits = []
        if self.separators_to_spaces:
            bits.append("turns _ and . into spaces")
        if self.cut_left:
            bits.append(f"cuts {self.cut_left} from the start")
        if self.cut_right:
            bits.append(f"cuts {self.cut_right} from the end")
        if self.trim_chars:
            bits.append(f"trims {show(self.trim_chars)} from the ends")
        if self.collapse_spaces:
            bits.append("squashes double spaces")
        if self.strip_whitespace:
            bits.append("trims spaces at the ends")
        if not bits:
            return "Tick an option to clean names"
        text = ", ".join(bits[:3]) + (" and more" if len(bits) > 3 else "")
        return scoped(self, text[:1].upper() + text[1:])

    def transform(self, text: str, ctx) -> str:
        if self.cut_left:
            text = text[self.cut_left:]
        if self.cut_right:
            text = text[:-self.cut_right] if self.cut_right < len(text) else ""
        if self.separators_to_spaces:
            text = re.sub(r"[_.]+", " ", text)
        if self.collapse_spaces:
            text = re.sub(r"\s{2,}", " ", text)
        if self.trim_chars:
            text = text.strip(self.trim_chars)
        if self.strip_whitespace:
            text = text.strip()
        return text


PAD_WHICH = [("all", "All numbers"), ("first", "First number"), ("last", "Last number")]


@register_rule
@dataclass
class PadNumbersRule(TargetedRule):
    TYPE = "pad"
    LABEL = "Pad Numbers"
    CATEGORY = "Numbering"
    DESCRIPTION = "Zero-pad existing numbers so they sort correctly: 'Track 7' → 'Track 07'."

    width: int = param(2, "Width", INT, minimum=1, maximum=12)
    which: str = param("all", "Numbers", CHOICE, choices=PAD_WHICH)
    pad_char: str = param("0", "Pad character", TEXT)

    def summary(self) -> str:
        which = {"all": "numbers", "first": "the first number", "last": "the last number"}[self.which]
        example = "7".rjust(self.width, (self.pad_char or "0")[0])
        return scoped(self, f"Pads {which} to {self.width} digit{'s' if self.width != 1 else ''} (7 → {example})")

    def transform(self, text: str, ctx) -> str:
        fill = (self.pad_char or "0")[0]
        matches = list(re.finditer(r"\d+", text))
        if self.which == "first":
            matches = matches[:1]
        elif self.which == "last":
            matches = matches[-1:]
        for m in reversed(matches):
            digits = m.group(0).lstrip("0") or "0"
            text = text[:m.start()] + digits.rjust(self.width, fill) + text[m.end():]
        return text


# ==========================================================================
# Counter
# ==========================================================================
COUNTER_POS = [("prefix", "Prefix"), ("suffix", "Suffix"), ("replace", "Replace whole name"),
               ("index", "At position"), ("renumber_first", "Renumber: replace first number"),
               ("renumber_last", "Renumber: replace last number")]
NO_NUMBER = [("end", "Add the number at the end"), ("start", "Add the number at the start"),
             ("skip", "Leave the name unchanged")]


@register_rule
@dataclass
class CounterRule(TargetedRule):
    TYPE = "counter"
    LABEL = "Counter / Numbering"
    CATEGORY = "Numbering"
    DESCRIPTION = ("Sequential numbers with start, step, padding and optional reset per folder. "
                   "Renumber modes swap an existing number for the new sequence; "
                   "choose what happens to files that have no number.")

    start: int = param(1, "Start at", INT, minimum=-999999, maximum=999999)
    step: int = param(1, "Step", INT, minimum=-9999, maximum=9999)
    padding: int = param(2, "Pad to digits", INT, minimum=0, maximum=12)
    placement: str = param("prefix", "Placement", CHOICE, choices=COUNTER_POS)
    position: int = param(0, "Position (for 'At position')", INT, minimum=0, maximum=9999)
    separator: str = param(" - ", "Separator", TEXT)
    reset_per_folder: bool = param(False, "Restart in each folder", BOOL)
    no_number: str = param("end", "Renumber: files without a number", CHOICE, choices=NO_NUMBER)

    def summary(self) -> str:
        def num(v: int) -> str:
            return ("-" if v < 0 else "") + str(abs(v)).zfill(self.padding)
        seq = ", ".join(num(self.start + i * self.step) for i in range(3)) + "…"
        text = {
            "prefix": f"Numbers files {seq} at the start",
            "suffix": f"Numbers files {seq} at the end",
            "replace": f"Replaces names with {seq}",
            "index": f"Inserts {seq} after character {self.position}",
            "renumber_first": f"Renumbers the first number in each name: {seq}",
            "renumber_last": f"Renumbers the last number in each name: {seq}",
        }[self.placement]
        return scoped(self, text + (", restarting in each folder" if self.reset_per_folder else ""))

    def transform(self, text: str, ctx) -> str:
        n = ctx.folder_index if self.reset_per_folder else ctx.index
        value = self.start + n * self.step
        number = ("-" if value < 0 else "") + str(abs(value)).zfill(self.padding)
        if self.placement == "replace":
            return number
        if self.placement in ("renumber_first", "renumber_last"):
            found = list(re.finditer(r"\d+", text))
            if not found:
                # 'Photo.png' beside 'Photo 2.png': give it a number in the same
                # style rather than leaving the batch half renumbered.
                if self.no_number == "skip":
                    return text
                if self.no_number == "start":
                    return f"{number}{self.separator}{text}"
                return f"{text}{self.separator}{number}"
            m = found[0] if self.placement == "renumber_first" else found[-1]
            return text[:m.start()] + number + text[m.end():]
        if self.placement == "suffix":
            return f"{text}{self.separator}{number}"
        if self.placement == "index":
            pos = min(self.position, len(text))
            return text[:pos] + number + text[pos:]
        return f"{number}{self.separator}{text}"


# ==========================================================================
# Template & extension
# ==========================================================================
@register_rule
@dataclass
class TemplateRule(Rule):
    TYPE = "template"
    LABEL = "New Name from Template"
    CATEGORY = "Smart Media"
    DESCRIPTION = "Build the whole name from tags, e.g. <artist> - <title> or <track:2>. <title>."

    template: str = param("<artist> - <title>", "Template", TEMPLATE)
    fallback_to_original: bool = param(True, "Keep original if result is empty", BOOL)

    def summary(self) -> str:
        return f"Builds names as {self.template}" if self.template else "Type a template, e.g. <artist> - <title>"

    def apply(self, stem: str, ext: str, ctx) -> tuple[str, str]:
        result = tags.expand(self.template, ctx).strip()
        # A template whose tags are all missing yields only separators, like " - ".
        if self.fallback_to_original and not re.sub(r"[\s\-_.,()\[\]]", "", result):
            ctx.warn("Template empty; kept original name")
            return stem, ext
        return result, ext


EXT_MODES = [("lower", "lowercase"), ("upper", "UPPERCASE"), ("set", "Replace with"),
             ("append", "Append"), ("remove", "Remove")]


@register_rule
@dataclass
class ExtensionRule(Rule):
    TYPE = "extension"
    LABEL = "Extension"
    CATEGORY = "Text"
    DESCRIPTION = "Change extension case, replace it, append one, or remove it."

    mode: str = param("lower", "Action", CHOICE, choices=EXT_MODES)
    value: str = param("", "New extension", TEXT, help="Without the dot")

    def summary(self) -> str:
        value = self.value.lstrip(".")
        if self.mode in ("set", "append") and not value:
            return "Type the new extension"
        return {
            "lower": "Makes extensions lowercase",
            "upper": "Makes extensions UPPERCASE",
            "set": f"Changes the extension to .{value}",
            "append": f"Adds .{value} after the extension",
            "remove": "Removes the extension",
        }[self.mode]

    def apply(self, stem: str, ext: str, ctx) -> tuple[str, str]:
        value = self.value.lstrip(".")
        if self.mode == "lower":
            return stem, ext.lower()
        if self.mode == "upper":
            return stem, ext.upper()
        if self.mode == "set":
            return stem, value
        if self.mode == "append":
            return (f"{stem}.{ext}" if ext else stem), value
        if self.mode == "remove":
            return stem, ""
        return stem, ext

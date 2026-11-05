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
        return f"“{self.find}” → “{self.replace}”" if self.find else "Find & Replace (empty)"

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


@register_rule
@dataclass
class RegexRule(TargetedRule):
    TYPE = "regex"
    LABEL = "RegEx Replace"
    CATEGORY = "Text"
    DESCRIPTION = ("Python regular expressions. Use \\1, \\g<name> or $1 for groups; "
                   "<tags> work in the replacement.")

    pattern: str = param("", "Pattern", REGEX)
    replacement: str = param("", "Replace with", TEMPLATE)
    ignore_case: bool = param(True, "Ignore case", BOOL)
    count: int = param(0, "Max replacements (0 = all)", INT, minimum=0, maximum=999)

    def summary(self) -> str:
        return f"/{self.pattern}/ → {self.replacement}" if self.pattern else "RegEx (empty)"

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
        return dict(CASE_MODES)[self.mode]

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
        where = "end" if self.from_end else "start"
        return f"Insert “{self.text}” at {self.position} from {where}"

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
        if not (self.prefix or self.suffix):
            return "Add Prefix / Suffix (empty)"
        return f"“{self.prefix}” + name + “{self.suffix}”"

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
            return f"Remove {self.count} char(s) at {self.start}{' from end' if self.from_end else ''}"
        if self.mode == "chars":
            return f"Remove characters “{self.characters}”"
        return f"Remove {dict(REMOVE_MODES)[self.mode].lower()}"

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
            bits.append("_ . → space")
        if self.cut_left or self.cut_right:
            bits.append(f"cut {self.cut_left}/{self.cut_right}")
        if self.trim_chars:
            bits.append(f"trim “{self.trim_chars}”")
        return "Trim" + (": " + ", ".join(bits) if bits else " whitespace")

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
        return f"Pad {self.which} numbers to {self.width}"

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


@register_rule
@dataclass
class CounterRule(TargetedRule):
    TYPE = "counter"
    LABEL = "Counter / Numbering"
    CATEGORY = "Numbering"
    DESCRIPTION = ("Sequential numbers with start, step, padding and optional reset per folder. "
                   "Renumber modes swap an existing number for the new sequence "
                   "(files without a number get it as a prefix).")

    start: int = param(1, "Start at", INT, minimum=-999999, maximum=999999)
    step: int = param(1, "Step", INT, minimum=-9999, maximum=9999)
    padding: int = param(2, "Pad to digits", INT, minimum=0, maximum=12)
    placement: str = param("prefix", "Placement", CHOICE, choices=COUNTER_POS)
    position: int = param(0, "Position (for 'At position')", INT, minimum=0, maximum=9999)
    separator: str = param(" - ", "Separator", TEXT)
    reset_per_folder: bool = param(False, "Restart in each folder", BOOL)

    def summary(self) -> str:
        sample = str(self.start).zfill(self.padding)
        reset = " · per folder" if self.reset_per_folder else ""
        return f"Counter {sample}, step {self.step} ({self.placement}){reset}"

    def transform(self, text: str, ctx) -> str:
        n = ctx.folder_index if self.reset_per_folder else ctx.index
        value = self.start + n * self.step
        number = ("-" if value < 0 else "") + str(abs(value)).zfill(self.padding)
        if self.placement == "replace":
            return number
        if self.placement in ("renumber_first", "renumber_last"):
            found = list(re.finditer(r"\d+", text))
            if not found:
                return f"{number}{self.separator}{text}"
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
        return self.template or "Template (empty)"

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
        label = dict(EXT_MODES)[self.mode]
        return f"Extension: {label} {self.value}".strip() if self.mode in ("set", "append") \
            else f"Extension: {label}"

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

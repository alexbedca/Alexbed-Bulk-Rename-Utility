# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""The RegEx guide dialog: a short, practical cheat sheet for renaming."""
from __future__ import annotations

from html import escape

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout, QWidget

from alexed_bru.skills.rules import RegexRule
from alexed_bru.ui.theme import C

# (pattern, meaning) rows of the cheat sheet, grouped.
CHEATSHEET: list[tuple[str, list[tuple[str, str]]]] = [
    ("Match characters", [
        (r"abc", "the exact text abc"),
        (r".", "any one character"),
        (r"\d", "a digit 0-9"),
        (r"\s", "a space (or tab)"),
        (r"\w", "a letter, digit or _"),
        (r"[abc]", "one of a, b or c"),
        (r"[^abc]", "any character except a, b, c"),
        (r"\. \( \[ \-", "a literal . ( [ or -  (a backslash removes the special meaning)"),
    ]),
    ("How many", [
        (r"+", "one or more of the thing before it:  \\d+  matches 7, 42, 2024"),
        (r"*", "zero or more"),
        (r"?", "optional (zero or one)"),
        (r"{4}", "exactly 4:  \\d{4}  matches a year"),
        (r"{2,}", "2 or more"),
        (r"+?  *?", "as few as possible (stop at the first match)"),
    ]),
    ("Where", [
        (r"^", "start of the name"),
        (r"$", "end of the name (before the extension)"),
        (r"\b", "a word boundary"),
    ]),
    ("Capture and reuse", [
        (r"( ... )", "capture a part; reuse it as \\1, \\2 ... in Replace with"),
        (r"(?: ... )", "group without capturing"),
        (r"(?P<year>\d{4})", "a named capture; reuse it as \\g<year>"),
        (r"a|b", "a or b"),
    ]),
]


def guide_html() -> str:
    def code(t: str) -> str:
        return f"<code style='color:{C.CYAN}; font-family:Consolas'>{escape(t)}</code>"

    parts = [
        f"<h2 style='color:{C.TEXT}'>RegEx in 60 seconds</h2>",
        "<p>A regular expression (RegEx) is a <b>pattern</b> that describes text. The "
        "<b>RegEx Replace</b> rule finds every part of the file name that matches the pattern and "
        "swaps it for <b>Replace with</b>. Only the name changes; the extension is left alone "
        "unless you set <i>Apply to</i>.</p>",
        "<p><b>How to work:</b> type a pattern and watch the preview. Matches are highlighted in the "
        "<i>Original name</i> column (each captured group in its own colour), and nothing on disk "
        "changes until you press <i>Rename files</i>. A red pattern box means the pattern has a "
        "mistake.</p>",
    ]
    for title, rows in CHEATSHEET:
        parts.append(f"<h3 style='color:{C.ACCENT_HI}'>{title}</h3><table cellspacing='0' cellpadding='3'>")
        for pat, meaning in rows:
            parts.append(f"<tr><td width='140'>{code(pat)}</td><td>{escape(meaning)}</td></tr>")
        parts.append("</table>")

    parts.append(f"<h3 style='color:{C.ACCENT_HI}'>Worked example</h3>"
                 f"<p>Name: {code('01 - Adele - Hello')}<br>"
                 f"Pattern: {code(r'^(\d+) - (.+?) - (.+)$')}<br>"
                 f"Replace with: {code(r'\3 (\2) \1')}<br>"
                 f"Result: {code('Hello (Adele) 01')}</p>"
                 "<p>Read the pattern left to right: <i>start</i>, capture digits as group 1, "
                 "a dash, capture as little as possible as group 2 (the artist), a dash, capture "
                 "the rest as group 3 (the title), <i>end</i>.</p>")

    parts.append(f"<h3 style='color:{C.ACCENT_HI}'>Recipes (also in the Examples menu)</h3>"
                 "<table cellspacing='0' cellpadding='3'>")
    for title, sample, params in RegexRule.EXAMPLES:
        parts.append(f"<tr><td><b>{escape(title)}</b><br><span style='color:{C.DIM}'>{escape(sample)}</span></td>"
                     f"<td>{code(params['pattern'])}<br>&rarr; {code(params['replacement'] or '(nothing)')}</td></tr>")
    parts.append("</table>")

    parts.append(f"<h3 style='color:{C.ACCENT_HI}'>Tips</h3><ul>"
                 "<li><b>Ignore case</b> is on by default, so <code>copy</code> also matches <i>Copy</i>.</li>"
                 "<li>You can mix tags into Replace with, e.g. <code>&lt;year&gt; \\1</code>.</li>"
                 "<li><code>$1</code> works the same as <code>\\1</code> if you know RegEx from elsewhere.</li>"
                 "<li>Prefer plain <b>Find &amp; Replace</b> when you just want to swap fixed text.</li>"
                 "</ul>")
    return "".join(parts)


class RegexGuide(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("RegEx guide")
        self.resize(720, 640)
        lay = QVBoxLayout(self)
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        view.setHtml(guide_html())
        lay.addWidget(view)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

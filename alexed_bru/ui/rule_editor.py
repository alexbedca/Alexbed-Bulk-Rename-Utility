# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rule stack list and the auto-generated parameter editor."""
from __future__ import annotations

from collections import defaultdict
from html import escape
from typing import Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
                               QPushButton, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from alexed_bru.core.tags import TAG_CATALOGUE
from alexed_bru.skills.base import BOOL, CHOICE, INT, REGEX, RULE_REGISTRY, TEMPLATE, Rule
from alexed_bru.ui.icons import icon
from alexed_bru.ui.theme import C


def menu_text(text: str) -> str:
    """Qt reads "&" in menu text as a keyboard-shortcut marker ("Find & Replace" showed as
    "Find _Replace"); "&&" shows a real ampersand."""
    return text.replace("&", "&&")


def rules_menu(parent: QWidget, on_pick) -> QMenu:
    """'Add rule' menu grouped by category."""
    menu = QMenu(parent)
    groups: dict[str, list[type[Rule]]] = defaultdict(list)
    for cls in RULE_REGISTRY.values():
        groups[cls.CATEGORY].append(cls)
    for i, category in enumerate(["Text", "Position", "Numbering", "Smart Media"]):
        if i:
            menu.addSeparator()
        menu.addSection(category)
        for cls in groups.get(category, []):
            act = menu.addAction(menu_text(cls.LABEL))
            act.setToolTip(cls.DESCRIPTION)
            act.triggered.connect(lambda _=False, c=cls: on_pick(c))
    menu.setToolTipsVisible(True)
    return menu


def tags_menu(parent: QWidget, on_pick) -> QMenu:
    menu = QMenu("Insert tag", parent)
    menu.setToolTipsVisible(True)
    for group, entries in TAG_CATALOGUE:
        sub = menu.addMenu(group)
        sub.setToolTipsVisible(True)
        for tag, desc in entries:
            act = QAction(menu_text(f"{tag}    {desc}"), sub)
            act.triggered.connect(lambda _=False, t=tag: on_pick(t))
            sub.addAction(act)
    return menu


# ==========================================================================
class RuleRow(QWidget):
    """One entry in the rule stack: [toggle] [n] title / summary."""

    toggled = Signal(bool)

    def __init__(self, number: int, rule: Rule) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_TranslucentBackground)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(10)
        self.check = QCheckBox()
        self.check.setChecked(rule.enabled)
        self.check.setToolTip("Enable / disable this rule")
        self.check.toggled.connect(self.toggled)
        badge = QLabel(str(number))
        badge.setFixedSize(22, 22)
        badge.setAlignment(Qt.AlignCenter)
        error = rule.config_error()
        badge_bg = C.ERROR if error else (C.ACCENT if rule.enabled else C.SURFACE_3)
        badge.setStyleSheet(f"background:{badge_bg}; border-radius:11px; font-weight:700; "
                            f"font-size:8pt; color:white;")
        text = QVBoxLayout()
        text.setSpacing(0)
        title = QLabel(rule.LABEL)
        title.setStyleSheet(f"font-weight:600; color:{C.TEXT if rule.enabled else C.FAINT};")
        full = error or rule.summary()
        summary = QLabel()
        summary.setStyleSheet(f"font-size:8.5pt; color:{C.ERROR if error else C.DIM};")
        summary.setMaximumWidth(260)
        # One line on the card ("…" if long); the tooltip has the whole sentence.
        summary.setText(summary.fontMetrics().elidedText(full, Qt.ElideRight, 255))
        summary.setToolTip(full)
        self.summary_text = full
        text.addWidget(title)
        text.addWidget(summary)
        lay.addWidget(self.check)
        lay.addWidget(badge)
        lay.addLayout(text, 1)


class RuleStack(QListWidget):
    """Reorderable list of rules. The window owns the list of Rule objects."""

    orderChanged = Signal(list)        # new order as list of original indices
    enabledChanged = Signal(int, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.model().rowsMoved.connect(self._on_moved)

    def populate(self, rules: list[Rule], select: int | None = None) -> None:
        self.blockSignals(True)
        self.clear()
        for n, rule in enumerate(rules):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, n)
            item.setSizeHint(QSize(0, 54))
            self.addItem(item)
            row = RuleRow(n + 1, rule)
            row.toggled.connect(lambda on, i=n: self.enabledChanged.emit(i, on))
            self.setItemWidget(item, row)
        self.blockSignals(False)
        if select is not None and 0 <= select < len(rules):
            self.setCurrentRow(select)
        else:
            self.currentRowChanged.emit(self.currentRow())

    def _on_moved(self, *_args) -> None:
        order = [self.item(i).data(Qt.UserRole) for i in range(self.count())]
        self.orderChanged.emit(order)


# ==========================================================================
class RuleEditor(QWidget):
    """Builds a form from a rule's dataclass fields; edits the rule in place."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rule: Rule | None = None
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(8)
        self.focused_template: QLineEdit | None = None
        # File names for "Generate from example": selected files first, then the rest.
        self.sample_names: Callable[[], list[str]] = lambda: []
        self._gen_open = False
        self._gen_sample = ""
        self._gen_desired = ""
        self._gen_note = ""
        self._generated = None
        self.generator: QFrame | None = None
        self.set_rule(None)

    def _clear(self) -> None:
        while self._lay.count():
            item = self._lay.takeAt(0)
            if item.widget():
                _dispose(item.widget())
            elif item.layout():
                _drop_layout(item.layout())

    def set_rule(self, rule: Rule | None) -> None:
        self.rule = rule
        self._regex_edit = None
        self._clear()
        if rule is None:
            hint = QLabel("Add a rule to start building your rename pipeline.\n\n"
                          "Rules run top to bottom. Drag them to reorder, untick to bypass.")
            hint.setObjectName("Faint")
            hint.setWordWrap(True)
            self._lay.addWidget(hint)
            self._lay.addStretch(1)
            return

        title = QLabel(rule.LABEL)
        title.setObjectName("RuleTitle")
        desc = QLabel(rule.DESCRIPTION)
        desc.setObjectName("Dim")
        desc.setWordWrap(True)
        self._lay.addWidget(title)
        self._lay.addWidget(desc)
        if rule.EXAMPLES:
            self._lay.addLayout(self._examples_row(rule))
        self.generator = None
        if rule.TYPE == "regex":
            self.generator = self._build_generator()
            self._lay.addWidget(self.generator)

        # Labels above their fields: the panel is narrow, and long labels or
        # options side by side were cut off at the right edge.
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(4)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.error_label = QLabel()
        self.error_label.setObjectName("ErrorText")
        self.error_label.setWordWrap(True)
        for f in rule.params():
            meta = f.metadata
            widget = self._make_widget(rule, f.name, meta)
            if meta["kind"] == BOOL:
                form.addRow(widget)
            else:
                label = QLabel(meta["label"])
                label.setObjectName("Dim")
                label.setContentsMargins(0, 6, 0, 0)
                form.addRow(label, widget)
            if meta.get("help"):
                helper = QLabel(meta["help"])
                helper.setObjectName("Faint")
                helper.setStyleSheet("font-size:8.5pt;")
                helper.setWordWrap(True)
                form.addRow(helper)
        self._lay.addLayout(form)
        self._lay.addWidget(self.error_label)
        self._lay.addStretch(1)
        self._refresh_error()

    def _examples_row(self, rule: Rule) -> QHBoxLayout:
        """'Examples' menu that fills in the fields, plus the RegEx guide."""
        row = QHBoxLayout()
        row.setSpacing(6)
        examples = QToolButton()
        examples.setText("Examples")
        examples.setIcon(icon("chevron"))
        examples.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        examples.setLayoutDirection(Qt.RightToLeft)
        examples.setPopupMode(QToolButton.InstantPopup)
        examples.setToolTip("Fill in a ready-made pattern; the preview shows the result at once")
        menu = QMenu(examples)
        menu.setLayoutDirection(Qt.LeftToRight)  # the button is RTL only to put its arrow last
        for title, sample, params in rule.EXAMPLES:
            act = menu.addAction(menu_text(f"{title}\t{sample}"))
            act.triggered.connect(lambda _=False, p=params: self.use_example(p))
        examples.setMenu(menu)
        row.addWidget(examples)
        if rule.TYPE == "regex":
            guide = QToolButton()
            guide.setText("RegEx guide")
            guide.setObjectName("Flat")
            guide.setToolTip("How patterns work, with a cheat sheet")
            guide.clicked.connect(self.show_regex_guide)
            row.addWidget(guide)
            self.gen_toggle = QToolButton()
            self.gen_toggle.setText("From example")
            self.gen_toggle.setObjectName("Flat")
            self.gen_toggle.setCheckable(True)
            self.gen_toggle.setChecked(self._gen_open)
            self.gen_toggle.setToolTip("Show how one file name should look; the pattern is written for you")
            self.gen_toggle.toggled.connect(self._toggle_generator)
            row.addWidget(self.gen_toggle)
        row.addStretch(1)
        return row

    # ---- Generate from example ---------------------------------------------
    def _build_generator(self) -> QFrame:
        box = QFrame()
        box.setObjectName("Generator")
        box.setStyleSheet(f"#Generator {{ background:{C.SURFACE_2}; border:1px solid {C.BORDER}; "
                          f"border-radius:8px; }}")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(4)
        head = QLabel("Generate from example")
        head.setStyleSheet("font-weight:600;")
        lay.addWidget(head)
        lab = QLabel("Sample name")
        lab.setObjectName("Dim")
        lay.addWidget(lab)
        self.gen_sample = QComboBox()
        self.gen_sample.setEditable(True)
        self.gen_sample.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.gen_sample.setMinimumContentsLength(10)
        self.gen_sample.lineEdit().setPlaceholderText("A file name from your list")
        lay.addWidget(self.gen_sample)
        lab = QLabel("How it should look")
        lab.setObjectName("Dim")
        lab.setContentsMargins(0, 4, 0, 0)
        lay.addWidget(lab)
        self.gen_desired = QLineEdit(self._gen_desired)
        self.gen_desired.setClearButtonEnabled(True)
        self.gen_desired.setPlaceholderText("Type the new name (extension optional)")
        lay.addWidget(self.gen_desired)
        self.gen_status = QLabel()
        self.gen_status.setWordWrap(True)
        self.gen_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.gen_status.setContentsMargins(0, 4, 0, 0)
        lay.addWidget(self.gen_status)
        self.gen_use = QPushButton("Use this pattern")
        self.gen_use.setObjectName("Primary")
        self.gen_use.clicked.connect(self._use_generated)
        lay.addWidget(self.gen_use, 0, Qt.AlignLeft)

        self._fill_samples()
        self.gen_sample.currentTextChanged.connect(self._update_generated)
        self.gen_desired.textChanged.connect(self._update_generated)
        box.setVisible(self._gen_open)
        self._update_generated()
        return box

    def _fill_samples(self) -> None:
        names = self.sample_names()[:300]
        current = self._gen_sample or (names[0] if names else "")
        self.gen_sample.blockSignals(True)
        self.gen_sample.clear()
        self.gen_sample.addItems(names)
        self.gen_sample.setEditText(current)
        self.gen_sample.blockSignals(False)

    def _toggle_generator(self, on: bool) -> None:
        self._gen_open = on
        if self.generator is None:
            return
        if on:
            self._gen_sample = ""  # start from the file selected now
            self._fill_samples()
            self._update_generated()
        self.generator.setVisible(on)
        if on:
            self.gen_desired.setFocus()

    def _update_generated(self, *_args) -> None:
        from alexed_bru.skills.regex_infer import count_matches, infer
        self._gen_sample = self.gen_sample.currentText()
        self._gen_desired = self.gen_desired.text()
        self._generated = None
        self.gen_use.setEnabled(False)
        if self._gen_note:  # shown once, right after "Use this pattern"
            note, self._gen_note = self._gen_note, ""
            self._set_gen_status(escape(note), C.OK)
            return
        if not self._gen_sample.strip():
            self._set_gen_status("Add files to the list, or type a sample name.", C.DIM)
            return
        if not self._gen_desired.strip():
            self._set_gen_status("Type how this name should look. The pattern is written for you.", C.DIM)
            return
        result = infer(self._gen_sample, self._gen_desired)
        if not result.ok:
            self._set_gen_status(escape(result.message), C.WARN)
            return
        self._generated = result
        names = self.sample_names()
        mono = "font-family:Consolas,monospace;"
        rule = (f"<span style='{mono} color:{C.CYAN}'>{escape(result.pattern)}</span> → "
                f"<span style='{mono} color:{C.CYAN}'>{escape(result.replacement) or '(nothing)'}</span>")
        if result.general:
            hits = count_matches(result.pattern, names)
            self._set_gen_status(f"{rule}<br>Matches {hits:,} of {len(names):,} file(s) in the list.", C.TEXT)
        else:
            self._set_gen_status(f"{escape(result.message)}<br>{rule}", C.WARN)
        self.gen_use.setEnabled(True)

    def _set_gen_status(self, html: str, colour: str) -> None:
        self.gen_status.setText(f"<span style='color:{colour}'>{html}</span>")

    def _use_generated(self) -> None:
        result = self._generated
        if result is None or self.rule is None:
            return
        self._gen_note = "Pattern filled in below. Check the preview, then press Rename files."
        self.use_example({"pattern": result.pattern, "replacement": result.replacement})

    def use_example(self, params: dict) -> None:
        if self.rule is None:
            return
        for name, value in params.items():
            setattr(self.rule, name, value)
        self.set_rule(self.rule)  # rebuild the form with the new values
        self.changed.emit()

    def show_regex_guide(self) -> None:
        from alexed_bru.ui.regex_help import RegexGuide
        RegexGuide(self.window()).exec()

    def _make_widget(self, rule: Rule, name: str, meta: dict) -> QWidget:
        kind = meta["kind"]
        value = getattr(rule, name)

        def commit(v, n=name):
            setattr(rule, n, v)
            self._refresh_error()
            self.changed.emit()

        if kind == BOOL:
            w = QCheckBox(meta["label"])
            w.setChecked(bool(value))
            w.toggled.connect(commit)
            return w
        if kind == INT:
            w = QSpinBox()
            w.setRange(meta.get("min") if meta.get("min") is not None else -999999,
                       meta.get("max") if meta.get("max") is not None else 999999)
            w.setValue(int(value))
            w.valueChanged.connect(commit)
            return w
        if kind == CHOICE:
            w = WideListComboBox()
            for key, label in meta["choices"]:
                w.addItem(label, key)
            # Don't demand the width of the longest option; the open list
            # still shows every option in full.
            w.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            w.setMinimumContentsLength(10)
            w.setCurrentIndex(max(0, w.findData(value)))
            w.setToolTip(w.currentText())
            w.currentIndexChanged.connect(lambda _i, cb=w: (cb.setToolTip(cb.currentText()),
                                                            commit(cb.currentData())))
            return w

        edit = QLineEdit(str(value))
        edit.setClearButtonEnabled(True)
        if kind == REGEX:
            edit.setObjectName("Mono")
            edit.setPlaceholderText(r"e.g. ^(\d+)\s*-\s*(.+)$")
        edit.textChanged.connect(commit)
        if kind != TEMPLATE:
            if kind == REGEX:
                self._regex_edit = edit
            return edit

        edit.setPlaceholderText("Text and <tags>")
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        btn = QToolButton()
        btn.setText("‹›")
        btn.setToolTip("Insert a tag: file info, audio tags, document properties, EXIF…")
        btn.setPopupMode(QToolButton.InstantPopup)
        btn.setMenu(tags_menu(btn, lambda tag, e=edit: (e.insert(tag), e.setFocus())))
        lay.addWidget(edit, 1)
        lay.addWidget(btn)
        return box

    def _refresh_error(self) -> None:
        if self.rule is None:
            return
        err = self.rule.config_error()
        self.error_label.setText(err or "")
        self.error_label.setVisible(bool(err))
        regex_edit = getattr(self, "_regex_edit", None)
        if regex_edit is not None:
            try:
                regex_edit.setProperty("invalid", bool(err))
                regex_edit.style().unpolish(regex_edit)
                regex_edit.style().polish(regex_edit)
            except RuntimeError:  # widget already deleted
                self._regex_edit = None


class WideListComboBox(QComboBox):
    """A compact combo box whose open list is wide enough for every option."""

    def showPopup(self) -> None:
        view = self.view()
        longest = max((self.fontMetrics().horizontalAdvance(self.itemText(i)) for i in range(self.count())),
                      default=0)
        view.setMinimumWidth(longest + 40)  # item padding + scroll bar
        super().showPopup()


def _drop_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            _dispose(item.widget())
        elif item.layout():
            _drop_layout(item.layout())


def _dispose(widget: QWidget) -> None:
    """Hide and detach now; deleteLater alone leaves it painted until the next loop."""
    widget.hide()
    widget.setParent(None)
    widget.deleteLater()

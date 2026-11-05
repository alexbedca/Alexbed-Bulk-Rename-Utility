"""Rule stack list and the auto-generated parameter editor."""
from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QSpinBox,
                               QToolButton, QVBoxLayout, QWidget)

from alexed_bru.core.tags import TAG_CATALOGUE
from alexed_bru.skills.base import BOOL, CHOICE, INT, REGEX, RULE_REGISTRY, TEMPLATE, Rule
from alexed_bru.ui.theme import C


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
            act = menu.addAction(cls.LABEL)
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
            act = QAction(f"{tag}    {desc}", sub)
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
        summary = QLabel(error or rule.summary())
        summary.setStyleSheet(f"font-size:8.5pt; color:{C.ERROR if error else C.DIM};")
        summary.setMaximumWidth(260)
        summary.setToolTip(error or rule.summary())
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

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(9)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.error_label = QLabel()
        self.error_label.setObjectName("ErrorText")
        self.error_label.setWordWrap(True)
        for f in rule.params():
            meta = f.metadata
            widget = self._make_widget(rule, f.name, meta)
            if meta["kind"] == BOOL:
                form.addRow("", widget)
            else:
                label = QLabel(meta["label"])
                label.setObjectName("Dim")
                form.addRow(label, widget)
            if meta.get("help"):
                helper = QLabel(meta["help"])
                helper.setObjectName("Faint")
                helper.setStyleSheet("font-size:8.5pt;")
                form.addRow("", helper)
        self._lay.addLayout(form)
        self._lay.addWidget(self.error_label)
        self._lay.addStretch(1)
        self._refresh_error()

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
            w = QComboBox()
            for key, label in meta["choices"]:
                w.addItem(label, key)
            w.setCurrentIndex(max(0, w.findData(value)))
            w.currentIndexChanged.connect(lambda _i, cb=w: commit(cb.currentData()))
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

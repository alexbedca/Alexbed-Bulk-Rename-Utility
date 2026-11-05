"""Rule skill contract.

A rule is a dataclass. Its public fields are its parameters; each field
carries UI metadata (label, widget kind, choices) through :func:`param`, so
the editor form and the JSON preset format are both derived automatically.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, ClassVar

from alexed_bru.core.models import join_name, split_name

if TYPE_CHECKING:
    from alexed_bru.core.pipeline import RuleContext

# Widget kinds understood by ui.rule_editor
TEXT, TEMPLATE, REGEX, INT, BOOL, CHOICE = "text", "template", "regex", "int", "bool", "choice"

TARGET_CHOICES = [("name", "Name only"), ("ext", "Extension only"), ("full", "Name + extension")]


def param(default: Any, label: str, kind: str = TEXT, *, choices: list[tuple[str, str]] | None = None,
          help: str = "", minimum: int | None = None, maximum: int | None = None):
    meta = {"label": label, "kind": kind, "choices": choices, "help": help,
            "min": minimum, "max": maximum}
    return field(default=default, metadata=meta)


RULE_REGISTRY: dict[str, type["Rule"]] = {}


def register_rule(cls: type["Rule"]) -> type["Rule"]:
    if cls.TYPE in RULE_REGISTRY:
        raise ValueError(f"Duplicate rule type {cls.TYPE!r}")
    RULE_REGISTRY[cls.TYPE] = cls
    return cls


@dataclass
class Rule:
    TYPE: ClassVar[str] = ""
    LABEL: ClassVar[str] = ""
    CATEGORY: ClassVar[str] = "General"
    DESCRIPTION: ClassVar[str] = ""

    enabled: bool = field(default=True, metadata={"hidden": True})

    # ---- contract -------------------------------------------------------
    def apply(self, stem: str, ext: str, ctx: "RuleContext") -> tuple[str, str]:
        raise NotImplementedError

    def summary(self) -> str:
        """One-line description shown in the rule stack."""
        return self.LABEL

    def config_error(self) -> str | None:
        """Return a message if the rule's parameters are unusable."""
        return None

    def template_fields(self) -> list[str]:
        """Parameter values that may contain <tags> (used to detect metadata needs)."""
        return [getattr(self, f.name) for f in dataclasses.fields(self)
                if f.metadata.get("kind") == TEMPLATE]

    # ---- serialisation --------------------------------------------------
    @classmethod
    def params(cls) -> list[dataclasses.Field]:
        return [f for f in dataclasses.fields(cls) if not f.metadata.get("hidden")]

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.TYPE, "enabled": self.enabled,
                "params": {f.name: getattr(self, f.name) for f in self.params()}}

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Rule":
        cls = RULE_REGISTRY.get(data.get("type", ""))
        if cls is None:
            raise ValueError(f"Unknown rule type: {data.get('type')!r}")
        known = {f.name: f for f in cls.params()}
        kwargs = {}
        for key, value in (data.get("params") or {}).items():
            if key in known:
                default = known[key].default
                # Coerce to the declared type so hand-edited presets stay safe.
                kwargs[key] = type(default)(value) if default is not None else value
        rule = cls(**kwargs)
        rule.enabled = bool(data.get("enabled", True))
        return rule

    def clone(self) -> "Rule":
        return dataclasses.replace(self)


@dataclass
class TargetedRule(Rule):
    """A rule that transforms one text: the stem, the extension, or the full name."""

    target: str = param("name", "Apply to", CHOICE, choices=TARGET_CHOICES)

    def transform(self, text: str, ctx: "RuleContext") -> str:
        raise NotImplementedError

    def apply(self, stem: str, ext: str, ctx: "RuleContext") -> tuple[str, str]:
        if self.target == "ext":
            return stem, self.transform(ext, ctx)
        if self.target == "full":
            return split_name(self.transform(join_name(stem, ext), ctx))
        return self.transform(stem, ctx), ext


Transform = Callable[[str], str]

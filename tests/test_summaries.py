"""Rule cards describe what each rule does in plain English."""
import pytest

from alexed_bru.skills.base import RULE_REGISTRY
from alexed_bru.skills.rules import (CaseRule, CounterRule, ExtensionRule, InsertRule, PadNumbersRule,
                                     PrefixSuffixRule, RegexRule, RemoveRule, ReplaceRule, TemplateRule,
                                     TrimRule)

CASES = [
    (ReplaceRule(), "Type the text to find"),
    (ReplaceRule(find="_", replace=" "), "Replaces “_” with a space"),
    (ReplaceRule(find="Copy"), "Removes “Copy”"),
    (ReplaceRule(find="a", replace="b", occurrence="first"), "Replaces “a” with “b” (first one only)"),
    (ReplaceRule(find=".", replace="_", target="full"), "Replaces “.” with “_” (in the whole name)"),
    (RegexRule(), "Type a pattern, or pick an Example"),
    (RegexRule(**RegexRule.EXAMPLES[3][2]), "Removes text in ( ) or [ ]"),
    (RegexRule(**RegexRule.EXAMPLES[1][2]), "Puts 'Track' before the number"),
    (RegexRule(**RegexRule.EXAMPLES[7][2]), "Changes date DD-MM-YYYY to YYYY-MM-DD"),
    (RegexRule(pattern=r"^(.+?) - (.+?)$", replacement=r"\2 - \1"),
     r"Replaces text matching ^(.+?) - (.+?)$ with “\2 - \1”"),
    (RegexRule(pattern=r"\d+"), r"Removes text matching \d+"),
    (CaseRule(mode="upper"), "Makes everything UPPERCASE"),
    (CaseRule(mode="title", target="ext"), "Capitalises Each Word (in the extension)"),
    (InsertRule(), "Type the text to insert"),
    (InsertRule(text="x"), "Inserts “x” at the start"),
    (InsertRule(text="x", from_end=True), "Inserts “x” at the end"),
    (InsertRule(text="x", position=3), "Inserts “x” after character 3"),
    (PrefixSuffixRule(), "Type a prefix or a suffix"),
    (PrefixSuffixRule(prefix="2026 - "), "Adds “2026 - ” to the start"),
    (PrefixSuffixRule(suffix=" (live)"), "Adds “ (live)” to the end"),
    (PrefixSuffixRule(prefix="A", suffix="B"), "Adds “A” to the start and “B” to the end"),
    (RemoveRule(count=3), "Removes 3 characters from the start"),
    (RemoveRule(count=1, from_end=True), "Removes 1 character from the end"),
    (RemoveRule(mode="brackets"), "Removes text inside ( ), [ ] and { }"),
    (RemoveRule(mode="chars"), "Type the characters to remove"),
    (RemoveRule(mode="chars", characters="#!#"), "Removes every “#” “!”"),
    (TrimRule(), "Squashes double spaces, trims spaces at the ends"),
    (TrimRule(strip_whitespace=False, collapse_spaces=False, separators_to_spaces=True),
     "Turns _ and . into spaces"),
    (TrimRule(strip_whitespace=False, collapse_spaces=False), "Tick an option to clean names"),
    (PadNumbersRule(), "Pads numbers to 2 digits (7 → 07)"),
    (PadNumbersRule(width=3, which="first"), "Pads the first number to 3 digits (7 → 007)"),
    (CounterRule(), "Numbers files 01, 02, 03… at the start"),
    (CounterRule(placement="suffix", start=10, step=10, padding=3), "Numbers files 010, 020, 030… at the end"),
    (CounterRule(placement="renumber_first", reset_per_folder=True),
     "Renumbers the first number in each name: 01, 02, 03…, restarting in each folder"),
    (TemplateRule(), "Builds names as <artist> - <title>"),
    (TemplateRule(template=""), "Type a template, e.g. <artist> - <title>"),
    (ExtensionRule(), "Makes extensions lowercase"),
    (ExtensionRule(mode="set", value=".JPG"), "Changes the extension to .JPG"),
    (ExtensionRule(mode="set"), "Type the new extension"),
    (ExtensionRule(mode="remove"), "Removes the extension"),
]


@pytest.mark.parametrize("rule,expected", CASES, ids=[f"{type(r).__name__}-{i}" for i, (r, _) in enumerate(CASES)])
def test_summary(rule, expected):
    assert rule.summary() == expected


def test_every_example_and_every_choice_has_a_summary():
    for title, _sample, params in RegexRule.EXAMPLES:
        text = RegexRule(**params).summary()
        assert text and "matching" not in text, title   # recipes read as words, not patterns
    for cls in RULE_REGISTRY.values():
        for f in cls.params():
            for key, _label in f.metadata.get("choices") or []:
                text = cls(**{f.name: key}).summary()
                assert text and text[0].isupper(), (cls.__name__, f.name, key)

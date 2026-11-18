"""RegEx from an example: the inferred pattern does what the user showed, and no more."""
import re

import pytest

from alexed_bru.core.models import split_name
from alexed_bru.skills.regex_infer import count_matches, infer
from alexed_bru.skills.rules import RegexRule


def run(r, name: str) -> str:
    """Apply an inference the way RegexRule does (to the name without extension)."""
    stem, _ = split_name(name)
    rule = RegexRule(pattern=r.pattern, replacement=r.replacement)
    return rule.transform(stem, None)


# sample, desired, other names that must follow the same pattern, expected pattern/replacement
CASES = [
    ("Adele - Hello.mp3", "Hello - Adele",
     {"Ed Sheeran - Shape of You.mp3": "Shape of You - Ed Sheeran"},
     r"^(.+?) - (.+?)$", r"\2 - \1"),
    ("IMG_20230601_142209.jpg", "2023-06-01 14.22.09",
     {"VID_20241231_235959.mp4": "2024-12-31 23.59.59", "PXL_20220101_000102.jpg": "2022-01-01 00.01.02"},
     r"^.+?_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$", r"\1-\2-\3 \4.\5.\6"),
    ("01 - Hello.mp3", "Hello",
     {"12 - Rolling in the Deep.mp3": "Rolling in the Deep"},
     r"^\d+ - (.+?)$", r"\1"),
    ("01 Hello World.mp3", "Hello World",
     {"7 Someone Like You.mp3": "Someone Like You"},
     r"^\d+ (.+?)$", r"\1"),
    ("Song (Live) [2019].mp3", "Song",
     {"Other Song (Acoustic) [2021].mp3": "Other Song"},
     r"^(.+?) \(.+?\) \[\d+\]$", r"\1"),
    ("Hello.mp3", "2026 - Hello",
     {"Anything.mp3": "2026 - Anything"},
     r"^(.+?)$", r"2026 - \1"),
    ("Invoice 31-12-2024.pdf", "Invoice 2024-12-31",
     {"Receipt 01-02-2023.pdf": "Receipt 2023-02-01"},
     r"^(.+?) (\d+)-(\d+)-(\d+)$", r"\1 \4-\3-\2"),
    ("01 - Adele - Hello.mp3", "Hello (Adele) 01",
     {"02 - Ed Sheeran - Perfect.mp3": "Perfect (Ed Sheeran) 02"},
     r"^(\d+) - (.+?) - (.+?)$", r"\3 (\2) \1"),
    ("My Holiday Photo.jpg", "My_Holiday_Photo",
     {"Big Red Bus.jpg": "Big_Red_Bus"},
     r"^(.+?) (.+?) (.+?)$", r"\1_\2_\3"),
]


@pytest.mark.parametrize("sample,desired,others,pattern,replacement", CASES,
                         ids=[c[0] for c in CASES])
def test_common_patterns(sample, desired, others, pattern, replacement):
    r = infer(sample, desired)
    assert r.ok and r.general, r.message
    assert (r.pattern, r.replacement) == (pattern, replacement)
    assert run(r, sample) == desired
    for name, expected in others.items():
        assert run(r, name) == expected


def test_names_with_another_shape_are_left_alone():
    r = infer("Song (Live) [2019].mp3", "Song")
    assert run(r, "Song without brackets.mp3") == "Song without brackets"
    r = infer("01 - Hello.mp3", "Hello")
    assert run(r, "Hello.mp3") == "Hello"


def test_unrelated_example_falls_back_to_that_exact_name():
    r = infer("random.txt", "invoice.txt")
    assert r.ok and not r.general
    assert r.pattern == "^random$" and r.replacement == "invoice"
    assert "only renames files named exactly" in r.message
    assert run(r, "random.txt") == "invoice"
    assert run(r, "random notes.txt") == "random notes"   # not a broad pattern
    assert run(r, "other.txt") == "other"


def test_fallback_escapes_special_characters():
    r = infer("a+b (1).txt", "zzz")
    assert not r.general
    assert run(r, "a+b (1).txt") == "zzz"
    assert run(r, "aab (1).txt") == "aab (1)"


def test_case_only_change_points_to_case_rule():
    r = infer("adele - hello.mp3", "Adele - Hello")
    assert not r.ok and "Change case" in r.message


def test_extension_is_ignored_or_refused():
    assert infer("Adele - Hello.mp3", "Hello - Adele.mp3").replacement == r"\2 - \1"
    r = infer("Report.docx", "Report.pdf")
    assert not r.ok and "Extension rule" in r.message
    assert infer("Hello.mp3", "Hello.mp3").ok is False          # nothing changes
    assert infer("Hello.mp3", "   ").ok is False                # nothing typed


def test_group_followed_by_digit_uses_safe_reference():
    r = infer("Track 7 x.mp3", "x7")
    assert run(r, "Track 7 x.mp3") == "x7"
    r = infer("A_5.txt", "5 1 A")
    assert run(r, "A_5.txt") == "5 1 A"
    r = infer("A_5.txt", "A1")         # literal digit after a group: \g<1> keeps "\11" from happening
    assert run(r, "A_5.txt") == "A1"


def test_digits_are_taken_once_each():
    r = infer("20230601.jpg", "01-06-2023")
    assert r.general and run(r, "20240215.jpg") == "15-02-2024"


def test_every_result_reproduces_the_sample():
    samples = [("x - y - z.txt", "z y x"), ("CD1 Track 03.mp3", "03"), ("a.b.c.txt", "c.b.a"),
               ("Report - Copy (2).docx", "Report"), ("DSC_0042.jpg", "Photo 0042")]
    for sample, desired in samples:
        r = infer(sample, desired)
        assert r.ok and r.general, (sample, r.message)
        stem = split_name(sample)[0]
        assert re.sub(r.pattern, lambda m: m.expand(r.replacement), stem, flags=re.I) == desired


@pytest.mark.parametrize("title,sample,_params", RegexRule.EXAMPLES, ids=[e[0] for e in RegexRule.EXAMPLES])
def test_examples_menu_samples_can_be_regenerated(title, sample, _params):
    before, after = sample.split("  →  ")
    r = infer(before, after)
    assert r.ok
    assert run(r, before) == after


def test_count_matches():
    r = infer("Adele - Hello.mp3", "Hello - Adele")
    names = ["Adele - Hello.mp3", "Ed Sheeran - Perfect.flac", "notes.txt", "no dash.mp3"]
    assert count_matches(r.pattern, names) == 2
    assert count_matches("(", names) == 0

from pathlib import Path

import pytest

from alexed_bru.core.models import FileItem, split_name
from alexed_bru.core.pipeline import RuleContext, run_pipeline
from alexed_bru.skills.base import Rule
from alexed_bru.skills.metadata import MetadataStore
from alexed_bru.skills.rules import (CaseRule, CounterRule, ExtensionRule, InsertRule,
                                     PadNumbersRule, RegexRule, RemoveRule, ReplaceRule,
                                     TemplateRule, TrimRule)


def run(name: str, *rules: Rule, folder: str = "C:/music") -> str:
    items = [FileItem(Path(folder) / name)]
    return run_pipeline(items, rules, MetadataStore())[0].new_name


def test_split_name_edge_cases():
    assert split_name("a.tar.gz") == ("a.tar", "gz")
    assert split_name(".gitignore") == (".gitignore", "")
    assert split_name("README") == ("README", "")


def test_replace_occurrences_and_case():
    assert run("a-b-a.txt", ReplaceRule(find="A", replace="x")) == "x-b-x.txt"
    assert run("a-b-a.txt", ReplaceRule(find="A", replace="x", case_sensitive=True)) == "a-b-a.txt"
    assert run("a-b-a.txt", ReplaceRule(find="a", replace="x", occurrence="last")) == "a-b-x.txt"


def test_regex_capture_groups_all_syntaxes():
    assert run("01 song.mp3", RegexRule(pattern=r"^(\d+)\s*", replacement=r"Track \1 - ")) \
        == "Track 01 - song.mp3"
    assert run("01 song.mp3", RegexRule(pattern=r"^(?P<n>\d+) (.*)", replacement=r"\2 [\g<n>]")) \
        == "song [01].mp3"
    assert run("01 song.mp3", RegexRule(pattern=r"^(\d+) (.*)", replacement="$2 ($1)")) \
        == "song (01).mp3"


def test_regex_invalid_pattern_is_skipped_not_crashing():
    rule = RegexRule(pattern="(unclosed")
    assert rule.config_error()
    assert run("x.txt", rule) == "x.txt"


@pytest.mark.parametrize("mode,expected", [
    ("title", "The Lord Of The Rings - Don't Stop"),
    ("smart_title", "The Lord of the Rings - Don't Stop"),
    ("upper", "THE LORD OF THE RINGS - DON'T STOP"),
    ("sentence", "The lord of the rings - don't stop"),
])
def test_case_modes(mode, expected):
    assert run("the lord OF the rings - don't stop.mkv", CaseRule(mode=mode)) == expected + ".mkv"


def test_smart_title_keeps_acronyms():
    assert run("live in the USA.mp3", CaseRule(mode="smart_title")) == "Live in the USA.mp3"


def test_insert_and_remove():
    assert run("song.mp3", InsertRule(text="X", position=2)) == "soXng.mp3"
    assert run("song.mp3", InsertRule(text="!", position=0, from_end=True)) == "song!.mp3"
    assert run("abcdef.txt", RemoveRule(mode="range", start=1, count=2)) == "adef.txt"
    assert run("abcdef.txt", RemoveRule(mode="range", start=0, count=2, from_end=True)) == "abcd.txt"
    assert run("Song (Official Video) [HD].mp4", RemoveRule(mode="brackets")) == "Song.mp4"
    assert run("Café Beyoncé.mp3", RemoveRule(mode="accents")) == "Cafe Beyonce.mp3"


def test_trim_and_pad():
    assert run("  my__file..name  .txt", TrimRule(separators_to_spaces=True)) == "my file name.txt"
    assert run("Track 7 of 12.mp3", PadNumbersRule(width=3)) == "Track 007 of 012.mp3"
    assert run("Track 007.mp3", PadNumbersRule(width=2)) == "Track 07.mp3"


def test_counter_with_folder_reset():
    items = [FileItem(Path(p)) for p in ("A/x.txt", "A/y.txt", "B/z.txt")]
    rule = CounterRule(start=1, step=5, padding=3, placement="prefix", separator="_",
                       reset_per_folder=True)
    names = [p.new_name for p in run_pipeline(items, [rule], MetadataStore())]
    assert names == ["001_x.txt", "006_y.txt", "001_z.txt"]
    rule.reset_per_folder = False
    names = [p.new_name for p in run_pipeline(items, [rule], MetadataStore())]
    assert names == ["001_x.txt", "006_y.txt", "011_z.txt"]


def test_excluded_items_do_not_consume_counter():
    items = [FileItem(Path("a.txt")), FileItem(Path("b.txt"), include=False), FileItem(Path("c.txt"))]
    names = [p.new_name for p in run_pipeline(items, [CounterRule(padding=1, separator=".")],
                                              MetadataStore())]
    assert names == ["1.a.txt", "b.txt", "2.c.txt"]


def test_extension_rule():
    assert run("a.JPEG", ExtensionRule(mode="lower")) == "a.jpeg"
    assert run("a.jpeg", ExtensionRule(mode="set", value=".jpg")) == "a.jpg"
    assert run("a.tar", ExtensionRule(mode="append", value="gz")) == "a.tar.gz"


def test_rule_order_matters_and_disabled_rules_skip():
    upper, add = CaseRule(mode="upper"), InsertRule(text="x", position=0)
    assert run("a.txt", upper, add) == "xA.txt"
    assert run("a.txt", add, upper) == "XA.txt"
    upper.enabled = False
    assert run("a.txt", upper, add) == "xa.txt"


def test_builtin_tags_in_template():
    assert run("song.mp3", TemplateRule(template="<folder> - <name> #<num:3>")) \
        == "music - song #001.mp3"


def test_serialisation_round_trip():
    rules = [RegexRule(pattern=r"(\d+)", replacement=r"T\1", count=2), CounterRule(start=5)]
    clones = [Rule.from_dict(r.to_dict()) for r in rules]
    assert clones == rules


def test_context_warn_dedupes():
    ctx = RuleContext(FileItem(Path("a")), 0, 0, 1, MetadataStore())
    ctx.warn("x")
    ctx.warn("x")
    assert ctx.warnings == ["x"]

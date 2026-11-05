"""Metadata providers (document, image, system) and presets."""
import json
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from alexed_bru.core import presets
from alexed_bru.core.engine import RenameEngine
from alexed_bru.core.models import Status
from alexed_bru.skills.base import Rule
from alexed_bru.skills.metadata import MetadataStore
from alexed_bru.skills.rules import CounterRule, RegexRule, TemplateRule

CORE_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
 <dc:title>Quarterly Report</dc:title><dc:creator>Jane Doe</dc:creator>
 <dcterms:created xsi:type="dcterms:W3CDTF">2023-04-05T10:20:30Z</dcterms:created>
</cp:coreProperties>"""


def make_docx(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("docProps/core.xml", CORE_XML)
    return path


def make_pdf(path: Path) -> Path:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    writer.add_metadata({"/Title": "Annual Summary", "/Author": "John Smith",
                         "/CreationDate": "D:20210102030405+00'00'"})
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def make_jpeg(path: Path) -> Path:
    from PIL import Image

    img = Image.new("RGB", (64, 48), "red")
    exif = Image.Exif()
    exif[0x010F] = "Canon"
    exif[0x0110] = "EOS R5"
    exif.get_ifd(0x8769)[0x9003] = "2022:07:14 18:30:05"
    img.save(path, exif=exif)
    return path


def test_office_core_properties(tmp_path):
    p = make_docx(tmp_path / "report.docx")
    data = MetadataStore().get(p, "doc")
    assert data["title"] == "Quarterly Report"
    assert data["author"] == "Jane Doe"
    assert data["created"] == datetime(2023, 4, 5, 10, 20, 30)
    (row,) = RenameEngine([TemplateRule(template="<date:%Y-%m-%d> <title> (<author>)")]).preview([p])
    assert row.proposed == "2023-04-05 Quarterly Report (Jane Doe).docx"


def test_pdf_info(tmp_path):
    p = make_pdf(tmp_path / "scan.pdf")
    data = MetadataStore().get(p, "doc")
    assert data["title"] == "Annual Summary" and data["pages"] == 2
    assert data["created"] == datetime(2021, 1, 2, 3, 4, 5)
    (row,) = RenameEngine([TemplateRule(template="<doc:author> - <title> [<doc:pages>p]")]).preview([p])
    assert row.proposed == "John Smith - Annual Summary [2p].pdf"


def test_exif(tmp_path):
    p = make_jpeg(tmp_path / "IMG_0001.JPG")
    data = MetadataStore().get(p, "exif")
    assert data["make"] == "Canon" and data["model"] == "EOS R5"
    assert data["width"] == 64 and data["date"] == datetime(2022, 7, 14, 18, 30, 5)
    (row,) = RenameEngine([TemplateRule(template="<date:%Y%m%d_%H%M%S> <exif:model>")]).preview([p])
    assert row.proposed == "20220714_183005 EOS R5.JPG"


def test_corrupt_files_do_not_crash(tmp_path):
    bad = [tmp_path / n for n in ("broken.pdf", "broken.docx", "broken.jpg", "broken.mp3")]
    for p in bad:
        p.write_bytes(b"not really a file")
    rows = RenameEngine([TemplateRule(template="<title>")]).preview(bad)
    assert all(r.status == Status.UNCHANGED and r.proposed == r.original for r in rows)


def test_system_tags(tmp_path):
    p = tmp_path / "folder" / "a.txt"
    p.parent.mkdir()
    p.write_text("x" * 2048)
    data = MetadataStore().get(p, "sys")
    assert data["size"] == 2048 and data["size_kb"] == "2.0" and data["parent"] == "folder"


def test_unknown_namespace_is_flagged_not_silent(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x")
    (row,) = RenameEngine([TemplateRule(template="<nope:thing>")]).preview([p])
    assert row.status == Status.ERROR  # '<' and '>' are invalid in names


def test_preset_file_round_trip(tmp_path):
    rules = [RegexRule(pattern=r"(\d+)", replacement="T$1"), CounterRule(start=3, padding=4)]
    rules[1].enabled = False
    path = tmp_path / "p.json"
    presets.save(path, rules)
    loaded = presets.load(path)
    assert loaded == rules and loaded[1].enabled is False


def test_preset_rejects_foreign_json(tmp_path):
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"hello": 1}))
    with pytest.raises(ValueError):
        presets.load(path)


def test_preset_ignores_unknown_params_and_coerces_types():
    rule = Rule.from_dict({"type": "counter", "params": {"start": "7", "bogus": 1}})
    assert rule.start == 7


@pytest.mark.parametrize("name", list(presets.samples()))
def test_starter_presets_are_valid(name):
    rules = presets.samples()[name]
    assert rules and all(r.config_error() is None for r in rules)
    assert presets.load_dict(presets.dump(rules)) == rules

# Alexed Bulk Rename Utility

![logo](assets/branding/logo-horizontal.svg)

A portable, transactional bulk file renamer for big music libraries and deeply nested document archives.
It's a single `.exe` with no installer and no registry footprint.

## Run

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python run.py            # or: python -m alexed_bru
```

To build the portable executable (runs the tests first), run `build.ps1`. The output is `dist\AlexedBulkRename.exe`:

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

History, presets and settings are stored in `AlexedBRU_data\` next to the exe. Copy both together to take your setup to another PC.
Set `ALEXED_BRU_DATA` to store them somewhere else.

## Using it

1. Drop files or folders onto the window (subfolders are included if that box is ticked).
2. Add rules on the left. They run top to bottom. Drag to reorder, untick to bypass.
3. The preview updates as you type. Blue = will rename, amber = warning, red = error (skipped).
   Regex matches are highlighted in the *Original* column, and the changed parts in *New name*.
4. Click **Rename N files**. You can undo any batch later from **History**, even after restarting the app.

| Shortcut | Action |
|---|---|
| Ctrl+O / Ctrl+Shift+O | Add files / folder |
| Ctrl+Enter | Apply renames |
| Ctrl+Z / Ctrl+Y | Undo / redo rule edits |
| Ctrl+H | Rename history (undo applied batches) |
| Ctrl+S | Save preset |
| Ctrl+F | Filter the preview |
| Delete | Remove selected files / rule |

## Rules

| Rule | What it does |
|---|---|
| Find & Replace | Replace all / first / last occurrence. Leave the replacement empty to delete the text |
| RegEx Replace | Python regex with live group highlighting; `\1`, `\g<name>`, `$1` |
| Add Prefix / Suffix | Text or tags before/after the name; won't add the same text twice |
| Change Case | Title, Smart Title, UPPER, lower, Sentence, Swap |
| Insert Text | At any position from the start or end |
| Remove | Character range, specific characters, digits, symbols, `(…)`/`[…]` text, accents |
| Trim & Clean | Whitespace, `_`/`.` to spaces, cut N characters |
| Pad Numbers | `Track 7` → `Track 07` |
| Counter / Numbering | Prefix, suffix, replace name, insert, **renumber existing numbers**; start, step, padding, restart per folder |
| New Name from Template | Build the whole name from tags |
| Extension | lower / UPPER / replace / append / remove |

Every rule can target the name, the extension, or both, and works on any file type.

## Supported metadata

| Kind | Formats | Examples |
|---|---|---|
| Audio | MP3 (ID3v1/v2), FLAC, OGG/Opus, M4A/AAC, WMA, WAV, AIFF, APE, WavPack, DSF | artist, album, title, track, disc, year, genre, bitrate, duration |
| Video | MP4, M4V, MOV, 3GP (iTunes tags, QuickTime atoms, iPhone `mdta` keys) | title, show, season, episode, date recorded, make/model, resolution, quality (1080p) |
| Documents | PDF, DOCX/XLSX/PPTX (+ macro variants) | title, author, subject, created, modified, pages |
| Images | JPEG, TIFF, PNG, WebP, HEIC*, DNG* (EXIF) | date taken, camera make/model, width/height, ISO |
| Any file | system | created, modified, size, parent/grandparent folder |

\* if Pillow can open it. MKV/AVI/WebM tags aren't read yet; system tags still work for them.

## Tags

You can use tags in any field that has a ‹› button: Template, Replace with, Insert.

| Tag | Meaning |
|---|---|
| `<name>` `<ext>` `<folder>` | Original name, extension, parent folder |
| `<num:3>` `<fnum:2>` | Position in batch / in folder, zero-padded |
| `<artist>` `<album>` `<title>` `<track:2>` `<year>` `<genre>` | **Smart tags.** Audio tags first, then document/EXIF data, then file dates |
| `<show>` `<season:2>` `<episode:2>` `<quality>` `<resolution>` `<duration>` | Video tags |
| `<date:%Y-%m-%d>` `<created:…>` `<modified:…>` | Dates with any strftime format |
| `<audio:key>` `<doc:key>` `<exif:key>` `<sys:key>` | Explicit namespace. See the *File metadata* panel for every key |

Tag values are cleaned up automatically: `AC/DC` becomes `AC-DC`, never a path separator.
Regex replacements accept `\1`, `\g<name>` and `$1`.

## Using the engine without the UI

```python
from alexed_bru.core.engine import RenameEngine
from alexed_bru.skills.rules import RegexRule, TemplateRule

engine = RenameEngine([RegexRule(pattern=r"^(\d+)\s*", replacement=r"Track \1 - ")])
for row in engine.preview(paths):
    print(row.original, "→", row.proposed, row.status.label, row.message)
engine.apply(paths)   # two-phase, rolls back on any failure
```

## Project docs

- [docs/RESEARCH.md](docs/RESEARCH.md): competitive analysis, the UX flaws we fix, feature checklist
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): stack, layout, data flow, safety model, how to add skills

Tests: `.venv\Scripts\python -m pytest`

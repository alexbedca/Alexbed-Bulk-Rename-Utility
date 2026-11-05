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

## Tags

You can use tags in any field that has a ‹› button: Template, Replace with, Insert.

| Tag | Meaning |
|---|---|
| `<name>` `<ext>` `<folder>` | Original name, extension, parent folder |
| `<num:3>` `<fnum:2>` | Position in batch / in folder, zero-padded |
| `<artist>` `<album>` `<title>` `<track:2>` `<year>` `<genre>` | **Smart tags.** Audio tags first, then document/EXIF data, then file dates |
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

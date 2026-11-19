# Alexbed Bulk Rename Utility: project notes for Claude

## What this project is
A free, portable Windows 10/11 bulk file renamer (single `.exe`, no installer, no registry): drop files/folders,
stack rules (Find & Replace, RegEx, prefix/suffix, case, counters/renumbering, templates from tags), see a live
preview, then rename as one transaction that rolls back on any failure. Any batch can be undone later from History.
Reads audio (mutagen), video (MP4/MOV atoms), EXIF (Pillow) and PDF/Office metadata for tag-based names.

- **Name:** the brand is **Alexbed** (Alexbed Bulk Rename Utility). 1.0.0 and 1.1.0 shipped as the misspelt "Alexed";
  1.1.1 renamed everything users see. Still "alexed" on purpose: the Python package `alexed_bru`, the preset format id
  `alexed-bru-preset`, this local folder name, and compatibility code for the old data folder `AlexedBRU_data`,
  env var `ALEXED_BRU_DATA` and Send To shortcut "Alexed Bulk Rename.lnk" (`paths.py`, `core/sendto.py`).
- **Status:** v1.4.0 released 2026-11-19 (1.4.0: MKV/WebM/AVI tags, Send To race fix, flatten undo restores empty folders; 1.3.1: drag selection + import-only-edited polish; 1.3.0: list export/import, sort before numbering, Quick Recipes, one window, Clear history; 1.2.0 Flatten, 1.1.x earlier that day, 1.0.0 on 2026-11-06). Public repo
  https://github.com/alexbedca/Alexbed-Bulk-Rename-Utility (GPL-3.0-or-later). Release assets: `AlexbedBulkRename.exe`,
  `AlexbedBulkRename.exe.sha256`, `LICENSE`, `THIRD-PARTY-NOTICES.txt`.
  1.1.0 added: Find duplicates, RegEx from example, plain-English rule cards, hand-edited names, auto-number
  duplicate names, Send To shortcut.
- **Screenshots and social card:** regenerate every release. README screenshots come from the real window over
  `test_library` (script pattern: drive `MainWindow` with `ALEXBED_BRU_DATA=test_library\.appdata`, `widget.grab()`).
  Card: `.venv\Scripts\python tools\make_social_preview.py` → `docs/social-preview.png` (shows the version), then
  upload it in repo Settings → Social preview via Claude in Chrome.
- **No CI** (no `.github/` folder): tests only run locally.
- **Known limits:** folders themselves are not renamed; video tags in other containers (WMV/FLV/TS) aren't read.
- **Roadmap:** `docs/ROADMAP.md` (v1.2.0+ in four phases, with safety notes per item). Update its status marks
  when a feature ships.
- **Read first:** `README.md` (user view), `docs/ARCHITECTURE.md` (layout, data flow, safety model, how to add rules),
  `docs/RESEARCH.md` (competitors, UX flaws fixed), `docs/REGEX_GUIDE.md`.

## Stack and layout
Python 3.11+ (venv in `.venv`), PySide6-Essentials (Qt 6), mutagen, pypdf, Pillow; PyInstaller `--onefile` build.
```
alexed_bru/__init__.py    APP_NAME / APP_VERSION (single place for the version)
alexed_bru/paths.py       portable data dir: AlexbedBRU_data\ next to the exe (override: ALEXBED_BRU_DATA)
alexed_bru/core/          engine, pipeline (pure), validation (+ auto-number), transaction (two-phase + rollback),
                          history (+ managed folders, clear), presets, tags, duplicates (content finder), flatten (folder
                          flatten), sendto (Explorer shortcut), listio (CSV/TXT export/import),
                          sorting (order by tags), recipes (Quick Recipes)
alexed_bru/skills/        rule base + registry (rules.py, plain-English summary() per rule), regex_infer
                          (RegEx from example), metadata providers (system/audio/video/document/image;
                          metadata/containers.py: pure-Python MKV/WebM + AVI tag readers)
alexed_bru/ui/            main_window, preview_model (virtualised table + highlight delegate; New name editable),
                          rule_editor (+ From example panel), duplicates_dialog, flatten_dialog, single_instance (one window
                          via named mutex + QLocalServer), regex_help, workers, theme
tests/                    pytest: engine, rules, metadata, media, containers (MKV/AVI), ui, large (10k, slow)
assets/branding, assets/ui  logo/icon, UI icons
test_library/             sample messy files for manual testing (git-ignored)
build.ps1                 venv + tests + PyInstaller -> dist\AlexbedBulkRename.exe
```

## Tools for this project
**Project commands** (PowerShell, from the project folder)
- Setup: `python -m venv .venv` then `.venv\Scripts\pip install -r requirements-dev.txt`
- Run: `.venv\Scripts\python run.py` (or `python -m alexed_bru`)
- Tests: `.venv\Scripts\python -m pytest` (~14 s; `-m "not slow"` is the default via `pytest.ini`). Keep it under
  15 s: most time is ~40 UI tests at ~0.4 s each for the window fixture; mark anything long `slow`.
  Slow 10,000-file rename/undo runs: `.venv\Scripts\python -m pytest -m slow` (a few minutes; ~4 s each for rename and undo).
- Build: `powershell -ExecutionPolicy Bypass -File build.ps1` → `dist\AlexbedBulkRename.exe` (runs tests first, stops if they fail).
- Lint: `pyflakes` is in requirements-dev.

**Project skills** (in `.claude/skills/`)
- `bru-release`: version bump → tests → build → sha256 → GitHub release → verification.

**Account tools this project uses** (full list in `~/.claude/CLAUDE.md`)
- `git push` via Git Credential Manager; `gh release create/upload` for releases (repo `alexbedca/Alexbed-Bulk-Rename-Utility`).
- Personal skill `alexbed-github-publish` for README/licence/screenshot/social-preview conventions.
- Claude in Chrome for the GitHub social-preview upload (web-only). The card is `docs/social-preview.png`,
  made by `tools/make_social_preview.py`.

## Decisions and gotchas
- **Safety model is the core promise:** the pipeline never touches disk; Apply = two-phase rename via
  `.~abru-<uuid>.tmp` names, full rollback on failure; history journal enables undo. Don't add shortcuts that write
  outside `core/transaction.py`.
- Hand-typed names (`FileItem.manual`) and auto-numbering only change *proposed names* before validation, so
  rename/undo need nothing special. Duplicate finder's "Move to _Duplicates" also goes through `transaction.execute`.
  Its Recycle Bin path is the one place files leave; it's refused on non-fixed drives (they'd be deleted permanently).
- **Privacy:** no log/crash/debug files ever (logging goes to a NullHandler in `ui/app.py`); the data folder
  holds only history.json, settings.json, presets/ (`tests/test_privacy.py` checks both). History has Clear.
- Send To race test: `conftest.py` starts the 3 helper processes (`tests/instance_race_helper.py`) when
  collection ends, so they load Qt while other tests run; the test only releases them. Keeps ~0.6 s off the suite.
- Tests: the `win` fixture deletes each window afterwards and uses a 5 ms preview delay; without that, closed
  windows piled up and the fast suite drifted past 15 s.
- Shell edits: in Git Bash heredocs, `\\n` inside Python strings turned into real line breaks twice. Write patch
  scripts to a file with the Write tool instead.
- New rules: subclass `Rule`, declare params with `param(...)`, decorate `@register_rule`; the UI form and preset
  serialisation are automatic. New metadata: subclass `MetadataProvider` (namespace + extensions).
- Tag values are sanitised (`AC/DC` → `AC-DC`), never a path separator.
- Startup was cut from 15–18 s to 4–6 s on PCs with many fonts (commit c9f7cc5); keep an eye on startup cost when
  adding UI.
- `dist/`, `*.spec`, `AlexbedBRU_data/`, `test_library/` and the release exe are git-ignored.
- `tests/test_stress_and_locks.py` runs the real engine: a file held open by another process must roll back the
  whole batch (small and 100-file parallel/chained batches; Windows only). Its 10k test is marked slow.

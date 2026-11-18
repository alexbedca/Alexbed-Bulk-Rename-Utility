# Alexed Bulk Rename Utility: project notes for Claude

## What this project is
A free, portable Windows 10/11 bulk file renamer (single `.exe`, no installer, no registry): drop files/folders,
stack rules (Find & Replace, RegEx, prefix/suffix, case, counters/renumbering, templates from tags), see a live
preview, then rename as one transaction that rolls back on any failure. Any batch can be undone later from History.
Reads audio (mutagen), video (MP4/MOV atoms), EXIF (Pillow) and PDF/Office metadata for tag-based names.

- **Status:** v1.0.0 released 2026-11-06. Public repo https://github.com/alexbedca/Alexed-Bulk-Rename-Utility
  (GPL-3.0-or-later). Release assets: `AlexedBulkRename.exe` + `AlexedBulkRename.exe.sha256`.
  Later commits on `main` (speed-ups, renumbering fixes, RegEx examples/guide, Find duplicates, RegEx from example) are **not in a release yet**.
- **Planned next (not built):** single-file name edits in the
  preview, plainer rule summaries, optional Windows Send To shortcut.
- **No CI** (no `.github/` folder): tests only run locally.
- **Known limits:** MKV/AVI/WebM tags not read; folders themselves are not renamed.
- **Read first:** `README.md` (user view), `docs/ARCHITECTURE.md` (layout, data flow, safety model, how to add rules),
  `docs/RESEARCH.md` (competitors, UX flaws fixed), `docs/REGEX_GUIDE.md`.

## Stack and layout
Python 3.11+ (venv in `.venv`), PySide6-Essentials (Qt 6), mutagen, pypdf, Pillow; PyInstaller `--onefile` build.
```
alexed_bru/__init__.py    APP_NAME / APP_VERSION (single place for the version)
alexed_bru/paths.py       portable data dir: AlexedBRU_data\ next to the exe (override: ALEXED_BRU_DATA)
alexed_bru/core/          engine, pipeline (pure), validation, transaction (two-phase + rollback), history, presets, tags
alexed_bru/skills/        rule base + registry (rules.py), metadata providers (system/audio/video/document/image)
alexed_bru/ui/            main_window, preview_model (virtualised table + highlight delegate), rule_editor, workers, theme
tests/                    pytest: engine, rules, metadata, media, ui, large (10k files, marked slow)
assets/branding, assets/ui  logo/icon, UI icons
test_library/             sample messy files for manual testing (git-ignored)
build.ps1                 venv + tests + PyInstaller -> dist\AlexedBulkRename.exe
```

## Tools for this project
**Project commands** (PowerShell, from the project folder)
- Setup: `python -m venv .venv` then `.venv\Scripts\pip install -r requirements-dev.txt`
- Run: `.venv\Scripts\python run.py` (or `python -m alexed_bru`)
- Tests: `.venv\Scripts\python -m pytest` (~10 s; `-m "not slow"` is the default via `pytest.ini`).
  Slow 10,000-file rename/undo runs: `.venv\Scripts\python -m pytest -m slow` (a few minutes; ~4 s each for rename and undo).
- Build: `powershell -ExecutionPolicy Bypass -File build.ps1` → `dist\AlexedBulkRename.exe` (runs tests first, stops if they fail).
- Lint: `pyflakes` is in requirements-dev.

**Project skills** (in `.claude/skills/`)
- `bru-release`: version bump → tests → build → sha256 → GitHub release → verification.

**Account tools this project uses** (full list in `~/.claude/CLAUDE.md`)
- `git push` via Git Credential Manager; `gh release create/upload` for releases (repo `alexbedca/Alexed-Bulk-Rename-Utility`).
- Personal skill `alexbed-github-publish` for README/licence/screenshot/social-preview conventions.
- Claude in Chrome for the GitHub social-preview upload (web-only). Card working files are in
  `..\Fast copier\social-cards\` (git-ignored there).

## Decisions and gotchas
- **Safety model is the core promise:** the pipeline never touches disk; Apply = two-phase rename via
  `.~abru-<uuid>.tmp` names, full rollback on failure; history journal enables undo. Don't add shortcuts that write
  outside `core/transaction.py`.
- New rules: subclass `Rule`, declare params with `param(...)`, decorate `@register_rule`; the UI form and preset
  serialisation are automatic. New metadata: subclass `MetadataProvider` (namespace + extensions).
- Tag values are sanitised (`AC/DC` → `AC-DC`), never a path separator.
- Startup was cut from 15–18 s to 4–6 s on PCs with many fonts (commit c9f7cc5); keep an eye on startup cost when
  adding UI.
- `dist/`, `*.spec`, `AlexedBRU_data/`, `test_library/` and the release exe are git-ignored.
- `tests/test_stress_and_locks.py` (committed 2026-11-18 at Alexander's request) simulates renames with os.rename/MagicMock;
  it does not exercise the real engine. Its 10k test is marked slow.
  ("Assuming your engine imports look similar to this"). Ask Alexander before committing or deleting it.

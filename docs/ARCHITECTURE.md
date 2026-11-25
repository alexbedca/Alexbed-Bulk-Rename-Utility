# Phase 2: Architecture

> Role: Core Architect Agent

## Tech stack

| Concern | Choice | Why |
|---|---|---|
| Language | **Python 3.11+** | Has the best metadata libraries available (mutagen, pypdf, Pillow). Rule logic stays short and easy to extend. |
| UI | **PySide6 (Qt 6)** | Native widgets with full styling. `QAbstractTableModel` is virtualized, so 10k+ rows cost only what's on screen. Also offers thread pools and drag-and-drop. |
| Audio tags | **mutagen** | ID3v1/v2.x, FLAC/Vorbis, Opus, MP4/M4A, APE, ASF, all through one API. |
| PDF | **pypdf** | Pure Python and fast for reading metadata only. |
| Office | stdlib `zipfile` + `xml.etree` | Reads `docProps/core.xml` without extra dependencies. |
| Images | **Pillow** | EXIF data (date taken, camera, size). |
| Packaging | **PyInstaller `--onefile`** | One `.exe` that needs no install. |

Tauri/Rust and Go/Wails were considered. They produce smaller binaries, but their audio/PDF metadata libraries are weaker, and neither toolchain is installed on this machine.

## Project layout

```
alexed_bru/
  __init__.py            app name/version
  __main__.py            python -m alexed_bru
  paths.py               portable data dir (no registry, no AppData unless read-only)
  core/
    models.py            FileItem, Proposal, Status
    tags.py              <ns:key[:fmt]> template expansion
    pipeline.py          runs the rule stack -> proposals (pure, thread-safe)
    validation.py        OS-name rules + collision detection
    transaction.py       two-phase rename with rollback
    history.py           persistent journal for undo/redo of applied batches
    presets.py           JSON (de)serialisation of rule stacks
  skills/
    base.py              Rule base class, param schema, registry
    rules.py             built-in "Rules" skill
    metadata/            "Smart Media" skill: system, audio, video, document, image providers
                         (containers.py: pure-Python MKV/WebM and AVI header readers)
  ui/
    theme.py             dark palette + QSS, Windows 11 dark title bar
    main_window.py       dual-pane window
    preview_model.py     table model + highlight delegate
    rule_editor.py       auto-generated forms from rule schema
    workers.py           background preview / apply jobs
tests/                   pytest suite for engine, validation, transactions
```

## Data flow

```
 files ──► FileItem list ─┐
 rule stack (UI) ─────────┼──► PreviewJob (QThreadPool)
                          │      1. preload needed metadata (parallel, cached)
                          │      2. Pipeline.run → proposals
                          │      3. validate → statuses
                          └──◄── resultReady(generation, proposals)  stale gens dropped
 Apply ─► Transaction (worker) ─► History.record ─► model refresh
```

## Safety model

1. **Virtual until Apply.** The pipeline is pure: it reads names and metadata and never touches the disk. Proposals live only in memory.
2. **Validation gate.** Only rows with `OK` or `WARNING` status are applied. Rows with errors are skipped and listed.
3. **Two-phase commit.** Every source is first renamed to `.~abru-<uuid>.tmp` in its own folder, then to its final name. This handles swaps, cycles and case-only renames safely.
4. **Rollback.** If any step fails, the completed steps are undone in reverse order and the batch is reported as failed. The disk ends up as it was before.
   Folder batches where one folder is inside another run in *layers* (`transaction._layers`, worked out from the paths: inside folders first, and parents first when undoing); a failure in a later layer puts the earlier layers back too.
5. **Journal.** Successful batches are appended to `history.json` in the portable data folder. Undo applies the inverse batch through the same transaction engine, after checking that each file is still where we left it.

## Extending (Skills and plugins)

To add a rule, subclass `Rule`, declare its parameters as dataclass fields with `param(...)` metadata, and decorate it with `@register_rule`. The UI builds the editor form automatically, and presets serialise it automatically.

To add a metadata source, subclass `MetadataProvider`, set `namespace` and `extensions`, and register it. Its tags become available as `<namespace:key>` immediately.

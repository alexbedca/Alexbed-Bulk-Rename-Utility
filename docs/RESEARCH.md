# Phase 1: Market Research & Competitive Analysis

> Role: Researcher Agent. This summary comes from hands-on knowledge of the tools as of 2026. It was not written from a fresh web survey.

## The field

| Tool | Platform | Strengths | Where it fails users |
|---|---|---|---|
| **Bulk Rename Utility** (TGRMN) | Windows | Huge feature set: 13 numbered rule panels, very fast, free for personal use, mature. | The UI is a wall of ~100 controls on one screen, and rule order is fixed by the panel numbers. Panels give little feedback, and you can't tell which panel caused a change. Undo covers only the last batch. Regex errors are silent. |
| **Advanced Renamer** | Windows / macOS | Stackable, reorderable "methods" (the right idea). Good tag support (ID3, EXIF, video), batch scripting, an undo log. | The method editor is a modal side panel, so you lose sight of the preview while editing. Preview refresh slows down with large lists. No live regex group highlighting. Presets are tied to the install, and it needs an installer. |
| **PowerToys PowerRename** | Windows | Clean shell integration, live preview, regex with `$1`, enumerate, date tokens. | One search/replace rule only, so multi-step pipelines aren't possible. No metadata tags (audio/PDF/Office). Undo is only Ctrl+Z within Explorer. Not portable: it's part of the PowerToys install. |
| **NameChanger** | macOS | Beautiful, minimal, real-time side-by-side preview with highlighted changes. | Mac-only. Few rule types, weak metadata support, no persistent history, and slow or limited with very large sets. |

## UX flaws we are fixing

1. **Cluttered UIs.** We show only the rules you've added. Each rule has a small form that's generated from its schema, so there's no fixed wall of panels.
2. **Fixed or invisible rule order.** Rules form a visible, reorderable stack, and each one can be switched off with its checkbox.
3. **Poor regex feedback.** The pattern is checked as you type (red border plus the error message), and match groups are highlighted in colour in the Original column.
4. **Slow preview.** Previews are computed on a background thread, edits are debounced, and stale results are discarded. Qt's virtualized table paints only the rows on screen, and metadata is read in parallel only when a rule uses its tags.
5. **No undo, or undo that's only one level deep.** Every applied batch is saved to a persistent history (it survives restarts) and can be rolled back. Rule editing has its own undo/redo stack.
6. **Errors found only after renaming.** Invalid characters, Windows reserved names, too-long names, duplicates within the batch and clashes with existing files show in red, and the affected files are skipped when you apply.
7. **Unsafe swaps.** A→B plus B→A swaps, and case-only renames on case-insensitive filesystems, go through a two-phase rename: everything moves to temporary names first. If anything fails, all completed steps are rolled back.
8. **Needs an installer.** It's a single portable `.exe`. Settings, history and presets live in a folder next to it, and nothing is written to the registry.

## Best-in-class feature checklist

- [x] Stackable, reorderable, toggleable rule pipeline
- [x] Search & Replace (first/last/all, case-sensitive option)
- [x] Regex with live match-group highlighting and inline error reporting
- [x] Change case: Title, Smart Title, UPPER, lower, Sentence, Swap
- [x] Insert at position (from start or end) · Remove range / characters / digits / symbols
- [x] Trim and whitespace cleanup · Number padding
- [x] Counter: start, step, padding, position, separator, reset per folder
- [x] Template rule with dynamic tags: `<audio:artist> - <audio:title>`
- [x] Audio tags (ID3v1/v2, Vorbis, FLAC, MP4, Opus, …) through mutagen
- [x] PDF metadata, Office core properties (docx/xlsx/pptx), image EXIF
- [x] System tags: created/modified date (with custom formats), size, parent folder, extension
- [x] Side-by-side preview with highlighted changes
- [x] Validation: invalid characters, reserved names, length, duplicates, existing files
- [x] Transactional two-phase apply with automatic rollback
- [x] Persistent multi-level rename history with rollback
- [x] Rule-edit undo/redo
- [x] JSON presets: save, load, quick menu
- [x] Drag-and-drop files and folders, recursive scanning
- [x] Single-file portable build with no registry footprint

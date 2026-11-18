# Roadmap (v1.2.0 and later)

This is a plan, not a promise. Each phase can ship as its own minor release. Before starting one, re-read
[ARCHITECTURE.md](ARCHITECTURE.md) (data flow and safety model) and keep the rules that apply to every item:

- **Safety model stays intact.** The pipeline is pure (never touches disk). Every change on disk goes through
  `core/transaction.py` (two-phase, full rollback) and is journalled in `history.json`, so History can undo it.
- **Fast tests under 15 seconds** (`pytest -m "not slow"`, about 14 s at v1.1.0). Anything that touches thousands
  of files, real drives or the network is marked `slow`. New UI tests should reuse the window fixture and stay short.
- **Exe stays compact** (about 57 MB at v1.1.0, PyInstaller one-file). New dependencies need a size check
  (`build.ps1` prints the size) and must be pure Python or already bundled. No system installs, no registry.
- **Portable.** Settings and history stay in `AlexedBRU_data\` next to the exe; anything written elsewhere
  (like the Send To shortcut) is opt-in and removable.
- **Plain language.** Every new option gets a plain-English rule card summary, a tooltip and a README section.

Status key: ☐ planned · ◐ in progress · ☑ done

---

## Phase 1: Organization and folders (v1.2.0)

### ☐ Folder renaming mode
Rename folders themselves, not only the files in them.
- **Ordering:** rename deepest folders first, so a parent's new path never invalidates a child's queued
  operation; or plan everything on original paths and let the transaction order steps bottom-up.
- **Mixed batches:** a folder and files inside it in one batch: compute the files' final paths from the
  folder's new name; validation must treat folder and file names in the same parent as one namespace.
- **Rollback/undo:** reverse order (top-down) on rollback and in History. Undo must check the folder still exists
  and is not in use (Explorer windows, open files inside give `PermissionError` → whole batch rolls back).
- **Windows limits:** reserved names, trailing dots/spaces and the 260-character path limit apply to every
  file under a renamed folder (a short folder name change can push deep files over the limit: warn per file).
- **UI:** a "Files / Folders" switch above the preview; folder rows get a folder icon.

### ☐ Sort into subfolders with path templates
Templates that include `\`, e.g. `<artist>\<album>\<track:2>. <title>` or `<date:%Y>\<date:%Y-%m>\<name>`.
- **New step type:** a template result with a separator becomes a *move* (relative to the file's folder or to a
  chosen target root). Tag values stay sanitised (`AC/DC` → `AC-DC`); only the template's own `\` makes folders.
- **Created folders are part of the transaction:** record every folder the batch creates; on rollback (and on
  History undo) remove the ones that end up **empty**, deepest first, and never remove a folder that existed
  before or still holds anything. (`core/duplicates.move_to_folder` already does this for `_Duplicates`.)
- **Same volume only for renames;** a target on another drive means copy + delete, which is not atomic: refuse
  it in v1.2 with a clear message, or treat it as a separate, slower "move across drives" mode later.
- **Collisions:** Auto-number applies per target folder; files from different source folders can collide in
  one target folder, so validation must group by the *target* folder, not the source.
- **Preview:** show the new relative path in the New name column, and a small tree summary
  ("Creates 12 folders, moves 340 files").
- **Tests:** fast tests with a handful of files (create, move, rollback leaves no empty folders, undo); the
  10,000-file move/undo run is `slow`.

---

## Phase 2: Workflow and power polish (v1.3.0)

### ☐ Single instance for Send To
Today Send To opens a second window if the app is already running.
- Use a `QLocalServer`/`QLocalSocket` named per user (+ per exe path, so two portable copies don't collide).
  A second launch sends its file list to the running window and exits.
- Send To passes many paths on one command line (about 32,000 characters max on Windows): for very large
  selections, tell the user to drag the files in instead.
- Fall back to opening normally if the socket fails; never lose the file list. Tests use a unique server name.

### ☐ One-click Quick Recipes
Starter recipes on an empty rule stack ("Tidy music from tags", "Photos by date taken", "Number files 01, 02…",
"Clean messy names"). They are presets with a picture and a one-line description.
- Reuse `core/presets.py`; recipes are data (JSON), not code, so users can add their own.
- Each shows a live before/after example from the user's own first file.

### ☐ Sort by metadata before numbering
Choose the order that counters follow: by name (natural), date taken, track number, file date, size; plus
drag-to-reorder rows.
- Today the counter follows the list order (sorting reorders the real list). Keep one source of truth: the
  sort applies to the model list, and the counter reads `RuleContext.index`.
- Metadata sorts need preloaded tags: run them in the background job with progress, and cache them like
  previews do. Keep 10,000-file sorts responsive (sort keys computed once).
- Manual drag order must survive re-previews and be saved with the session.

### ☐ Import and export rename lists (CSV/TXT)
- **Export:** `old path, new name, status` of the current preview (UTF-8 with BOM for Excel).
- **Import:** a CSV/TXT of `old name → new name` becomes hand-typed names (`FileItem.manual`), so the normal
  validation, Auto-number, transaction and History apply unchanged.
- Rows that don't match a listed file are reported, never guessed. Guard against formula injection when
  exporting (cells starting with `=`, `+`, `-`, `@`).

---

## Phase 3: Broader media support (v1.4.0)

### ☐ MKV / WebM / AVI tags
Today these formats only get system tags (dates, size).
- **MKV/WebM (Matroska/EBML):** a small pure-Python reader for the Segment Info (title, duration, date) and
  Tags elements, plus video track width/height for `<resolution>`/`<quality>`. Read only the first few MB and
  stop at the first Cluster, so big files stay fast.
- **AVI (RIFF):** read the `LIST INFO` chunk (`INAM` title, `IART` artist, `ICRD` date) and the `avih` header
  for resolution/duration.
- **No ffprobe/MediaInfo/pymediainfo:** they would add many MB to the exe or need installs. Measure the exe size
  before and after (target: under +1 MB).
- **Robustness:** corrupt or truncated files must give "no tags", never an exception that stops a preview.
  Add tiny fixture files (a few KB each) to the fast tests; fuzz with truncated copies.

---

## Phase 4: Appearance and distribution (v1.5.0)

### ☐ Dark / Light theme
- Options: follow Windows (default), Dark, Light, in the ⋯ menu; remembered in settings.
- `ui/theme.py` already keeps colours in one place (`C`). Add a light palette with the same names and check
  contrast (WCAG AA) for the preview highlights (added/removed colours) and status dots on both themes.
- Follow system changes live (`QStyleHints.colorSchemeChanged`), including the dark title bar.
- Icons are drawn from SVG paths with theme colours, so they recolour automatically.
- Watch startup time (4–6 s after the font fix): no extra font loading.

### ☐ Scoop and winget manifests
Let people install and update the portable exe with a package manager.
- **Scoop:** a manifest (`alexed-bulk-rename.json`) for a bucket, with `"bin"`, `"shortcuts"`, `"persist":
  "AlexedBRU_data"` (so history and settings survive updates), `checkver` on GitHub releases and `autoupdate`
  using the `.sha256` file.
- **winget:** `InstallerType: portable` manifests for `microsoft/winget-pkgs`; portable installs live in a
  winget folder, so document that data is kept next to the exe there.
- Keep templates in `packaging/` and fill version/URL/hash from the release, ideally in the `bru-release` skill.
- The exe is not code-signed: SmartScreen and some package reviewers may flag it; signing is a separate
  decision (cost of a certificate).

---

## Already done
- ☑ v1.1.0 (2026-11-18): Find duplicates, RegEx from example, plain-English rule cards, hand-edited names,
  auto-number duplicate names, Send To menu, how-to video.
- ☑ Fixed after 1.1.0 (ships in 1.1.1): "&" shown as "_" in menus.

## Small follow-ups (next patch)
- Remove empty `_Duplicates` folders after a duplicate move is undone.
- The name editor sometimes doesn't open on double-click while a preview is refreshing.

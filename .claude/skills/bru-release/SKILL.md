---
name: bru-release
description: Release a new version of Alexed Bulk Rename Utility - version bump, tests, PyInstaller exe build, sha256, GitHub release and verification. Use when asked to release, ship, publish or tag a new Bulk Rename Utility version.
---

# Releasing Alexed Bulk Rename Utility

Repo: https://github.com/alexbedca/Alexed-Bulk-Rename-Utility (branch `main`). General Alexbed publishing conventions
are in the personal `alexbed-github-publish` skill; this file covers only what is specific to this app.
**Confirm with Alexander before pushing, tagging or publishing the release.**

## 1. Prepare
1. `git status` must be clean apart from the intended changes (ask about untracked files such as
   `tests/test_stress_and_locks.py`; never commit them silently). `git pull`.
2. Pick the version (semver) and update it in:
   - `alexed_bru/__init__.py` → `APP_VERSION = "X.Y.Z"` (the window title and About read it)
   - `README.md` → the `**Version:** X.Y.Z` line
3. There is no CHANGELOG file: write the release notes from `git log vPREVIOUS..HEAD --oneline`.
   Keep the v1.0.0 notes' structure: Download, SmartScreen note with the `.sha256`, Highlights, Known limitations.

## 2. Test and build
```powershell
.venv\Scripts\python -m pytest            # must be 0 failed (~10 s)
.venv\Scripts\python -m pytest -m slow    # 10,000-file rename/undo, a few minutes; run before a release
powershell -ExecutionPolicy Bypass -File build.ps1
```
`build.ps1` re-runs the tests and writes `dist\AlexedBulkRename.exe`. Then make the checksum file:
```powershell
$h = (Get-FileHash dist\AlexedBulkRename.exe -Algorithm SHA256).Hash.ToLower()
"$h  AlexedBulkRename.exe" | Set-Content -Encoding ascii dist\AlexedBulkRename.exe.sha256
```
Portable smoke test: copy the exe to `%TEMP%\bru-portable`, start it, rename a few files from `test_library\`
copies, undo from History, and check that `AlexedBRU_data\` was created next to the exe (not in AppData).
Report the startup time honestly (it was 4–6 s after commit c9f7cc5).

## 3. Screenshots (only if the UI changed)
Screenshots live in `docs/screenshots/` (`main-window.png`, `regex-groups.png`, `regex-examples.png`,
`regex-guide.png`, `smart-tags.png`). There is no snapshot hook in this app; capture with computer use
(ask first) and crop to the window.

## 4. Commit, tag, release
```powershell
git add -A; git commit -F msg.txt     # write the message to a file first
git push
git tag vX.Y.Z; git push origin vX.Y.Z
gh release create vX.Y.Z dist\AlexedBulkRename.exe dist\AlexedBulkRename.exe.sha256 `
  -R alexbedca/Alexed-Bulk-Rename-Utility -t "Alexed Bulk Rename Utility X.Y.Z" -F notes.md
```

## 5. Verify
- `gh release view vX.Y.Z -R alexbedca/Alexed-Bulk-Rename-Utility` lists both assets and is marked Latest.
- Download the exe from the release into a new empty folder, check its SHA-256 against the `.sha256`, start it once.
- Tell Alexander the release URL, exe size, test counts (fast + slow) and anything not verified.

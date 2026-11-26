---
name: bru-release
description: Release a new version of Alexbed Bulk Rename Utility - version bump, tests, PyInstaller exe build, sha256, GitHub release and verification. Use when asked to release, ship, publish or tag a new Bulk Rename Utility version.
---

# Releasing Alexbed Bulk Rename Utility

Repo: https://github.com/alexbedca/Alexbed-Bulk-Rename-Utility (branch `main`). General Alexbed publishing conventions
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
`build.ps1` re-runs the tests and writes `dist\AlexbedBulkRename.exe`. Then make the checksum file:
```powershell
$h = (Get-FileHash dist\AlexbedBulkRename.exe -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText("$PWD\dist\AlexbedBulkRename.exe.sha256", "$h  AlexbedBulkRename.exe`n")
```
Use a plain `\n` line ending: `Set-Content` writes CRLF, and then `sha256sum -c` fails (1.1.0 had to re-upload it).
Portable smoke test: copy the exe to `%TEMP%\bru-portable`, start it, rename a few files from `test_library\`
copies, undo from History, and check that `AlexbedBRU_data\` was created next to the exe (not in AppData).
Report the startup time honestly (it was 4–6 s after commit c9f7cc5).

## 3. Screenshots and social card (every release)
Run `.venv\Scripts\python tools\make_screenshots.py`: it drives the real `MainWindow` over `test_library`
(git-ignored; it creates its own demo folders there) at 1400×800 and writes every `docs/screenshots/*.png`
(incl. `folder-mode`, `flatten`, `recipes`) plus `video\build\hdr-flatten.png`. Look at every image before
committing (watch for squeezed labels in the preview bar). Then the how-to video with
`$env:PYTHONPATH=$PWD; .venv\Scripts\python tools\make_tutorial_video.py` (its highlight boxes are pixel
positions on the screenshots: re-check them when the layout moves). Then rebuild the card (it shows the version):
`$env:PYTHONPATH=$PWD; .venv\Scripts\python tools\make_social_preview.py` → `docs/social-preview.png`, and upload it in repo
Settings → Social preview with Claude in Chrome (`find` the hidden "Upload an image..." file input, then
`file_upload`); verify with GraphQL `usesCustomOpenGraphImage`.
Testing the built exe by clicking needs computer use, which Alexander may decline; then report it as NOT TESTED.

## 4. Commit, tag, release
```powershell
git add -A; git commit -F msg.txt     # write the message to a file first
git push
git tag vX.Y.Z; git push origin vX.Y.Z
gh release create vX.Y.Z dist\AlexbedBulkRename.exe dist\AlexbedBulkRename.exe.sha256 `
  -R alexbedca/Alexbed-Bulk-Rename-Utility -t "Alexbed Bulk Rename Utility X.Y.Z" -F notes.md
```

## 5. Verify
- `gh release view vX.Y.Z -R alexbedca/Alexbed-Bulk-Rename-Utility` lists both assets and is marked Latest.
- Download the exe from the release into a new empty folder, check its SHA-256 against the `.sha256`, start it once.
- Tell Alexander the release URL, exe size, test counts (fast + slow) and anything not verified.

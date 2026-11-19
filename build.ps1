# Builds the portable single-file executable: dist\AlexbedBulkRename.exe
# Usage:  powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) { python -m venv .venv }
$py = ".venv\Scripts\python.exe"
& $py -m pip install --quiet -r requirements-dev.txt

& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed; not building." }

& $py -m PyInstaller `
    --noconfirm --clean --onefile --windowed `
    --name AlexbedBulkRename `
    --icon assets\branding\app.ico `
    --add-data "assets\branding\app.ico;assets\branding" `
    --add-data "assets\branding\png\logo-mark-64.png;assets\branding\png" `
    --add-data "assets\branding\png\logo-mark-128.png;assets\branding\png" `
    --add-data "assets\ui;assets\ui" `
    --exclude-module tkinter `
    --exclude-module PySide6.QtWebEngineCore `
    --exclude-module PySide6.QtWebEngineWidgets `
    --exclude-module PySide6.QtQuick `
    --exclude-module PySide6.QtQml `
    --exclude-module PySide6.QtPdf `
    --exclude-module PySide6.Qt3DCore `
    --exclude-module PySide6.QtMultimedia `
    run.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

$exe = Get-Item dist\AlexbedBulkRename.exe
"Built {0} ({1:N1} MB)" -f $exe.FullName, ($exe.Length / 1MB)

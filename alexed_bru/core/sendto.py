# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional shortcut in Explorer's right-click "Send to" menu.

The shortcut lives in the user's own SendTo folder
(%APPDATA%\\Microsoft\\Windows\\SendTo), so no admin rights are needed and
nothing else on the system changes. Selected files are passed to the app on
its command line, which it already accepts.

Shortcuts are made with Windows' own WScript.Shell through PowerShell, so no
extra libraries are needed. Values reach PowerShell as environment
variables, never pasted into the script, so odd characters in paths are safe.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from alexed_bru.paths import app_root

SHORTCUT_NAME = "Alexed Bulk Rename.lnk"
_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW: no console flash from a GUI app

_CREATE = (
    "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:ABRU_LNK);"
    "$s.TargetPath = $env:ABRU_TARGET; $s.Arguments = $env:ABRU_ARGS;"
    "$s.WorkingDirectory = $env:ABRU_DIR; $s.IconLocation = $env:ABRU_ICON;"
    "$s.Description = 'Rename the selected files with Alexed Bulk Rename Utility'; $s.Save()"
)
_READ = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:ABRU_LNK);"
         "Write-Output $s.TargetPath; Write-Output $s.Arguments")


def sendto_dir() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / \
        "Microsoft" / "Windows" / "SendTo"


def shortcut_path(folder: Path | None = None) -> Path:
    return (folder or sendto_dir()) / SHORTCUT_NAME


def is_installed(folder: Path | None = None) -> bool:
    return shortcut_path(folder).exists()


def launch_command() -> tuple[str, str, str, str]:
    """(target, arguments, working folder, icon) that start this copy of the app."""
    if getattr(sys, "frozen", False):  # the portable exe
        exe = str(Path(sys.executable).resolve())
        return exe, "", str(Path(exe).parent), f"{exe},0"
    # From source: pythonw (no console window) running run.py
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    root = app_root()
    icon = root / "assets" / "branding" / "app.ico"
    return (str(pythonw if pythonw.exists() else python), f'"{root / "run.py"}"', str(root),
            str(icon) if icon.exists() else "")


def _powershell(script: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          env={**os.environ, **env}, capture_output=True, text=True, timeout=30,
                          creationflags=_NO_WINDOW if os.name == "nt" else 0)


def install(folder: Path | None = None) -> Path:
    """Create (or refresh) the shortcut. Raises OSError with the reason on failure."""
    if os.name != "nt":
        raise OSError("The Send To menu is a Windows feature")
    lnk = shortcut_path(folder)
    lnk.parent.mkdir(parents=True, exist_ok=True)
    target, args, workdir, icon = launch_command()
    proc = _powershell(_CREATE, {"ABRU_LNK": str(lnk), "ABRU_TARGET": target, "ABRU_ARGS": args,
                                 "ABRU_DIR": workdir, "ABRU_ICON": icon})
    if proc.returncode != 0 or not lnk.exists():
        raise OSError((proc.stderr or proc.stdout or "PowerShell could not create the shortcut").strip())
    return lnk


def remove(folder: Path | None = None) -> None:
    """Delete only our own shortcut; nothing else in the folder is touched."""
    try:
        shortcut_path(folder).unlink()
    except FileNotFoundError:
        pass


def read_shortcut(lnk: Path) -> tuple[str, str]:
    """(target, arguments) stored in a shortcut."""
    proc = _powershell(_READ, {"ABRU_LNK": str(lnk)})
    lines = (proc.stdout.splitlines() + ["", ""])[:2]
    return lines[0].strip(), lines[1].strip()

"""Build le .exe via PyInstaller, dans un thread."""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "dist"
BUILD = ROOT / "build"
SPEC = ROOT / "PZSaveSync.spec"
ENTRY = ROOT / "src" / "pzsavesync" / "__main__.py"


def ensure_pyinstaller(log: Callable[[str], None]) -> bool:
    try:
        import PyInstaller  # noqa: F401
        return True
    except ImportError:
        log("PyInstaller absent, installation...")
        res = subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyinstaller"],
            capture_output=True, text=True,
        )
        log(res.stdout)
        if res.returncode != 0:
            log(res.stderr)
            return False
        return True


def build(log: Callable[[str], None], on_done: Callable[[bool, Path | None], None]):
    def run():
        try:
            if not ensure_pyinstaller(log):
                on_done(False, None)
                return
            log(f"Build via {sys.executable}")
            log(f"Entry: {ENTRY}")
            cmd = [
                sys.executable, "-m", "PyInstaller",
                "--noconfirm",
                "--clean",
                "--onefile",
                "--windowed",
                "--name", "PZSaveSync",
                "--paths", str(ROOT / "src"),
                "--collect-all", "customtkinter",
                # tkinterdnd2 = drag-and-drop. Doit être collecté pour que
                # le .exe ait la feature (le code Python a un fallback mais
                # PyInstaller ne le packagerait pas autrement).
                "--collect-all", "tkinterdnd2",
                str(ENTRY),
            ]
            log("Commande : " + " ".join(cmd))
            proc = subprocess.Popen(
                cmd, cwd=ROOT,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            assert proc.stdout
            for line in proc.stdout:
                log(line.rstrip())
            rc = proc.wait()
            exe = DIST / "PZSaveSync.exe"
            if rc == 0 and exe.exists():
                log(f"OK : {exe}")
                on_done(True, exe)
            else:
                log(f"Échec (code {rc}).")
                on_done(False, None)
        except Exception as e:
            log(f"Erreur : {e}")
            on_done(False, None)

    threading.Thread(target=run, daemon=True).start()

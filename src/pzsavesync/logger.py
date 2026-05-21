"""Logger persistant : tous les events de l'app sont écrits dans un fichier rotatif.

Fichier : %APPDATA%/PZSaveSync/logs/pzsavesync-YYYY-MM-DD.log
Rétention : 14 jours (purge auto au démarrage).
"""
from __future__ import annotations

import datetime as dt
import logging
import logging.handlers
import os
import sys
from pathlib import Path


def _logs_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "PZSaveSync" / "logs"
    return Path.home() / ".config" / "pzsavesync" / "logs"


LOGS_DIR = _logs_dir()
LOG_FILE = LOGS_DIR / f"pzsavesync-{dt.date.today().isoformat()}.log"


_configured = False


def setup() -> logging.Logger:
    """Configure le logger root. Idempotent."""
    global _configured
    logger = logging.getLogger("pzsavesync")
    if _configured:
        return logger

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Handler fichier — rotation manuelle par date du jour
    try:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception as e:
        # Si le fichier n'est pas accessible, on log juste sur stderr
        print(f"[logger] impossible d'ouvrir {LOG_FILE} : {e}", file=sys.stderr)

    # Handler console (INFO+) — silencieux en mode --windowed sans console
    try:
        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        logger.addHandler(ch)
    except Exception:
        pass

    _configured = True
    purge_old(days=14)
    logger.info("Logger initialisé — %s", LOG_FILE)
    return logger


def get(name: str = "pzsavesync") -> logging.Logger:
    """Renvoie un logger enfant (auto-setup si pas fait)."""
    if not _configured:
        setup()
    if name == "pzsavesync":
        return logging.getLogger("pzsavesync")
    return logging.getLogger(f"pzsavesync.{name}")


def purge_old(days: int = 14) -> int:
    """Supprime les fichiers de log plus vieux que `days` jours. Renvoie le nombre supprimé."""
    if not LOGS_DIR.exists():
        return 0
    cutoff = dt.datetime.now() - dt.timedelta(days=days)
    deleted = 0
    for f in LOGS_DIR.glob("pzsavesync-*.log"):
        try:
            mtime = dt.datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                f.unlink(missing_ok=True)
                deleted += 1
        except OSError:
            continue
    return deleted


def open_logs_folder():
    """Ouvre le dossier de logs dans l'explorateur (utile depuis l'UI)."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(LOGS_DIR)
    elif sys.platform == "darwin":
        import subprocess
        subprocess.Popen(["open", str(LOGS_DIR)])
    else:
        import subprocess
        subprocess.Popen(["xdg-open", str(LOGS_DIR)])

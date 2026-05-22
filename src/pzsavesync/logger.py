"""Logger persistant : tous les events de l'app sont écrits dans un fichier rotatif.

Fichier : %APPDATA%/PZSaveSync/logs/pzsavesync.log
Rotation : à minuit, suffixé par YYYY-MM-DD (TimedRotatingFileHandler).
Rétention : 14 jours (purge auto au démarrage + backupCount du handler).
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
# Le fichier "courant" sans date. Le TimedRotatingFileHandler rotationnera
# automatiquement vers `pzsavesync.log.YYYY-MM-DD` à minuit, peu importe la
# durée d'exécution de l'app. Avant on figeait la date à l'import, donc une
# session ouverte sur 2 jours écrivait toute la nuit dans le fichier de la veille.
LOG_FILE = LOGS_DIR / "pzsavesync.log"


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

    # Handler fichier — rotation à minuit, suffixe = date.
    # backupCount=14 → retient 14 fichiers historiques (= 14 jours).
    try:
        fh = logging.handlers.TimedRotatingFileHandler(
            LOG_FILE,
            when="midnight",
            interval=1,
            backupCount=14,
            encoding="utf-8",
            utc=False,
        )
        fh.suffix = "%Y-%m-%d"
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
    """Supprime les fichiers de log plus vieux que `days` jours. Renvoie le nombre supprimé.

    Couvre l'ANCIEN format `pzsavesync-YYYY-MM-DD.log` (avant TimedRotating)
    et le NOUVEAU format `pzsavesync.log.YYYY-MM-DD` (avec rotation).
    """
    if not LOGS_DIR.exists():
        return 0
    cutoff = dt.datetime.now() - dt.timedelta(days=days)
    deleted = 0
    patterns = ("pzsavesync-*.log", "pzsavesync.log.*")
    for pattern in patterns:
        for f in LOGS_DIR.glob(pattern):
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

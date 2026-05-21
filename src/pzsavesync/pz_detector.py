"""Détection si Project Zomboid est en cours d'exécution.

Sert à bloquer les opérations destructives (pull, import) tant que PZ tourne :
PZ tient des locks sur les fichiers de la save en cours d'écriture et peut
corrompre le bundle si on l'écrase dessous.

Cross-platform : Windows (tasklist), macOS/Linux (pgrep ou /proc).
"""
from __future__ import annotations

import platform
import subprocess
from typing import Iterable

# Noms de process à surveiller (couvre B41/B42 + Windows/Linux/Mac)
PZ_PROCESS_NAMES = (
    "ProjectZomboid64.exe",
    "ProjectZomboid32.exe",
    "PZServer.exe",       # serveur dédié
    "ProjectZomboid",     # Linux/Mac binary
    "projectzomboid",
)


def _list_processes_windows() -> set[str]:
    """Liste les noms de process via tasklist (Windows).

    Renvoie un set de noms en minuscules pour comparaison case-insensitive.
    """
    try:
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return set()
    if out.returncode != 0:
        return set()
    names: set[str] = set()
    for line in out.stdout.splitlines():
        # CSV : "ImageName","PID","SessionName","Session#","MemUsage"
        parts = line.strip().split(",")
        if not parts:
            continue
        name = parts[0].strip().strip('"').lower()
        if name:
            names.add(name)
    return names


def _list_processes_unix() -> set[str]:
    """Liste les noms de process via ps (Linux/macOS)."""
    try:
        out = subprocess.run(
            ["ps", "-A", "-o", "comm="],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return set()
    if out.returncode != 0:
        return set()
    return {line.strip().lower() for line in out.stdout.splitlines() if line.strip()}


def list_running_processes() -> set[str]:
    """Renvoie un set des noms de process en cours (en minuscules)."""
    if platform.system() == "Windows":
        return _list_processes_windows()
    return _list_processes_unix()


def is_pz_running(extra_names: Iterable[str] = ()) -> tuple[bool, list[str]]:
    """Détecte si Project Zomboid (ou un serveur PZ) tourne actuellement.

    Returns:
        (running, matched_names) — running est True si au moins un process
        de PZ_PROCESS_NAMES (+ extra_names) est dans la liste.
    """
    targets = {n.lower() for n in (*PZ_PROCESS_NAMES, *extra_names)}
    running = list_running_processes()
    matched = sorted(n for n in running if n in targets)
    return (len(matched) > 0), matched

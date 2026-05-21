"""Auto-détection des dossiers cloud locaux (Dropbox, Drive, OneDrive).

L'idée : au premier lancement, suggérer à l'utilisateur les chemins qui
existent déjà sur son PC plutôt que de lui faire taper à la main.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CloudCandidate:
    label: str           # affiché à l'utilisateur (ex. "Dropbox")
    path: Path
    icon: str = "☁"      # emoji facultatif


def _candidates() -> list[CloudCandidate]:
    """Construit la liste des chemins standards à vérifier."""
    home = Path.home()
    userprofile = Path(os.environ.get("USERPROFILE", str(home)))
    onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    onedrive_biz = os.environ.get("OneDriveCommercial")

    items: list[CloudCandidate] = []

    # Dropbox
    for p in (
        userprofile / "Dropbox",
        home / "Dropbox",
    ):
        items.append(CloudCandidate("Dropbox", p, "📦"))

    # OneDrive (perso et pro)
    if onedrive:
        items.append(CloudCandidate("OneDrive (perso)", Path(onedrive), "☁"))
    if onedrive_biz:
        items.append(CloudCandidate("OneDrive (pro)", Path(onedrive_biz), "🏢"))
    items.extend([
        CloudCandidate("OneDrive (perso)", userprofile / "OneDrive", "☁"),
        CloudCandidate("OneDrive (pro)", userprofile / "OneDrive - Personal", "☁"),
    ])

    # Google Drive — plusieurs variantes selon la version du client
    items.extend([
        CloudCandidate("Google Drive", userprofile / "Google Drive", "🟢"),
        CloudCandidate("Google Drive", userprofile / "GoogleDrive", "🟢"),
        # Drive File Stream / "Mon Drive" sur volume G:
        CloudCandidate("Google Drive (G:)", Path("G:/Mon Drive"), "🟢"),
        CloudCandidate("Google Drive (G:)", Path("G:/My Drive"), "🟢"),
        CloudCandidate("Google Drive (H:)", Path("H:/Mon Drive"), "🟢"),
    ])

    # iCloud Drive (Windows + macOS)
    items.extend([
        CloudCandidate("iCloud Drive", userprofile / "iCloudDrive", "🍎"),
        CloudCandidate("iCloud Drive", home / "Library" / "Mobile Documents" / "com~apple~CloudDocs", "🍎"),
    ])

    # MEGA, pCloud, Sync.com — bonus
    items.extend([
        CloudCandidate("MEGA", userprofile / "MEGA", "🟥"),
        CloudCandidate("pCloud", userprofile / "pCloud Drive", "🔷"),
        CloudCandidate("pCloud", Path("P:/")),
    ])

    return items


def detect() -> list[CloudCandidate]:
    """Renvoie les dossiers cloud qui EXISTENT vraiment sur ce PC."""
    seen: set[str] = set()
    found: list[CloudCandidate] = []
    for c in _candidates():
        try:
            if not c.path.exists() or not c.path.is_dir():
                continue
        except OSError:
            continue
        key = str(c.path).lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(c)
    return found


def suggest_subfolder(parent: Path, name: str = "PZ_avec_potes") -> Path:
    """Renvoie un sous-chemin suggéré sans le créer."""
    return parent / name

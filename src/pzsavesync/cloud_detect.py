"""Auto-détection des dossiers cloud locaux (Dropbox, Drive, OneDrive).

L'idée : au premier lancement, suggérer à l'utilisateur les chemins qui
existent déjà sur son PC plutôt que de lui faire taper à la main.

v0.5.0 : ajout de `find_gdrive_roots()` et `open_drive_folder_browser()` pour
détecter le disque Google Drive for Desktop (registre Windows + scan lettres)
et ouvrir un sélecteur de dossier directement à la bonne racine.
"""
from __future__ import annotations

import os
import re
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
    ])
    # Drive for Desktop : on cherche dynamiquement la lettre de disque
    for root in find_gdrive_roots():
        label = f"Google Drive ({root.drive})"
        items.append(CloudCandidate(label, root, "🟢"))

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


# ====================================================== Google Drive for Desktop

# Noms de sous-dossier utilisés selon la locale de Drive
_DRIVE_SUBFOLDERS = ("My Drive", "Mon Drive", "My drive", "Meu Drive", "Mi unidad")


def _gdrive_letter_from_registry() -> str | None:
    """Lit la lettre de disque Drive for Desktop dans le registre Windows."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Google\DriveFS",
        )
        # La valeur est soit "DefaultMountPoint" (lettre ex: "G:")
        # soit dans une sous-clé par compte
        try:
            val, _ = winreg.QueryValueEx(key, "DefaultMountPoint")
            if val and len(val) >= 1:
                return val[0].upper()  # "G:" → "G"
        except FileNotFoundError:
            pass
        # Chercher dans les sous-clés (un compte par clé)
        i = 0
        while True:
            try:
                sub_name = winreg.EnumKey(key, i)
                sub = winreg.OpenKey(key, sub_name)
                try:
                    val, _ = winreg.QueryValueEx(sub, "MountPoint")
                    if val:
                        return val[0].upper()
                except FileNotFoundError:
                    pass
                i += 1
            except OSError:
                break
    except Exception:
        pass
    return None


def find_gdrive_roots() -> list[Path]:
    """Retourne la liste des racines Google Drive for Desktop détectées.

    Stratégie (Windows) :
    1. Registre HKCU\\Software\\Google\\DriveFS → lettre de disque
    2. Scan de toutes les lettres D-Z à la recherche des sous-dossiers Drive
    3. Chemins standards (G:\\My Drive, H:\\Mon Drive, etc.)

    Chaque entrée pointe vers le sous-dossier "My Drive" (ou équivalent).
    """
    roots: list[Path] = []
    seen: set[str] = set()

    def _add(p: Path) -> None:
        try:
            if p.exists() and p.is_dir() and str(p).lower() not in seen:
                seen.add(str(p).lower())
                roots.append(p)
        except OSError:
            pass

    # 1. Registre
    reg_letter = _gdrive_letter_from_registry()
    if reg_letter:
        for sub in _DRIVE_SUBFOLDERS:
            _add(Path(f"{reg_letter}:/{sub}"))
        # Racine du disque aussi (certaines configs n'ont pas de sous-dossier)
        _add(Path(f"{reg_letter}:/"))

    # 2. Scan D-Z
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        drive = Path(f"{letter}:/")
        try:
            if not drive.exists():
                continue
        except OSError:
            continue
        for sub in _DRIVE_SUBFOLDERS:
            candidate = drive / sub
            _add(candidate)

    # 3. Mirror mode (dossier local classique)
    home = Path.home()
    userprofile = Path(os.environ.get("USERPROFILE", str(home)))
    for p in (userprofile / "Google Drive", userprofile / "GoogleDrive", home / "Google Drive"):
        _add(p)

    return roots


def find_best_gdrive_root() -> Path | None:
    """Retourne la première racine Drive for Desktop trouvée, ou None."""
    roots = find_gdrive_roots()
    return roots[0] if roots else None


def parse_folder_id_from_url(url: str) -> str | None:
    """Extrait l'ID de dossier Drive depuis une URL partagée.

    Accepte :
      https://drive.google.com/drive/folders/FOLDER_ID
      https://drive.google.com/drive/u/0/folders/FOLDER_ID
    Retourne None si le format n'est pas reconnu.
    """
    m = re.search(r"/folders/([a-zA-Z0-9_-]{20,})", url)
    return m.group(1) if m else None

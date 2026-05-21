r"""Vérification que les mods requis par une save sont installés localement.

PZ cherche les mods à deux endroits :
1. %USERPROFILE%\Zomboid\mods\<mod_id>\            (mods manuels / "Mods Locaux")
2. %PROGRAMFILES(X86)%\Steam\steamapps\workshop\content\108600\<workshop_id>\
   (Steam Workshop — 108600 est l'AppID de PZ)

Un mod Workshop est en fait un dossier Workshop qui CONTIENT un sous-dossier
mod (parfois plusieurs). Le `Mods=` du .ini liste les **noms** des mods,
indépendamment du fait qu'ils viennent du Workshop ou pas.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModCheckResult:
    """Résultat d'une vérification des mods requis."""
    required_mods: list[str] = field(default_factory=list)
    required_workshop: list[str] = field(default_factory=list)
    found_mods: list[str] = field(default_factory=list)
    found_workshop: list[str] = field(default_factory=list)
    missing_mods: list[str] = field(default_factory=list)
    missing_workshop: list[str] = field(default_factory=list)
    scanned_paths: list[Path] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return not self.missing_mods and not self.missing_workshop

    @property
    def summary(self) -> str:
        if self.all_ok:
            return "✓ Tous les mods requis sont installés."
        parts = []
        if self.missing_mods:
            parts.append(f"{len(self.missing_mods)} mod(s) manquant(s)")
        if self.missing_workshop:
            parts.append(f"{len(self.missing_workshop)} Workshop ID(s) manquant(s)")
        return "⚠ " + ", ".join(parts) + "."


def _zomboid_mods_dir() -> Path:
    return Path.home() / "Zomboid" / "mods"


def _steam_workshop_candidates() -> list[Path]:
    """Renvoie les chemins possibles de Steam Workshop pour PZ (AppID 108600)."""
    candidates: list[Path] = []
    # Windows : drives & Program Files
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    for base in (program_files_x86, program_files):
        candidates.append(Path(base) / "Steam" / "steamapps" / "workshop" / "content" / "108600")
    # Autres lettres de drive (D:, E:, F:) — Steam libraries fréquentes
    for letter in "CDEFGH":
        for fold in ("Steam", "SteamLibrary"):
            candidates.append(Path(f"{letter}:/") / fold / "steamapps" / "workshop" / "content" / "108600")
    # Linux / Mac
    home = Path.home()
    candidates.append(home / ".steam" / "steam" / "steamapps" / "workshop" / "content" / "108600")
    candidates.append(home / ".local" / "share" / "Steam" / "steamapps" / "workshop" / "content" / "108600")
    candidates.append(home / "Library" / "Application Support" / "Steam" / "steamapps" / "workshop" / "content" / "108600")
    return candidates


def _scan_mods_in_dir(directory: Path) -> set[str]:
    """Renvoie les noms de mods (= noms de dossiers contenant un mod.info) dans une arbo donnée."""
    found: set[str] = set()
    if not directory.exists() or not directory.is_dir():
        return found
    try:
        for entry in directory.iterdir():
            if not entry.is_dir():
                continue
            # Cas 1 : le dossier lui-même est un mod (contient mod.info à la racine)
            if (entry / "mod.info").exists():
                found.add(entry.name)
            # Cas 2 : Workshop — sous-dossier "mods/<mod_id>/mod.info"
            mods_sub = entry / "mods"
            if mods_sub.exists() and mods_sub.is_dir():
                for sub in mods_sub.iterdir():
                    if sub.is_dir() and (sub / "mod.info").exists():
                        found.add(sub.name)
    except (OSError, PermissionError):
        pass
    return found


def installed_mod_names(extra_search_paths: list[Path] | None = None) -> tuple[set[str], list[Path]]:
    """Liste tous les mod-names installés (Zomboid/mods + Steam Workshop).

    Returns:
        (mod_names, scanned_paths)
    """
    found: set[str] = set()
    scanned: list[Path] = []

    user_mods = _zomboid_mods_dir()
    scanned.append(user_mods)
    found |= _scan_mods_in_dir(user_mods)

    for ws in _steam_workshop_candidates():
        if ws.exists():
            scanned.append(ws)
            found |= _scan_mods_in_dir(ws)

    for extra in (extra_search_paths or []):
        scanned.append(extra)
        found |= _scan_mods_in_dir(extra)

    return found, scanned


def installed_workshop_ids() -> set[str]:
    """Liste les Workshop IDs (= noms de dossier dans .../workshop/content/108600/) installés."""
    ids: set[str] = set()
    for ws in _steam_workshop_candidates():
        if not ws.exists() or not ws.is_dir():
            continue
        try:
            for entry in ws.iterdir():
                if entry.is_dir() and entry.name.isdigit():
                    ids.add(entry.name)
        except (OSError, PermissionError):
            continue
    return ids


def check_mods(required_mods: list[str], required_workshop: list[str]) -> ModCheckResult:
    """Compare la liste requise au contenu local. Renvoie un rapport détaillé."""
    installed_names, scanned = installed_mod_names()
    installed_ids = installed_workshop_ids()

    found_mods = [m for m in required_mods if m in installed_names]
    missing_mods = [m for m in required_mods if m not in installed_names]

    found_ws = [w for w in required_workshop if w in installed_ids]
    missing_ws = [w for w in required_workshop if w not in installed_ids]

    return ModCheckResult(
        required_mods=list(required_mods),
        required_workshop=list(required_workshop),
        found_mods=found_mods,
        found_workshop=found_ws,
        missing_mods=missing_mods,
        missing_workshop=missing_ws,
        scanned_paths=scanned,
    )

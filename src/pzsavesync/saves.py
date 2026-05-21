"""Détection des saves PZ locales."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pzsavesync import bundle as bundle_mod
from pzsavesync import inspector


def zomboid_root() -> Path:
    """Renvoie le chemin du dossier Zomboid de l'utilisateur.

    Cross-platform :
    - Windows  : %USERPROFILE%/Zomboid
    - macOS    : ~/Zomboid (PZ stocke aussi là)
    - Linux    : ~/Zomboid (idem)

    Variable d'environnement override : PZ_ZOMBOID_ROOT (chemin absolu).
    """
    override = os.environ.get("PZ_ZOMBOID_ROOT")
    if override:
        return Path(override)
    return Path.home() / "Zomboid"


def list_multiplayer_saves() -> list[str]:
    root = zomboid_root() / "Saves" / "Multiplayer"
    if not root.exists():
        return []
    return sorted([p.name for p in root.iterdir() if p.is_dir()])


def has_server_files() -> bool:
    return (zomboid_root() / "Server").exists()


@dataclass
class SaveEntry:
    name: str
    info: inspector.SaveInfo
    companions: dict[str, Path]

    @property
    def is_server_save(self) -> bool:
        return self.info.kind == "server_save"

    @property
    def is_client_save(self) -> bool:
        return self.info.kind == "client_save"

    @property
    def transferable(self) -> bool:
        """Une save est transférable si c'est une save de serveur hébergée localement."""
        return self.is_server_save and "save_dir" in self.companions

    @property
    def companions_status(self) -> dict[str, bool]:
        return {
            "save_dir": "save_dir" in self.companions,
            "db": "db" in self.companions,
            "server_ini": any(k.endswith("ini") for k in self.companions),
            "server_sandbox": any(k.endswith("vars") or "sandboxvars" in k.lower() for k in self.companions) or any("SandboxVars" in str(v) for v in self.companions.values()),
            "server_spawn": any("spawnregions" in str(v).lower() for v in self.companions.values()),
        }


def list_all_with_info() -> list[SaveEntry]:
    """Liste toutes les saves Multiplayer avec leurs infos d'inspection."""
    root = zomboid_root() / "Saves" / "Multiplayer"
    if not root.exists():
        return []
    entries: list[SaveEntry] = []
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        info = inspector.inspect_save(p)
        companions = bundle_mod.find_companions(p.name)
        entries.append(SaveEntry(name=p.name, info=info, companions=companions))
    return entries

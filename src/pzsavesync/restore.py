"""Restauration des backups locaux créés par extract_bundle.

Les backups sont dans ``~/PZSaveSync_LocalBackups/pre_import_<save>_<ts>/`` et
contiennent :
    save.zip                       → archive de Saves/Multiplayer/<save>/
    <save>.db                      → si présent
    <save>.db-wal / .db-shm / .db-journal → compagnons SQLite
    <save>.ini, _SandboxVars.lua, _spawnregions.lua, _spawnpoints.lua
"""
from __future__ import annotations

import datetime as dt
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from pzsavesync import bundle as bundle_mod

_BACKUP_NAME_RX = re.compile(r"^pre_import_(?P<save>.+)_(?P<ts>\d{8}-\d{6})$")


@dataclass
class BackupEntry:
    path: Path
    save_name: str
    timestamp: str  # YYYYMMDD-HHMMSS
    size_bytes: int = 0
    has_save_zip: bool = False
    has_db: bool = False
    db_companions: list[str] = field(default_factory=list)
    server_files: list[str] = field(default_factory=list)

    @property
    def display_timestamp(self) -> str:
        """ISO-like : 2026-05-22 14:30:00."""
        try:
            d = dt.datetime.strptime(self.timestamp, "%Y%m%d-%H%M%S")
            return d.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return self.timestamp

    @property
    def restorable(self) -> bool:
        """Au minimum un save.zip → on peut restaurer la save_dir."""
        return self.has_save_zip


def list_backups(backup_root: Path) -> list[BackupEntry]:
    """Liste les backups disponibles, triés du plus récent au plus ancien."""
    if not backup_root.exists():
        return []
    out: list[BackupEntry] = []
    for entry in backup_root.iterdir():
        if not entry.is_dir():
            continue
        m = _BACKUP_NAME_RX.match(entry.name)
        if not m:
            continue
        be = BackupEntry(
            path=entry,
            save_name=m.group("save"),
            timestamp=m.group("ts"),
        )
        size = 0
        for f in entry.rglob("*"):
            if not f.is_file():
                continue
            try:
                size += f.stat().st_size
            except OSError:
                continue
            n = f.name
            if n == "save.zip":
                be.has_save_zip = True
            elif n == f"{be.save_name}.db":
                be.has_db = True
            elif n.startswith(f"{be.save_name}.db-"):
                be.db_companions.append(n)
            elif n.startswith(f"{be.save_name}") and (
                n.endswith(".ini")
                or n.endswith("_SandboxVars.lua")
                or n.endswith("_spawnregions.lua")
                or n.endswith("_spawnpoints.lua")
            ):
                be.server_files.append(n)
        be.size_bytes = size
        out.append(be)
    out.sort(key=lambda b: b.timestamp, reverse=True)
    return out


@dataclass
class RestoreReport:
    save_name: str
    save_dir: Path
    db_path: Path | None
    db_companions_restored: list[Path]
    server_files: list[Path]
    pre_restore_backup: Path | None  # backup créé avant la restauration


def restore_backup(
    backup: BackupEntry,
    root: Path | None = None,
    safety_backup_dir: Path | None = None,
) -> RestoreReport:
    """Restaure un backup dans l'arborescence Zomboid.

    SÉCURITÉ : avant de restaurer (qui écrase l'état courant), on fait un
    backup pré-restore dans ``safety_backup_dir`` (au cas où l'utilisateur
    se trompe de backup à restaurer). Le rapport indique son chemin.

    Si ``safety_backup_dir`` est ``None``, l'opération échoue — le but de
    cette fonction est de protéger l'utilisateur, pas de l'exposer.
    """
    if not backup.restorable:
        raise ValueError(
            f"Backup '{backup.path.name}' incomplet (pas de save.zip) — "
            "rien à restaurer."
        )
    if safety_backup_dir is None:
        raise ValueError(
            "safety_backup_dir est obligatoire — la restauration écrase l'état "
            "actuel, on doit d'abord en faire un backup."
        )
    if root is None:
        root = bundle_mod.zomboid_root()

    save_name = backup.save_name
    bundle_mod._validate_save_name(save_name)
    save_dir = root / "Saves" / "Multiplayer" / save_name
    db_path = root / "db" / f"{save_name}.db"
    server_dir = root / "Server"

    # --- 1. Pre-restore safety backup (de l'état actuel) ---
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    pre = safety_backup_dir / f"pre_restore_{save_name}_{ts}"
    pre.mkdir(parents=True, exist_ok=True)
    if save_dir.exists():
        shutil.make_archive(str(pre / "save"), "zip", root_dir=save_dir)
    if db_path.exists():
        shutil.copy2(db_path, pre / db_path.name)
    for sfx in bundle_mod._DB_COMPANION_SUFFIXES:
        comp = db_path.with_name(db_path.name + sfx)
        if comp.exists():
            shutil.copy2(comp, pre / comp.name)
    for suffix in (".ini", "_SandboxVars.lua", "_spawnregions.lua", "_spawnpoints.lua"):
        f = server_dir / f"{save_name}{suffix}"
        if f.exists():
            shutil.copy2(f, pre / f.name)

    # --- 2. Effacement de la save_dir actuelle + compagnons SQLite résiduels ---
    if save_dir.exists():
        shutil.rmtree(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    server_dir.mkdir(parents=True, exist_ok=True)
    (root / "db").mkdir(parents=True, exist_ok=True)
    for sfx in bundle_mod._DB_COMPANION_SUFFIXES:
        stale = db_path.with_name(db_path.name + sfx)
        if stale.exists():
            try:
                stale.unlink()
            except OSError:
                pass

    # --- 3. Extraction du save.zip dans save_dir ---
    save_zip = backup.path / "save.zip"
    with zipfile.ZipFile(save_zip, "r") as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            target = bundle_mod._safe_join(save_dir, name)
            bundle_mod._atomic_extract_file(zf, name, target)

    # --- 4. Restauration db + compagnons ---
    restored_db: Path | None = None
    restored_db_comps: list[Path] = []
    src_db = backup.path / f"{save_name}.db"
    if src_db.exists():
        shutil.copy2(src_db, db_path)
        restored_db = db_path
        for sfx in bundle_mod._DB_COMPANION_SUFFIXES:
            src_comp = backup.path / f"{save_name}.db{sfx}"
            if src_comp.exists():
                dst_comp = db_path.with_name(db_path.name + sfx)
                shutil.copy2(src_comp, dst_comp)
                restored_db_comps.append(dst_comp)

    # --- 5. Restauration fichiers Server ---
    restored_server: list[Path] = []
    for suffix in (".ini", "_SandboxVars.lua", "_spawnregions.lua", "_spawnpoints.lua"):
        src = backup.path / f"{save_name}{suffix}"
        if src.exists():
            dst = server_dir / src.name
            shutil.copy2(src, dst)
            restored_server.append(dst)

    return RestoreReport(
        save_name=save_name,
        save_dir=save_dir,
        db_path=restored_db,
        db_companions_restored=restored_db_comps,
        server_files=restored_server,
        pre_restore_backup=pre,
    )

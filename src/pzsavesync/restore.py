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

# Reconnaît deux préfixes :
#  - `pre_import_` : backup auto créé avant un pull/import (extract_bundle)
#  - `pre_restore_` : backup auto créé avant une restauration (restore_backup)
# Sans ça, un user qui restaure le mauvais backup ne voyait pas le filet de
# secours créé juste avant — il faut pouvoir revenir en arrière en 1 clic.
_BACKUP_NAME_RX = re.compile(
    r"^pre_(?P<kind>import|restore)_(?P<save>.+)_(?P<ts>\d{8}-\d{6})$"
)


@dataclass
class BackupEntry:
    path: Path
    save_name: str
    timestamp: str  # YYYYMMDD-HHMMSS
    kind: str = "import"  # "import" (avant pull/import) | "restore" (avant restauration)
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

    @property
    def kind_label(self) -> str:
        return "avant import" if self.kind == "import" else "avant restauration"


_SERVER_SUFFIXES = (".ini", "_SandboxVars.lua", "_spawnregions.lua", "_spawnpoints.lua")
_DB_COMPANION_SUFFIXES_REL = ("-wal", "-shm", "-journal")


def list_backups(backup_root: Path) -> list[BackupEntry]:
    """Liste les backups disponibles, triés du plus récent au plus ancien.

    v0.4.0 FIX 5 : la détection des fichiers Server/DB ne hardcode plus
    f"{save_name}.<ext>" — elle scanne les patterns d'extension. Permet
    de reconnaître les fichiers avec espaces (ex: "Gitano Z.ini") que le
    fix v0.3.7 préserve maintenant.
    """
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
            kind=m.group("kind"),
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
            elif n.endswith(".db") and not any(
                n.endswith(".db" + sfx) for sfx in _DB_COMPANION_SUFFIXES_REL
            ):
                # Pour rétro-compat, on flag has_db si on trouve UN .db
                # principal. Le restore lira tout .db trouvé.
                be.has_db = True
            elif any(n.endswith(".db" + sfx) for sfx in _DB_COMPANION_SUFFIXES_REL):
                be.db_companions.append(n)
            elif any(n.endswith(sfx) for sfx in _SERVER_SUFFIXES):
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
    server_dir = root / "Server"
    db_dir = root / "db"

    # FIX 5 v0.4.0 — pre-restore et restore utilisent les fichiers REELLEMENT
    # présents (par scan d'extension), pas un nom hardcodé f"{save_name}.<ext>".
    # Permet de gérer les Server name avec espaces ("Gitano Z.ini").

    # --- 1. Pre-restore safety backup (de l'état actuel) ---
    cf_local = bundle_mod.discover_companion_files(save_name, root)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    pre = safety_backup_dir / f"pre_restore_{save_name}_{ts}"
    pre.mkdir(parents=True, exist_ok=True)
    if save_dir.exists():
        shutil.make_archive(str(pre / "save"), "zip", root_dir=save_dir)
    if cf_local.db is not None and cf_local.db.exists():
        shutil.copy2(cf_local.db, pre / cf_local.db.name)
    for comp in cf_local.db_companions:
        if comp.exists():
            shutil.copy2(comp, pre / comp.name)
    for srv in cf_local.server_files:
        if srv.exists():
            shutil.copy2(srv, pre / srv.name)

    # --- 2. Effacement de la save_dir actuelle + compagnons SQLite résiduels ---
    if save_dir.exists():
        shutil.rmtree(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    server_dir.mkdir(parents=True, exist_ok=True)
    db_dir.mkdir(parents=True, exist_ok=True)
    # Nettoyer les compagnons SQLite résiduels de l'ancien .db (peu importe son
    # prefix — on cherche tout .db-* dans db_dir matchant le cf_local.db).
    if cf_local.db is not None:
        for sfx in bundle_mod._DB_COMPANION_SUFFIXES:
            stale = cf_local.db.with_name(cf_local.db.name + sfx)
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

    # --- 4. Restauration db + compagnons (par scan d'extension, pas par nom) ---
    restored_db: Path | None = None
    restored_db_comps: list[Path] = []
    for f in backup.path.iterdir():
        if not f.is_file():
            continue
        n = f.name
        # DB principale : *.db sans suffixe -wal/-shm/-journal
        if n.endswith(".db") and not any(
            n.endswith(".db" + sfx) for sfx in bundle_mod._DB_COMPANION_SUFFIXES
        ):
            dst = db_dir / n
            shutil.copy2(f, dst)
            if restored_db is None:
                restored_db = dst
        # Compagnons SQLite
        elif any(n.endswith(".db" + sfx) for sfx in bundle_mod._DB_COMPANION_SUFFIXES):
            dst = db_dir / n
            shutil.copy2(f, dst)
            restored_db_comps.append(dst)

    # --- 5. Restauration fichiers Server (par scan d'extension) ---
    restored_server: list[Path] = []
    server_suffixes = (".ini", "_SandboxVars.lua", "_spawnregions.lua", "_spawnpoints.lua")
    for f in backup.path.iterdir():
        if not f.is_file():
            continue
        if any(f.name.endswith(sfx) for sfx in server_suffixes):
            dst = server_dir / f.name
            shutil.copy2(f, dst)
            restored_server.append(dst)

    return RestoreReport(
        save_name=save_name,
        save_dir=save_dir,
        db_path=restored_db,
        db_companions_restored=restored_db_comps,
        server_files=restored_server,
        pre_restore_backup=pre,
    )

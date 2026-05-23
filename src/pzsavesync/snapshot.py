"""Snapshot SHA256 d'une save_dir à l'instant T (post-import d'un bundle).

Utilisé par le mode différentiel (bundle v4) :
- À l'import d'un bundle FULL, on hash chaque fichier sous save_dir et on
  persiste un snapshot JSON dans ~/PZSaveSync/snapshots/.
- Au push retour, on charge ce snapshot, on rehash la save_dir actuelle,
  on diffe → seuls les fichiers added/modified partent dans le bundle DIFF.

Format stockage : APP_DIR/snapshots/<save_name>__<parent_sha_short12>.json
GC : on garde les N derniers par save + tous ceux < 30 jours.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from pzsavesync.config import APP_DIR
from pzsavesync.diff_errors import SnapshotCorruptError

__all__ = [
    "Snapshot", "SnapshotDiff", "SnapshotCorruptError",
    "compute_snapshot", "save_snapshot", "load_snapshot_for_parent",
    "find_latest_snapshot_for_save", "diff_against_snapshot",
    "cleanup_orphan_snapshots", "snapshot_path", "snapshots_dir",
    "SCHEMA_VERSION", "DEFAULT_MAX_AGE_DAYS", "DEFAULT_KEEP_RECENT",
]


SCHEMA_VERSION = 1
SNAPSHOTS_DIRNAME = "snapshots"
SHA_SHORT_LEN = 12
DEFAULT_MAX_AGE_DAYS = 180
DEFAULT_KEEP_RECENT = 5
RECENT_PROTECTION_DAYS = 30  # snapshots < 30j toujours gardés même au-delà de KEEP_RECENT
HASH_CHUNK_SIZE = 1024 * 1024  # 1 MB

# Callback de progression : (étape, courant, total) -> None
ProgressCb = Callable[[str, int, int], None]

_BAD_NAME_CHARS = re.compile(r'[<>:"/\\|?*]')


@dataclass
class Snapshot:
    """État SHA256 d'une save_dir post-import d'un bundle source."""
    schema_version: int = SCHEMA_VERSION
    save_name: str = ""
    parent_bundle_sha256: str = ""
    parent_bundle_filename: str = ""
    created_at: str = ""
    save_files: dict[str, str] = field(default_factory=dict)
    excluded_at_import: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SnapshotDiff:
    """Résultat de diff_against_snapshot."""
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    current_hashes: dict[str, str] = field(default_factory=dict)


def snapshots_dir() -> Path:
    return APP_DIR / SNAPSHOTS_DIRNAME


def _sha_short(parent_sha: str) -> str:
    cleaned = (parent_sha or "").strip().lower()
    if not cleaned:
        return "nosha"
    return cleaned[:SHA_SHORT_LEN]


def _safe_save_name_for_filename(save_name: str) -> str:
    """Remplace les caractères interdits pour un nom de fichier (Windows surtout)."""
    return _BAD_NAME_CHARS.sub("_", save_name or "unknown")


def snapshot_path(save_name: str, parent_sha: str) -> Path:
    fname = f"{_safe_save_name_for_filename(save_name)}__{_sha_short(parent_sha)}.json"
    return snapshots_dir() / fname


def _hash_file(path: Path) -> str:
    """SHA256 chunké d'un fichier."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(HASH_CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _walk_save_files(save_dir: Path) -> list[tuple[str, Path]]:
    """Liste tous les fichiers sous save_dir comme (rel_path POSIX, abs_path).

    On utilise POSIX (forward slashes) pour rester portable entre Windows et
    Linux : un snapshot créé sur Windows doit se charger sur Linux sans
    confusion de séparateurs.
    """
    out: list[tuple[str, Path]] = []
    for root, _dirs, files in os.walk(save_dir):
        root_p = Path(root)
        for fname in files:
            abs_p = root_p / fname
            rel = abs_p.relative_to(save_dir).as_posix()
            out.append((rel, abs_p))
    return out


def compute_snapshot(
    save_dir: Path,
    save_name: str,
    parent_sha: str,
    parent_filename: str = "",
    excluded_at_import: list[str] | None = None,
    progress: ProgressCb | None = None,
) -> Snapshot:
    """Walk save_dir et hash SHA256 chaque fichier.

    Raise FileNotFoundError si save_dir n'existe pas.
    """
    save_dir = Path(save_dir)
    if not save_dir.exists():
        raise FileNotFoundError(f"save_dir introuvable : {save_dir}")
    if not save_dir.is_dir():
        raise NotADirectoryError(f"save_dir n'est pas un dossier : {save_dir}")

    files = _walk_save_files(save_dir)
    total = len(files)
    hashes: dict[str, str] = {}
    for i, (rel, abs_p) in enumerate(files):
        try:
            hashes[rel] = _hash_file(abs_p)
        except (OSError, PermissionError):
            # Fichier disparu pendant le walk, ou accès refusé : on log via skip.
            # Le snapshot reste valide pour les fichiers qu'on a pu lire.
            continue
        if progress and (i % 128 == 0 or i == total - 1):
            progress("snapshot", i + 1, total)

    return Snapshot(
        schema_version=SCHEMA_VERSION,
        save_name=save_name,
        parent_bundle_sha256=parent_sha,
        parent_bundle_filename=parent_filename,
        created_at=dt.datetime.now().isoformat(timespec="seconds"),
        save_files=hashes,
        excluded_at_import=list(excluded_at_import or []),
    )


def save_snapshot(snap: Snapshot) -> Path:
    """Écrit le snapshot sur disque en atomique (.tmp + os.replace).

    Crée snapshots_dir() si nécessaire. Retourne le chemin final.
    """
    snapshots_dir().mkdir(parents=True, exist_ok=True)
    target = snapshot_path(snap.save_name, snap.parent_bundle_sha256)
    tmp = target.with_suffix(target.suffix + ".tmp")
    payload = json.dumps(snap.to_dict(), indent=2, ensure_ascii=False)
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, target)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target


def _load_snapshot_file(path: Path) -> Snapshot:
    """Charge un snapshot depuis un fichier. Raise SnapshotCorruptError si invalide."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise SnapshotCorruptError(f"Snapshot illisible {path}: {e}") from e

    if not isinstance(data, dict):
        raise SnapshotCorruptError(f"Snapshot {path} : racine n'est pas un objet JSON")

    known = set(Snapshot.__dataclass_fields__.keys())
    filtered = {k: v for k, v in data.items() if k in known}

    # Validation des champs critiques
    if not isinstance(filtered.get("save_files", {}), dict):
        raise SnapshotCorruptError(f"Snapshot {path} : save_files n'est pas un dict")
    if not isinstance(filtered.get("excluded_at_import", []), list):
        raise SnapshotCorruptError(f"Snapshot {path} : excluded_at_import n'est pas une liste")

    try:
        return Snapshot(**filtered)
    except TypeError as e:
        raise SnapshotCorruptError(f"Snapshot {path} : champs incompatibles : {e}") from e


def load_snapshot_for_parent(save_name: str, parent_sha: str) -> Snapshot | None:
    """Charge le snapshot exact correspondant à un parent_sha donné.

    Retourne None si introuvable. Raise SnapshotCorruptError si trouvé mais
    illisible (l'appelant peut fallback FULL).
    """
    path = snapshot_path(save_name, parent_sha)
    if not path.exists():
        return None
    return _load_snapshot_file(path)


def _list_snapshots_for_save(save_name: str) -> list[Path]:
    """Liste les fichiers de snapshot existants pour une save donnée."""
    d = snapshots_dir()
    if not d.exists():
        return []
    safe = _safe_save_name_for_filename(save_name)
    prefix = f"{safe}__"
    return [p for p in d.iterdir() if p.is_file() and p.name.startswith(prefix) and p.suffix == ".json"]


def find_latest_snapshot_for_save(save_name: str) -> Snapshot | None:
    """Le snapshot le plus récent (mtime) pour une save donnée, peu importe le parent_sha.

    Utile en fallback si on ne connaît pas le parent_sha (premier push après
    onboarding manuel). Ignore les fichiers corrompus.
    """
    candidates = _list_snapshots_for_save(save_name)
    if not candidates:
        return None
    # Tri par mtime décroissant
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for p in candidates:
        try:
            return _load_snapshot_file(p)
        except SnapshotCorruptError:
            continue
    return None


def diff_against_snapshot(
    snap: Snapshot,
    current_save_dir: Path,
    progress: ProgressCb | None = None,
) -> SnapshotDiff:
    """Compare l'état actuel de save_dir au snapshot.

    - added : présents maintenant mais pas dans le snapshot
    - modified : présents des 2 côtés mais hash différent
    - unchanged : présents des 2 côtés, hash identique
    - deleted : dans le snapshot mais plus présents
    - current_hashes : carte complète des hash actuels (sera l'expected_save_files
      du manifest diff côté client)
    """
    current_save_dir = Path(current_save_dir)
    if not current_save_dir.exists():
        raise FileNotFoundError(f"save_dir introuvable : {current_save_dir}")

    files = _walk_save_files(current_save_dir)
    total = len(files)
    current_hashes: dict[str, str] = {}

    for i, (rel, abs_p) in enumerate(files):
        try:
            current_hashes[rel] = _hash_file(abs_p)
        except (OSError, PermissionError):
            continue
        if progress and (i % 128 == 0 or i == total - 1):
            progress("diff", i + 1, total)

    snap_files = snap.save_files
    snap_keys = set(snap_files.keys())
    current_keys = set(current_hashes.keys())

    added = sorted(current_keys - snap_keys)
    deleted = sorted(snap_keys - current_keys)
    both = current_keys & snap_keys

    modified: list[str] = []
    unchanged: list[str] = []
    for k in sorted(both):
        if current_hashes[k] != snap_files[k]:
            modified.append(k)
        else:
            unchanged.append(k)

    return SnapshotDiff(
        added=added,
        modified=modified,
        unchanged=unchanged,
        deleted=deleted,
        current_hashes=current_hashes,
    )


def cleanup_orphan_snapshots(
    save_name: str | None = None,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    keep_n_recent: int = DEFAULT_KEEP_RECENT,
) -> list[Path]:
    """Supprime les snapshots trop vieux ou en surplus.

    Règles (par save_name groupé) :
    - Garde toujours les `keep_n_recent` plus récents
    - Garde toujours ceux modifiés depuis moins de RECENT_PROTECTION_DAYS jours
    - Supprime ceux > max_age_days qui ne sont pas protégés ci-dessus
    - Garantit qu'il reste toujours au moins 1 snapshot par save (le plus récent)

    Si `save_name` est None, applique à toutes les saves trouvées dans le dossier.
    Retourne la liste des chemins supprimés.
    """
    d = snapshots_dir()
    if not d.exists():
        return []

    # Group by save_name (extrait du nom de fichier <save>__<sha>.json)
    groups: dict[str, list[Path]] = {}
    for p in d.iterdir():
        if not p.is_file() or p.suffix != ".json":
            continue
        name = p.stem  # <save>__<sha>
        if "__" not in name:
            continue
        sname = name.split("__", 1)[0]
        if save_name is not None and sname != _safe_save_name_for_filename(save_name):
            continue
        groups.setdefault(sname, []).append(p)

    deleted: list[Path] = []
    now = dt.datetime.now().timestamp()
    recent_cutoff = now - (RECENT_PROTECTION_DAYS * 86400)
    age_cutoff = now - (max_age_days * 86400)

    for _sname, paths in groups.items():
        # Tri du plus récent au plus ancien
        paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        # Le plus récent par save est toujours protégé
        if not paths:
            continue
        protected: set[Path] = {paths[0]}
        # Les N plus récents protégés
        for p in paths[:keep_n_recent]:
            protected.add(p)
        # Et ceux < RECENT_PROTECTION_DAYS
        for p in paths:
            if p.stat().st_mtime >= recent_cutoff:
                protected.add(p)

        # Suppression de tout le reste qui est aussi plus vieux que max_age_days
        for p in paths:
            if p in protected:
                continue
            if p.stat().st_mtime < age_cutoff:
                try:
                    p.unlink()
                    deleted.append(p)
                except OSError:
                    continue

    return deleted

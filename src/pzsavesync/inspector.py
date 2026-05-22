"""Inspection d'une save PZ (locale ou extraite d'un zip)."""
from __future__ import annotations

import datetime as dt
import re
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


# Sécurité : limites pour l'inspection de zips tiers (anti zip-bomb à l'inspection).
# Mêmes ordres de grandeur que extract_bundle mais on tolère plus de fichiers
# pour les saves multi très explorées.
_INSPECT_MAX_FILES = 500_000
_INSPECT_MAX_UNCOMPRESSED = 20 * 1024 * 1024 * 1024  # 20 GB
_INSPECT_MAX_DB_SIZE = 200 * 1024 * 1024  # 200 MB pour extraire la .db en mémoire


@dataclass
class SaveInfo:
    path: str
    exists: bool
    kind: str = "unknown"                 # server_save | client_save | server_config | unknown
    last_played: str | None = None        # ISO timestamp (mtime du fichier le plus récent)
    total_size_bytes: int = 0
    file_count: int = 0
    map_chunks: int = 0                   # nb de map_*.bin (zone explorée)
    chunkdata_files: int = 0              # nb de chunkdata_*.bin (state monde)
    structures: int = 0                   # nb de gos_*.bin (constructions/feux/etc)
    players: list[str] = field(default_factory=list)
    players_source: str = ""              # "db" | "folder_name" | ""
    notes: list[str] = field(default_factory=list)

    @property
    def size_mb(self) -> float:
        return self.total_size_bytes / (1024 * 1024)


def inspect_save(path: Path, zomboid_root: Path | None = None) -> SaveInfo:
    """Inspecte un dossier de save (Multiplayer ou Server)."""
    info = SaveInfo(path=str(path), exists=path.exists())
    if not info.exists:
        return info

    latest_mtime = 0.0
    for f in path.rglob("*"):
        if not f.is_file():
            continue
        info.file_count += 1
        try:
            stat = f.stat()
        except OSError:
            continue
        info.total_size_bytes += stat.st_size
        latest_mtime = max(latest_mtime, stat.st_mtime)

        name = f.name
        if name.startswith("map_") and name.endswith(".bin"):
            info.map_chunks += 1
        elif name.startswith("chunkdata_") and name.endswith(".bin"):
            info.chunkdata_files += 1
        elif name.startswith("gos_") and name.endswith(".bin"):
            info.structures += 1

    if latest_mtime:
        info.last_played = dt.datetime.fromtimestamp(latest_mtime).isoformat(timespec="seconds")

    # Détermine la nature de la save
    parent_name = path.name
    m = re.match(r"^(?P<steamid>\d{17})_(?P<pseudo>.+?)_player$", parent_name)
    if m:
        info.kind = "client_save"
        info.players = [m.group("pseudo")]
        info.players_source = "folder_name"
    elif parent_name.lower() == "server":
        info.kind = "server_config"
    elif info.chunkdata_files > 0 or info.map_chunks > 50:
        info.kind = "server_save"

    # Tente de lire la db SQLite associée
    if info.kind == "server_save":
        players = _read_players_from_db(path.name, zomboid_root)
        if players:
            info.players = sorted(set(info.players) | set(players))
            info.players_source = "db"
        else:
            info.notes.append(
                f"DB '{path.name}.db' introuvable ou vide — joueurs non listés."
            )

    return info


def _read_players_from_db(save_name: str, zomboid_root: Path | None) -> list[str]:
    """Lit les noms de joueurs depuis Zomboid/db/<save_name>.db si dispo."""
    if zomboid_root is None:
        # Honore $PZ_ZOMBOID_ROOT (cross-platform Win/Linux/Mac)
        import os as _os
        override = _os.environ.get("PZ_ZOMBOID_ROOT")
        zomboid_root = Path(override) if override else (Path.home() / "Zomboid")
    db_path = zomboid_root / "db" / f"{save_name}.db"
    return _read_players_from_db_file(db_path)


def inspect_zip(zip_path: Path) -> SaveInfo:
    """Inspecte une archive .zip sans la décompresser entièrement.

    Sécurité :
    - Garde-fous anti zip-bomb : refuse `> _INSPECT_MAX_FILES` ou
      décompressé `> _INSPECT_MAX_UNCOMPRESSED`. On inspecte des .zip
      reçus de tiers (Inspecter un .zip dans la GUI), donc on ne fait
      JAMAIS confiance à la taille déclarée par l'archive.
    - Pas de `extractall()` : on lit le manifest et la DB (si présente)
      via les API en streaming de zipfile. Le zip-slip n'est plus possible
      puisque rien n'est écrit en dehors d'un fichier .db temporaire dont
      on contrôle le nom.

    Performance : avant, une inspection d'un bundle de 500 MB extrayait
    tout le zip sur le disque temporaire. Maintenant on lit juste les
    métadonnées (manifest + infolist) + éventuellement la DB.
    """
    import json as _json
    info = SaveInfo(path=str(zip_path), exists=False)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            infos = zf.infolist()
            # Anti zip-bomb : refuser un zip aberrant
            if len(infos) > _INSPECT_MAX_FILES:
                info.notes.append(
                    f"Zip suspect : {len(infos)} fichiers (max {_INSPECT_MAX_FILES})."
                )
                return info
            total_uncompressed = sum(i.file_size for i in infos)
            if total_uncompressed > _INSPECT_MAX_UNCOMPRESSED:
                info.notes.append(
                    f"Zip suspect : décompressé {total_uncompressed/1024**3:.1f} GB > "
                    f"{_INSPECT_MAX_UNCOMPRESSED/1024**3:.0f} GB."
                )
                return info

            info.exists = True
            names = [i.filename for i in infos]
            name_set = set(names)
            is_bundle = "bundle_manifest.json" in name_set
            save_name = ""
            if is_bundle:
                try:
                    with zf.open("bundle_manifest.json") as fp:
                        manifest_data = _json.loads(fp.read().decode("utf-8"))
                        save_name = str(manifest_data.get("save_name", ""))
                except Exception:
                    save_name = ""

            # Comptage en streaming sur les noms + tailles, sans extraction
            latest_mtime = 0.0
            for i in infos:
                if i.is_dir():
                    continue
                info.file_count += 1
                info.total_size_bytes += i.file_size
                # zipinfo.date_time = (Y, m, d, H, M, S)
                try:
                    dt_tuple = i.date_time
                    if dt_tuple and dt_tuple[0] >= 1980:
                        mtime = dt.datetime(*dt_tuple).timestamp()
                        latest_mtime = max(latest_mtime, mtime)
                except (ValueError, TypeError):
                    pass
                base = i.filename.rsplit("/", 1)[-1]
                if base.startswith("map_") and base.endswith(".bin"):
                    info.map_chunks += 1
                elif base.startswith("chunkdata_") and base.endswith(".bin"):
                    info.chunkdata_files += 1
                elif base.startswith("gos_") and base.endswith(".bin"):
                    info.structures += 1

            if latest_mtime:
                info.last_played = dt.datetime.fromtimestamp(latest_mtime).isoformat(timespec="seconds")

            # Type de save
            if is_bundle:
                info.kind = "server_save"
                info.path = f"(bundle) {zip_path.name} [save={save_name or '?'}]"
                # Joueurs depuis la DB embarquée — extraction ciblée + bornée
                db_member = f"db/{save_name}.db" if save_name else None
                if db_member and db_member in name_set:
                    db_info = zf.getinfo(db_member)
                    if db_info.file_size <= _INSPECT_MAX_DB_SIZE:
                        players = _read_players_from_zip_db(zf, db_member, save_name)
                        if players:
                            info.players = players
                            info.players_source = "db"
                    else:
                        info.notes.append(
                            f"DB du bundle trop grosse ({db_info.file_size/1024/1024:.0f} MB) — "
                            f"joueurs non listés."
                        )
            elif info.chunkdata_files > 0 or info.map_chunks > 50:
                info.kind = "server_save"
                info.path = f"(zip) {zip_path.name}"
            else:
                info.path = f"(zip) {zip_path.name}"

            return info
    except zipfile.BadZipFile as e:
        info.notes.append(f"Zip illisible : {e}")
        return info
    except OSError as e:
        info.notes.append(f"Lecture impossible : {e}")
        return info


def _read_players_from_zip_db(zf: zipfile.ZipFile, member: str, save_name: str) -> list[str]:
    """Extrait la .db du bundle en sécurité et lit les joueurs.

    On extrait dans un fichier temporaire à NOM CONTRÔLÉ (pas dérivé du zip),
    ce qui élimine zip-slip de manière structurelle.
    """
    with tempfile.TemporaryDirectory() as tmp:
        db_target = Path(tmp) / "embedded.db"
        try:
            with zf.open(member) as src, open(db_target, "wb") as dst:
                # Copie bornée : si jamais ZipInfo.file_size mentait, on bloque à _INSPECT_MAX_DB_SIZE
                remaining = _INSPECT_MAX_DB_SIZE
                while remaining > 0:
                    chunk = src.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    dst.write(chunk)
                    remaining -= len(chunk)
        except (OSError, zipfile.BadZipFile):
            return []
        return _read_players_from_db_file(db_target)


def _read_players_from_db_file(db_path: Path) -> list[str]:
    """Lit les joueurs depuis un fichier .db SQLite (chemin absolu connu)."""
    if not db_path.exists():
        return []
    try:
        uri = f"file:{db_path}?mode=ro"
        con = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return []
    try:
        cur = con.cursor()
        try:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0].lower() for row in cur.fetchall()}
        except sqlite3.Error:
            return []
        names: set[str] = set()
        for table, col in [
            ("networkplayers", "username"),
            ("networkplayers", "name"),
            ("players", "username"),
            ("players", "name"),
            ("whitelist", "username"),
            ("whitelist", "name"),
        ]:
            if table not in tables:
                continue
            try:
                cur.execute(f"SELECT DISTINCT {col} FROM {table}")
                for row in cur.fetchall():
                    if row[0]:
                        names.add(str(row[0]))
            except sqlite3.Error:
                continue
            if names:
                break
        return sorted(names)
    finally:
        con.close()


def format_info(info: SaveInfo, title: str = "") -> str:
    if not info.exists:
        return f"{title}\n  (n'existe pas : {info.path})"
    lines = [title] if title else []
    lines.append(f"  Chemin        : {info.path}")
    lines.append(f"  Type          : {info.kind}")
    lines.append(f"  Dernier jeu   : {info.last_played or '-'}")
    lines.append(f"  Taille        : {info.size_mb:.1f} MB ({info.file_count} fichiers)")
    lines.append(f"  Chunks (map_) : {info.map_chunks}")
    lines.append(f"  Chunkdata     : {info.chunkdata_files}")
    lines.append(f"  Structures    : {info.structures}")
    src = f" [source: {info.players_source}]" if info.players_source else ""
    lines.append(f"  Joueurs       : {', '.join(info.players) if info.players else '(aucun)'}{src}")
    for n in info.notes:
        lines.append(f"  ! {n}")
    return "\n".join(lines)


def diff(local: SaveInfo, remote: SaveInfo) -> str:
    lines = ["Diff (local → remote)"]
    if not local.exists:
        lines.append("  Local : (inexistant)")
    if not remote.exists:
        lines.append("  Remote: (inexistant)")
    if not (local.exists and remote.exists):
        return "\n".join(lines)

    def _delta(a, b, unit=""):
        d = b - a
        sign = "+" if d >= 0 else "-"
        return f"{a} → {b} ({sign}{abs(d)}{unit})"

    def _delta_mb(a, b):
        d = b - a
        sign = "+" if d >= 0 else "-"
        return f"{a/1024/1024:.1f} → {b/1024/1024:.1f} MB ({sign}{abs(d)/1024/1024:.1f})"

    lines.append(f"  Taille        : {_delta_mb(local.total_size_bytes, remote.total_size_bytes)}")
    lines.append(f"  Fichiers      : {_delta(local.file_count, remote.file_count)}")
    lines.append(f"  Chunks (map_) : {_delta(local.map_chunks, remote.map_chunks)}")
    lines.append(f"  Chunkdata     : {_delta(local.chunkdata_files, remote.chunkdata_files)}")
    lines.append(f"  Structures    : {_delta(local.structures, remote.structures)}")
    lines.append(f"  Dernier jeu   : {local.last_played} → {remote.last_played}")

    added = sorted(set(remote.players) - set(local.players))
    removed = sorted(set(local.players) - set(remote.players))
    common = sorted(set(local.players) & set(remote.players))
    lines.append(f"  Joueurs communs  : {', '.join(common) or '-'}")
    lines.append(f"  Nouveaux (remote): {', '.join(added) or '-'}")
    lines.append(f"  Disparus (remote): {', '.join(removed) or '-'}")
    return "\n".join(lines)

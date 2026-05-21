"""Inspection d'une save PZ (locale ou extraite d'un zip)."""
from __future__ import annotations

import datetime as dt
import re
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


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
        zomboid_root = Path.home() / "Zomboid"
    db_path = zomboid_root / "db" / f"{save_name}.db"
    if not db_path.exists():
        return []
    try:
        # Ouvrir en read-only pour éviter tout lock side-effect.
        uri = f"file:{db_path}?mode=ro"
        con = sqlite3.connect(uri, uri=True)
        try:
            cur = con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0].lower() for row in cur.fetchall()}
            names: set[str] = set()
            # PZ stocke généralement les joueurs dans une table "networkPlayers" ou "players".
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
    except sqlite3.Error:
        return []


def inspect_zip(zip_path: Path) -> SaveInfo:
    """Inspecte une archive .zip (bundle PZSaveSync ou simple zip de save)."""
    import json as _json
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp)
        root = Path(tmp)

        # Bundle PZSaveSync : structure save/ db/<save>.db server/ + manifest
        manifest_path = root / "bundle_manifest.json"
        if manifest_path.exists():
            try:
                data = _json.loads(manifest_path.read_text(encoding="utf-8"))
                save_name = data.get("save_name", "")
            except Exception:
                save_name = ""
            save_subdir = root / "save"
            target = save_subdir if save_subdir.exists() else root
            # Recopie temporairement la db sous Zomboid-root/db/<save_name>.db
            # pour que _read_players_from_db la trouve via le pattern attendu.
            if save_name:
                db_in_zip = root / "db" / f"{save_name}.db"
                if db_in_zip.exists():
                    fake_root_db = root / "db" / f"{save_name}.db"
                    fake_root_db.parent.mkdir(parents=True, exist_ok=True)
                    # déjà au bon endroit
                info = inspect_save(target, zomboid_root=root)
                info.path = f"(bundle) {zip_path.name} [save={save_name}]"
                # Si le nom du dossier extrait n'est pas <save_name>, l'inspector
                # n'a pas pu déduire le save_name pour chercher la db. On le fait ici.
                if not info.players and (root / "db" / f"{save_name}.db").exists():
                    info.players = _read_players_from_db(save_name, zomboid_root=root)
                    if info.players:
                        info.players_source = "db"
                return info

        # Zip "brut" (ancien format) — fallback
        children = [c for c in root.iterdir() if c.is_dir()]
        target = children[0] if len(children) == 1 else root
        info = inspect_save(target, zomboid_root=root)
        info.path = f"(zip) {zip_path.name}"
        return info


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

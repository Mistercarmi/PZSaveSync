"""Push/pull versionné d'un BUNDLE PZ (save+db+config) vers un dossier partagé."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from pzsavesync import bundle as bundle_mod

VERSIONS_DIRNAME = "versions"
LOCK_FILENAME = "lock.json"
MANIFEST_FILENAME = "manifest.json"
_REQUIRED_LOCK_FIELDS = ("holder", "taken_at")


def _atomic_write_text(path: Path, content: str) -> None:
    """Écrit du texte dans un fichier de manière atomique (tmp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


@dataclass
class Lock:
    holder: str
    taken_at: str
    note: str = ""

    def to_dict(self) -> dict:
        return {"holder": self.holder, "taken_at": self.taken_at, "note": self.note}


@dataclass
class Version:
    filename: str
    save_name: str
    uploaded_by: str
    uploaded_at: str
    size_bytes: int
    has_db: bool = False
    server_files: list[str] | None = None
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "save_name": self.save_name,
            "uploaded_by": self.uploaded_by,
            "uploaded_at": self.uploaded_at,
            "size_bytes": self.size_bytes,
            "has_db": self.has_db,
            "server_files": self.server_files or [],
            "note": self.note,
        }


class SharedRepo:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.versions_dir = self.root / VERSIONS_DIRNAME
        self.lock_path = self.root / LOCK_FILENAME
        self.manifest_path = self.root / MANIFEST_FILENAME

    def init_if_needed(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        if not self.manifest_path.exists():
            self._write_manifest({"versions": []})

    def _write_manifest(self, data: dict) -> None:
        _atomic_write_text(self.manifest_path, json.dumps(data, indent=2))

    # ---------- lock ----------
    def get_lock(self) -> Lock | None:
        if not self.lock_path.exists():
            return None
        try:
            data = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"[sync] lock.json illisible : {e}", file=sys.stderr)
            return None
        if not isinstance(data, dict):
            print("[sync] lock.json invalide (pas un objet)", file=sys.stderr)
            return None
        missing = [k for k in _REQUIRED_LOCK_FIELDS if k not in data]
        if missing:
            print(f"[sync] lock.json incomplet, champs manquants : {missing}", file=sys.stderr)
            return None
        known = set(Lock.__dataclass_fields__.keys())
        try:
            return Lock(**{k: v for k, v in data.items() if k in known})
        except TypeError as e:
            print(f"[sync] lock.json mal typé : {e}", file=sys.stderr)
            return None

    def take_lock(self, holder: str, note: str = "", force: bool = False) -> Lock:
        existing = self.get_lock()
        if existing and existing.holder != holder and not force:
            raise RuntimeError(
                f"Le tour est déjà pris par {existing.holder} depuis {existing.taken_at}."
            )
        lock = Lock(
            holder=holder,
            taken_at=dt.datetime.now().isoformat(timespec="seconds"),
            note=note,
        )
        _atomic_write_text(self.lock_path, json.dumps(lock.to_dict(), indent=2))
        return lock

    def release_lock(self, holder: str, force: bool = False) -> None:
        existing = self.get_lock()
        if existing is None:
            return
        if existing.holder != holder and not force:
            raise RuntimeError(
                f"Tu ne peux pas libérer le verrou de {existing.holder}."
            )
        self.lock_path.unlink(missing_ok=True)

    # ---------- versions ----------
    def list_versions(self) -> list[Version]:
        manifest = self._read_manifest()
        out: list[Version] = []
        for v in manifest.get("versions", []):
            # Compat anciens manifestes
            v = dict(v)
            v.setdefault("save_name", "")
            v.setdefault("has_db", False)
            v.setdefault("server_files", [])
            out.append(Version(**v))
        return out

    def latest_version(self) -> Version | None:
        versions = self.list_versions()
        return versions[-1] if versions else None

    def push_bundle(
        self, save_name: str, uploaded_by: str, note: str = "",
    ) -> Version:
        """Crée un bundle complet (save+db+config) et le pousse dans le dossier partagé."""
        self.init_if_needed()
        ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_user = "".join(c for c in uploaded_by if c.isalnum() or c in "-_") or "anon"
        safe_save = "".join(c for c in save_name if c.isalnum() or c in "-_") or "save"
        filename = f"bundle_{safe_save}_{ts}_{safe_user}.zip"
        target = self.versions_dir / filename

        manifest = bundle_mod.build_bundle(
            save_name=save_name,
            out_zip=target,
            created_by=uploaded_by,
            note=note,
        )

        version = Version(
            filename=filename,
            save_name=save_name,
            uploaded_by=uploaded_by,
            uploaded_at=manifest.created_at,
            size_bytes=target.stat().st_size,
            has_db=manifest.has_db,
            server_files=manifest.server_files,
            note=note,
        )
        data = self._read_manifest()
        data.setdefault("versions", []).append(version.to_dict())
        self._write_manifest(data)
        return version

    def pull_bundle(self, version: Version, backup_dir: Path):
        """Restaure le bundle d'une version. Backup automatique de l'existant."""
        archive = self.versions_dir / version.filename
        if not archive.exists():
            raise FileNotFoundError(f"Archive manquante : {archive}")
        return bundle_mod.extract_bundle(archive, backup_dir=backup_dir)

    # ---------- manifest ----------
    def _read_manifest(self) -> dict:
        if not self.manifest_path.exists():
            return {"versions": []}
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

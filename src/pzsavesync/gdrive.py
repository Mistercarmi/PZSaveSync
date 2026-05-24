"""Accès Google Drive via l'API officielle (OAuth2 Desktop flow).

Architecture :
- GDriveClient : wrapper bas niveau (auth + CRUD fichiers/dossiers Drive)
- GDriveRepo   : même interface que SharedRepo, stocke tout sur Drive

Credentials :
  L'utilisateur crée un projet Google Cloud, active l'API Drive, télécharge
  credentials.json (type "Desktop app") et le place dans APP_DIR.
  Au premier push/pull, le navigateur s'ouvre pour le consentement OAuth2.
  Le token est ensuite persisté dans APP_DIR/gdrive_token.json.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import logging
import re
import sys
import tempfile
from pathlib import Path
from typing import Callable

_log = logging.getLogger(__name__)

try:
    from google.oauth2.credentials import Credentials as _Credentials
    from google.auth.transport.requests import Request as _Request
    from google_auth_oauthlib.flow import InstalledAppFlow as _InstalledAppFlow
    from googleapiclient.discovery import build as _build_service
    from googleapiclient.http import (
        MediaIoBaseUpload as _MediaIoBaseUpload,
        MediaFileUpload as _MediaFileUpload,
        MediaIoBaseDownload as _MediaIoBaseDownload,
    )
    _GDRIVE_AVAILABLE = True
except ImportError:
    _GDRIVE_AVAILABLE = False


SCOPES = ["https://www.googleapis.com/auth/drive"]
CREDS_FILENAME = "gdrive_credentials.json"
TOKEN_FILENAME = "gdrive_token.json"
MIME_JSON = "application/json"
MIME_ZIP = "application/zip"
MIME_FOLDER = "application/vnd.google-apps.folder"
VERSIONS_FOLDER_NAME = "versions"
MANIFEST_FILENAME = "manifest.json"
LOCK_FILENAME = "lock.json"
_REQUIRED_LOCK_FIELDS = ("holder", "taken_at")


def _require_gdrive() -> None:
    if not _GDRIVE_AVAILABLE:
        raise ImportError(
            "Librairies Google Drive non installées.\n"
            "Lance : pip install google-api-python-client google-auth-oauthlib"
        )


def parse_folder_id(url_or_id: str) -> str:
    """Extrait l'ID de dossier Drive depuis une URL ou retourne l'input si déjà un ID."""
    url_or_id = url_or_id.strip()
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", url_or_id)
    if m:
        return m.group(1)
    if re.match(r"^[a-zA-Z0-9_-]{20,}$", url_or_id):
        return url_or_id
    raise ValueError(
        f"URL Google Drive invalide : {url_or_id!r}\n"
        "Format attendu : https://drive.google.com/drive/folders/FOLDER_ID"
    )


class GDriveAuthError(Exception):
    """Credentials introuvables, invalides ou flow OAuth2 annulé."""


class GDriveClient:
    """Wrapper bas niveau autour de l'API Google Drive v3."""

    def __init__(self, app_dir: Path):
        self._app_dir = Path(app_dir)
        self._creds_path = self._app_dir / CREDS_FILENAME
        self._token_path = self._app_dir / TOKEN_FILENAME
        self._service = None

    # ------------------------------------------------------------------ auth

    def is_authenticated(self) -> bool:
        """Vrai si un token valide ou rafraîchissable existe."""
        if not _GDRIVE_AVAILABLE or not self._token_path.exists():
            return False
        try:
            creds = _Credentials.from_authorized_user_file(str(self._token_path), SCOPES)
            return bool(creds and (creds.valid or (creds.expired and creds.refresh_token)))
        except Exception:
            return False

    def has_credentials_file(self) -> bool:
        return self._creds_path.exists()

    def authenticate(self) -> None:
        """Lance le flow OAuth2 (ouvre le navigateur si nécessaire). Persiste le token."""
        _require_gdrive()

        creds = None
        if self._token_path.exists():
            try:
                creds = _Credentials.from_authorized_user_file(str(self._token_path), SCOPES)
            except Exception:
                creds = None

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(_Request())
            except Exception:
                creds = None

        if not creds or not creds.valid:
            if not self._creds_path.exists():
                raise GDriveAuthError(
                    f"Fichier d'identifiants Google introuvable :\n  {self._creds_path}\n\n"
                    "Pour créer ce fichier :\n"
                    "  1. Va sur console.cloud.google.com\n"
                    "  2. Crée un projet → Active l'API Google Drive\n"
                    "  3. Credentials → + Create Credentials → OAuth 2.0 Client → Desktop App\n"
                    "  4. Télécharge le JSON et renomme-le « gdrive_credentials.json »\n"
                    f"  5. Place-le dans : {self._app_dir}"
                )
            flow = _InstalledAppFlow.from_client_secrets_file(str(self._creds_path), SCOPES)
            creds = flow.run_local_server(port=0)

        self._app_dir.mkdir(parents=True, exist_ok=True)
        self._token_path.write_text(creds.to_json(), encoding="utf-8")
        self._service = _build_service("drive", "v3", credentials=creds)

    def revoke(self) -> None:
        """Révoque le token local (déconnexion)."""
        self._token_path.unlink(missing_ok=True)
        self._service = None

    def _svc(self):
        """Retourne le service Drive (s'authentifie si besoin)."""
        if self._service is None:
            self.authenticate()
        return self._service

    # ---------------------------------------------------------------- CRUD

    def find_file(self, parent_id: str, name: str) -> dict | None:
        name_esc = name.replace("'", "\\'")
        q = f"'{parent_id}' in parents and name = '{name_esc}' and trashed = false"
        result = self._svc().files().list(
            q=q, fields="files(id,name,size)", pageSize=5,
        ).execute()
        files = result.get("files", [])
        return files[0] if files else None

    def list_files(self, parent_id: str) -> list[dict]:
        files: list[dict] = []
        page_token = None
        while True:
            kw: dict = dict(
                q=f"'{parent_id}' in parents and trashed = false",
                fields="nextPageToken,files(id,name,size,mimeType)",
                pageSize=100,
            )
            if page_token:
                kw["pageToken"] = page_token
            result = self._svc().files().list(**kw).execute()
            files.extend(result.get("files", []))
            page_token = result.get("nextPageToken")
            if not page_token:
                break
        return files

    def find_or_create_folder(self, parent_id: str, name: str) -> str:
        name_esc = name.replace("'", "\\'")
        q = (
            f"'{parent_id}' in parents and name = '{name_esc}' "
            f"and mimeType = '{MIME_FOLDER}' and trashed = false"
        )
        result = self._svc().files().list(q=q, fields="files(id)").execute()
        existing = result.get("files", [])
        if existing:
            return existing[0]["id"]
        meta = {"name": name, "mimeType": MIME_FOLDER, "parents": [parent_id]}
        f = self._svc().files().create(body=meta, fields="id").execute()
        return f["id"]

    def read_json(self, parent_id: str, name: str) -> dict | None:
        f = self.find_file(parent_id, name)
        if f is None:
            return None
        buf = io.BytesIO()
        req = self._svc().files().get_media(fileId=f["id"])
        dl = _MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
        try:
            return json.loads(buf.getvalue().decode("utf-8"))
        except Exception:
            return None

    def write_json(self, parent_id: str, name: str, data: dict) -> str:
        payload = json.dumps(data, indent=2).encode("utf-8")
        existing = self.find_file(parent_id, name)
        media = _MediaIoBaseUpload(io.BytesIO(payload), mimetype=MIME_JSON, resumable=False)
        if existing:
            self._svc().files().update(fileId=existing["id"], media_body=media).execute()
            return existing["id"]
        meta = {"name": name, "parents": [parent_id]}
        f = self._svc().files().create(body=meta, media_body=media, fields="id").execute()
        return f["id"]

    def delete_file_by_id(self, file_id: str) -> None:
        try:
            self._svc().files().delete(fileId=file_id).execute()
        except Exception as e:
            _log.warning("delete Drive file %s : %s", file_id, e)

    def upload_file(
        self,
        parent_id: str,
        name: str,
        path: Path,
        mimetype: str = MIME_ZIP,
        progress_cb: Callable[[int, int], None] | None = None,
    ) -> str:
        size = path.stat().st_size
        meta = {"name": name, "parents": [parent_id]}
        media = _MediaFileUpload(
            str(path), mimetype=mimetype, resumable=True, chunksize=4 * 1024 * 1024,
        )
        req = self._svc().files().create(body=meta, media_body=media, fields="id")
        resp = None
        while resp is None:
            status, resp = req.next_chunk()
            if status and progress_cb:
                progress_cb(int(status.resumable_progress), size)
        if progress_cb:
            progress_cb(size, size)
        return resp["id"]

    def download_file(
        self,
        file_id: str,
        dest_path: Path,
        progress_cb: Callable[[int, int], None] | None = None,
    ) -> None:
        req = self._svc().files().get_media(fileId=file_id)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as fh:
            dl = _MediaIoBaseDownload(fh, req, chunksize=4 * 1024 * 1024)
            done = False
            while not done:
                status, done = dl.next_chunk()
                if status and progress_cb:
                    progress_cb(
                        int(status.resumable_progress),
                        int(status.total_size or 0),
                    )

    def get_folder_name(self, folder_id: str) -> str:
        try:
            f = self._svc().files().get(fileId=folder_id, fields="name").execute()
            return f.get("name", folder_id)
        except Exception:
            return folder_id


# ============================================================ GDriveRepo

class GDriveRepo:
    """Même interface que SharedRepo mais tous les fichiers sont sur Google Drive.

    Le dossier Drive pointe par son ID (extrait de l'URL partagée).
    Structure sur Drive :
        <dossier_partage>/
        ├── manifest.json
        ├── lock.json
        └── versions/
            └── bundle_*.zip
    """

    def __init__(self, folder_id: str, client: GDriveClient):
        self._folder_id = folder_id
        self._client = client
        self._versions_folder_id: str | None = None

    @property
    def _versions_id(self) -> str:
        if self._versions_folder_id is None:
            self._versions_folder_id = self._client.find_or_create_folder(
                self._folder_id, VERSIONS_FOLDER_NAME,
            )
        return self._versions_folder_id

    def init_if_needed(self) -> None:
        _ = self._versions_id
        if self._client.read_json(self._folder_id, MANIFEST_FILENAME) is None:
            self._write_manifest({"versions": []})

    def _read_manifest(self) -> dict:
        data = self._client.read_json(self._folder_id, MANIFEST_FILENAME)
        if not isinstance(data, dict):
            return {"versions": []}
        if not isinstance(data.get("versions"), list):
            data["versions"] = []
        return data

    def _write_manifest(self, data: dict) -> None:
        self._client.write_json(self._folder_id, MANIFEST_FILENAME, data)

    # ---------- lock ----------

    def get_lock(self):
        from pzsavesync.sync import Lock  # late import to avoid circular
        data = self._client.read_json(self._folder_id, LOCK_FILENAME)
        if not isinstance(data, dict):
            return None
        missing = [k for k in _REQUIRED_LOCK_FIELDS if k not in data]
        if missing:
            return None
        known = set(Lock.__dataclass_fields__.keys())
        try:
            return Lock(**{k: v for k, v in data.items() if k in known})
        except TypeError:
            return None

    def take_lock(self, holder: str, note: str = "", force: bool = False):
        from pzsavesync.sync import Lock
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
        self._client.write_json(self._folder_id, LOCK_FILENAME, lock.to_dict())
        return lock

    def release_lock(self, holder: str, force: bool = False) -> None:
        existing = self.get_lock()
        if existing is None:
            return
        if existing.holder != holder and not force:
            raise RuntimeError(f"Tu ne peux pas libérer le verrou de {existing.holder}.")
        f = self._client.find_file(self._folder_id, LOCK_FILENAME)
        if f:
            self._client.delete_file_by_id(f["id"])

    # ---------- versions ----------

    def list_versions(self) -> list:
        from pzsavesync.sync import Version
        manifest = self._read_manifest()
        known = set(Version.__dataclass_fields__.keys())
        out = []
        for v in manifest.get("versions", []):
            v = dict(v)
            v.setdefault("save_name", "")
            v.setdefault("has_db", False)
            v.setdefault("server_files", [])
            v.setdefault("bundle_mode", "full")
            v.setdefault("parent_bundle_sha256", "")
            v.setdefault("full_size_estimate_bytes", 0)
            filtered = {k: val for k, val in v.items() if k in known}
            out.append(Version(**filtered))
        return out

    def latest_version(self):
        versions = self.list_versions()
        return versions[-1] if versions else None

    def total_size_bytes(self) -> int:
        return sum(v.size_bytes for v in self.list_versions())

    # ---------- push ----------

    def _resolve_mode_and_snapshot(self, save_name: str, requested_mode):
        """Détermine le mode effectif + snapshot parent (version Drive du _resolve sync.py)."""
        from pzsavesync import snapshot as snapshot_mod
        from pzsavesync.bundle import BundleMode
        from pzsavesync.diff_errors import NoSnapshotAvailableError, ParentBundleSHAmismatchError

        if requested_mode == BundleMode.FULL:
            return BundleMode.FULL, None

        try:
            snap = snapshot_mod.find_latest_snapshot_for_save(save_name)
        except Exception as e:
            _log.warning("Lecture snapshot échouée (%s) — fallback FULL", e)
            snap = None

        if snap is None:
            if requested_mode == BundleMode.DIFF:
                raise NoSnapshotAvailableError(
                    f"Pas de snapshot pour '{save_name}'. Importe d'abord un bundle."
                )
            return BundleMode.FULL, None

        # Vérification mismatch par filename (Drive ne stocke pas le sha256 du zip facilement)
        latest = self.latest_version()
        if latest is not None and snap.parent_bundle_filename != latest.filename:
            if requested_mode == BundleMode.DIFF:
                raise ParentBundleSHAmismatchError(
                    "Un autre joueur a poussé depuis ton dernier import. "
                    "Pull la dernière version avant de re-pousser un diff."
                )
            _log.info("AUTO push Drive : filename mismatch, fallback FULL")
            return BundleMode.FULL, None

        return BundleMode.DIFF, snap

    def push_bundle(
        self,
        save_name: str,
        uploaded_by: str,
        note: str = "",
        progress=None,
        root: Path | None = None,
        *,
        mode,
    ) -> tuple:
        from pzsavesync import bundle as bundle_mod
        from pzsavesync.bundle import BundleMode
        from pzsavesync.diff_errors import DiffTooBigError
        from pzsavesync.sync import PushStats, Version, _estimate_full_bundle_size

        self.init_if_needed()
        full_size_estimate = _estimate_full_bundle_size(save_name, root)
        actual_mode, parent_snapshot = self._resolve_mode_and_snapshot(save_name, mode)

        ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_user = "".join(c for c in uploaded_by if c.isalnum() or c in "-_") or "anon"
        safe_save = "".join(c for c in save_name if c.isalnum() or c in "-_") or "save"
        filename = f"bundle_{safe_save}_{ts}_{safe_user}.zip"

        tmp_path = Path(tempfile.mktemp(suffix=".zip", prefix="pzsavesync_push_"))
        try:
            try:
                manifest = bundle_mod.build_bundle(
                    save_name=save_name, out_zip=tmp_path, created_by=uploaded_by,
                    note=note, root=root, progress=progress, mode=actual_mode,
                    parent_snapshot=parent_snapshot,
                )
            except DiffTooBigError as e:
                if mode == BundleMode.AUTO:
                    _log.info("DiffTooBig AUTO — fallback FULL (%s)", e)
                    tmp_path.unlink(missing_ok=True)
                    actual_mode = BundleMode.FULL
                    parent_snapshot = None
                    manifest = bundle_mod.build_bundle(
                        save_name=save_name, out_zip=tmp_path, created_by=uploaded_by,
                        note=note, root=root, progress=progress, mode=BundleMode.FULL,
                    )
                else:
                    raise

            actual_size = tmp_path.stat().st_size

            # Upload vers Drive
            self._client.upload_file(self._versions_id, filename, tmp_path)

        finally:
            tmp_path.unlink(missing_ok=True)

        version = Version(
            filename=filename,
            save_name=save_name,
            uploaded_by=uploaded_by,
            uploaded_at=manifest.created_at,
            size_bytes=actual_size,
            has_db=manifest.has_db,
            server_files=manifest.server_files,
            note=note,
            bundle_mode=manifest.bundle_mode,
            parent_bundle_sha256=manifest.parent_bundle_sha256,
            full_size_estimate_bytes=full_size_estimate,
        )
        data = self._read_manifest()
        data.setdefault("versions", []).append(version.to_dict())
        self._write_manifest(data)

        stats = PushStats(
            mode_used=manifest.bundle_mode,
            full_size_estimate_bytes=full_size_estimate,
            actual_size_bytes=actual_size,
            files_total_in_save=(
                len(manifest.expected_save_files) if manifest.expected_save_files else manifest.save_files
            ),
            files_pushed=manifest.save_files,
            files_unchanged_skipped=(
                max(0, len(manifest.expected_save_files) - len(manifest.diff_files))
                if manifest.bundle_mode == "diff" else 0
            ),
        )
        return version, stats

    # ---------- pull ----------

    def pull_bundle(self, version, backup_dir: Path, *, verify_hash: bool = True):
        from pzsavesync import bundle as bundle_mod
        from pzsavesync import snapshot as snapshot_mod
        from pzsavesync.config import APP_DIR

        f = self._client.find_file(self._versions_id, version.filename)
        if f is None:
            raise FileNotFoundError(
                f"Fichier introuvable sur Google Drive : {version.filename}"
            )

        tmp_dir = APP_DIR / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_zip = tmp_dir / version.filename
        try:
            self._client.download_file(f["id"], tmp_zip)
            # Lire manifest AVANT extract (extract ne supprime pas le zip mais on veut le sha)
            try:
                inner_manifest = bundle_mod.read_manifest(tmp_zip)
            except Exception:
                inner_manifest = None
            report = bundle_mod.extract_bundle(
                tmp_zip, backup_dir=backup_dir, verify_hash=verify_hash,
            )
        finally:
            tmp_zip.unlink(missing_ok=True)

        # Snapshot post-import (best-effort)
        if inner_manifest is not None:
            try:
                snap = snapshot_mod.compute_snapshot(
                    save_dir=report.save_dir,
                    save_name=report.save_name,
                    parent_sha=inner_manifest.sha256,
                    parent_filename=version.filename,
                )
                snapshot_mod.save_snapshot(snap)
            except Exception as e:
                _log.warning("Snapshot post-import Drive échoué : %s", e)

        return report

    # ---------- maintenance ----------

    def prune_versions(
        self,
        keep_last_n: int | None = None,
        older_than_days: int | None = None,
        save_name: str | None = None,
    ) -> list[str]:
        from pzsavesync.sync import SharedRepo
        if keep_last_n is None and older_than_days is None:
            raise ValueError("Préciser au moins keep_last_n ou older_than_days.")
        if keep_last_n is not None and keep_last_n < SharedRepo.MIN_KEEP_LAST_N:
            keep_last_n = SharedRepo.MIN_KEEP_LAST_N

        data = self._read_manifest()
        versions_all = data.get("versions", [])

        if save_name:
            in_scope = [v for v in versions_all if v.get("save_name") == save_name]
            other = [v for v in versions_all if v.get("save_name") != save_name]
        else:
            in_scope = list(versions_all)
            other = []

        in_scope.sort(key=lambda v: v.get("uploaded_at", ""))
        to_delete: list[dict] = []

        if older_than_days is not None:
            cutoff = dt.datetime.now() - dt.timedelta(days=older_than_days)
            for v in in_scope:
                try:
                    ts = dt.datetime.fromisoformat(v.get("uploaded_at", ""))
                    if ts < cutoff:
                        to_delete.append(v)
                except (ValueError, TypeError):
                    continue

        if keep_last_n is not None and len(in_scope) > keep_last_n:
            for v in in_scope[: len(in_scope) - keep_last_n]:
                if v not in to_delete:
                    to_delete.append(v)

        deleted: list[str] = []
        for v in to_delete:
            fname = v.get("filename")
            if not fname:
                continue
            f = self._client.find_file(self._versions_id, fname)
            if f:
                self._client.delete_file_by_id(f["id"])
            deleted.append(fname)

        kept_scope = [v for v in in_scope if v not in to_delete]
        data["versions"] = other + kept_scope
        data["versions"].sort(key=lambda v: v.get("uploaded_at", ""))
        self._write_manifest(data)
        return deleted

    def health_check(self):
        from pzsavesync.sync import RepoHealth
        manifest_versions = self._read_manifest().get("versions", [])
        in_manifest = {v.get("filename") for v in manifest_versions if v.get("filename")}
        drive_files = self._client.list_files(self._versions_id)
        on_drive = {
            f["name"] for f in drive_files
            if f.get("mimeType") != MIME_FOLDER and f["name"].lower().endswith(".zip")
        }
        orphan_files = sorted(on_drive - in_manifest)
        missing_files = sorted(in_manifest - on_drive)
        return RepoHealth(
            orphan_files=orphan_files,
            missing_files=missing_files,
            tmp_residues=[],
            readable_orphans=[],
        )

    def cleanup_orphan_tmp_files(self, min_age_seconds: float | None = None) -> list[str]:
        return []  # Pas de .tmp sur Drive

    def adopt_orphans(self, orphans: list) -> int:
        return 0  # Non applicable sur Drive

    def remove_missing_from_manifest(self, missing: list[str]) -> int:
        if not missing:
            return 0
        data = self._read_manifest()
        kept = [v for v in data.get("versions", []) if v.get("filename") not in set(missing)]
        removed = len(data.get("versions", [])) - len(kept)
        data["versions"] = kept
        self._write_manifest(data)
        return removed

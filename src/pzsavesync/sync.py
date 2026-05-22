"""Push/pull versionné d'un BUNDLE PZ (save+db+config) vers un dossier partagé."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from pzsavesync import bundle as bundle_mod  # utilisé dans health_check/adopt_orphans

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


@dataclass
class RepoHealth:
    """Résultat du health_check d'un SharedRepo.

    - orphan_files : .zip présents physiquement mais absents du manifest
    - missing_files : noms dans le manifest sans .zip physique correspondant
    - tmp_residues : fichiers .tmp / .rwm.tmp à nettoyer
    - readable_orphans : sous-set d'orphan_files dont le manifest interne
      est lisible → peuvent être réintégrés via adopt_orphans()
    """
    orphan_files: list[str]
    missing_files: list[str]
    tmp_residues: list[str]
    readable_orphans: list  # list[tuple[str, BundleManifest]]

    @property
    def is_healthy(self) -> bool:
        return not (self.orphan_files or self.missing_files or self.tmp_residues)

    @property
    def summary(self) -> str:
        if self.is_healthy:
            return "Repo cloud OK — aucun problème détecté."
        bits = []
        if self.orphan_files:
            bits.append(f"{len(self.orphan_files)} .zip orphelin(s) (présents mais "
                        f"absents du manifest)")
        if self.missing_files:
            bits.append(f"{len(self.missing_files)} entrée(s) sans .zip physique")
        if self.tmp_residues:
            bits.append(f"{len(self.tmp_residues)} fichier(s) .tmp résiduel(s)")
        return "Problèmes détectés : " + " · ".join(bits)


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

    def health_check(self) -> "RepoHealth":
        """Vérifie l'intégrité du repo cloud :
        - orphan_files : .zip physiquement présents mais ABSENTS du manifest
          (peut arriver après race condition / crash entre écriture zip et
          mise à jour du manifest). Ils sont invisibles au pull mais lisent
          potentiellement une version saine.
        - missing_files : entrées du manifest qui PAS de .zip physique
          (l'archive a été supprimée à la main, ou la sync cloud a foiré).
        - tmp_residues : .tmp / .rwm.tmp résiduels.
        """
        orphan_files: list[str] = []
        missing_files: list[str] = []
        tmp_residues: list[str] = []
        readable_orphans: list[tuple[str, "bundle_mod.BundleManifest"]] = []

        if not self.versions_dir.exists():
            return RepoHealth(
                orphan_files=[], missing_files=[], tmp_residues=[],
                readable_orphans=[],
            )

        # 1. Set des filenames référencés par le manifest
        manifest_versions = self._read_manifest().get("versions", [])
        in_manifest = {v.get("filename") for v in manifest_versions if v.get("filename")}

        # 2. Scan des fichiers physiques
        on_disk: set[str] = set()
        for f in self.versions_dir.iterdir():
            if not f.is_file():
                continue
            if f.suffix == ".tmp" or f.name.endswith(".rwm.tmp"):
                tmp_residues.append(f.name)
                continue
            if not f.name.lower().endswith(".zip"):
                continue
            on_disk.add(f.name)

        # 3. Orphelins = sur disque mais pas dans manifest
        for name in sorted(on_disk - in_manifest):
            orphan_files.append(name)
            # Essayer de lire son manifest interne pour pouvoir le réintégrer proprement
            try:
                m = bundle_mod.read_manifest(self.versions_dir / name)
                readable_orphans.append((name, m))
            except Exception:
                # Zip illisible — on le signale mais on ne le réintègre pas
                pass

        # 4. Fantômes = dans manifest mais pas sur disque
        for name in sorted(in_manifest - on_disk):
            missing_files.append(name)

        return RepoHealth(
            orphan_files=orphan_files,
            missing_files=missing_files,
            tmp_residues=tmp_residues,
            readable_orphans=readable_orphans,
        )

    def adopt_orphans(self, orphans: "list[tuple[str, bundle_mod.BundleManifest]]") -> int:
        """Réintègre des bundles orphelins dans le manifest.

        Pour chaque (filename, manifest) fourni, ajoute une entrée Version
        dans le manifest du repo. Renvoie le nombre adopté.
        """
        if not orphans:
            return 0
        data = self._read_manifest()
        versions = data.setdefault("versions", [])
        existing_names = {v.get("filename") for v in versions}
        adopted = 0
        for filename, m in orphans:
            if filename in existing_names:
                continue
            path = self.versions_dir / filename
            try:
                size = path.stat().st_size
            except OSError:
                continue
            v = Version(
                filename=filename,
                save_name=m.save_name,
                uploaded_by=m.created_by,
                uploaded_at=m.created_at,
                size_bytes=size,
                has_db=m.has_db,
                server_files=list(m.server_files),
                note=(m.note + " (réintégré)").strip(),
            )
            versions.append(v.to_dict())
            adopted += 1
        # Re-tri par date
        versions.sort(key=lambda v: v.get("uploaded_at", ""))
        self._write_manifest(data)
        return adopted

    def remove_missing_from_manifest(self, missing: list[str]) -> int:
        """Supprime du manifest les entrées qui n'ont pas de .zip physique.
        Renvoie le nombre retiré.
        """
        if not missing:
            return 0
        data = self._read_manifest()
        kept = [v for v in data.get("versions", []) if v.get("filename") not in set(missing)]
        removed = len(data.get("versions", [])) - len(kept)
        data["versions"] = kept
        self._write_manifest(data)
        return removed

    # Âge minimal d'un .tmp pour qu'on accepte de le supprimer comme "orphelin".
    # Si une autre instance de l'app est en plein push et a écrit son .tmp il
    # y a 30s, on ne veut PAS le clobber. Un push réel s'étale rarement sur
    # > 5 minutes pour un bundle de quelques GB ; au-delà, c'est très
    # probablement un résidu d'opération crashée.
    TMP_ORPHAN_MIN_AGE_SECONDS = 5 * 60

    def cleanup_orphan_tmp_files(self, min_age_seconds: float | None = None) -> list[str]:
        """Supprime les fichiers .tmp orphelins (résidus d'une opération interrompue).

        Sécurité : on ne supprime que les .tmp dont la mtime est plus vieille
        que `min_age_seconds` (par défaut TMP_ORPHAN_MIN_AGE_SECONDS = 5 min).
        Sans ce garde-fou, lancer une 2e instance de l'app pendant qu'une
        autre fait un push peut clobber le .tmp en cours d'écriture →
        l'`os.replace(tmp, target)` échouerait.

        `min_age_seconds=0` permet de forcer la suppression sans délai (utile
        pour les tests).

        Renvoie la liste des fichiers supprimés.
        """
        deleted: list[str] = []
        if not self.versions_dir.exists():
            return deleted
        if min_age_seconds is None:
            min_age_seconds = self.TMP_ORPHAN_MIN_AGE_SECONDS
        import time as _time
        now = _time.time()
        for f in self.versions_dir.iterdir():
            if not f.is_file():
                continue
            if f.suffix == ".tmp" or f.name.endswith(".rwm.tmp"):
                try:
                    age = now - f.stat().st_mtime
                except OSError:
                    continue
                if age < min_age_seconds:
                    continue  # trop récent — peut-être un push en cours dans une autre instance
                try:
                    f.unlink(missing_ok=True)
                    deleted.append(f.name)
                except OSError:
                    pass
        return deleted

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
        self,
        save_name: str,
        uploaded_by: str,
        note: str = "",
        progress: bundle_mod.ProgressCb | None = None,
        root: Path | None = None,
    ) -> Version:
        """Crée un bundle complet (save+db+config) et le pousse dans le dossier partagé.

        `progress` est transmis à `build_bundle` pour l'UI de progression.
        `root` permet d'injecter une racine Zomboid alternative (tests, $PZ_ZOMBOID_ROOT
        est honoré par défaut côté bundle).
        """
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
            root=root,
            progress=progress,
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

    # ---------- nettoyage ----------
    # Minimum de versions à conserver côté cloud pour pouvoir rollback si
    # un push contient une save corrompue (ex: PZ a écrit n'importe quoi
    # avant que tu cliques). Avec N=1, tu perds la version précédente saine
    # dès qu'une mauvaise est push. N=2 = un cran de filet.
    MIN_KEEP_LAST_N = 2

    def prune_versions(
        self,
        keep_last_n: int | None = None,
        older_than_days: int | None = None,
        save_name: str | None = None,
    ) -> list[str]:
        """Supprime des versions selon des critères. Renvoie la liste des fichiers supprimés.

        - keep_last_n : conserve les N plus récentes (par version, du plus vieux supprimé en premier).
          **Clamp automatique à MIN_KEEP_LAST_N=2** pour garantir un rollback possible.
        - older_than_days : supprime tout ce qui est plus ancien que N jours
        - save_name : si fourni, ne touche que les versions de cette save

        Au moins un des deux critères (keep_last_n, older_than_days) est requis.
        """
        if keep_last_n is None and older_than_days is None:
            raise ValueError("Préciser au moins keep_last_n ou older_than_days.")
        if keep_last_n is not None and keep_last_n < self.MIN_KEEP_LAST_N:
            # Garde-fou anti-perte : on clamp silencieusement vers le haut.
            # Si l'user explicite veut purger à fond, il peut passer par
            # older_than_days ou supprimer le dossier à la main.
            keep_last_n = self.MIN_KEEP_LAST_N

        data = self._read_manifest()
        versions_all = data.get("versions", [])

        # Filtrer la portée
        if save_name:
            in_scope = [v for v in versions_all if v.get("save_name") == save_name]
            other = [v for v in versions_all if v.get("save_name") != save_name]
        else:
            in_scope = list(versions_all)
            other = []

        # Trier par uploaded_at croissant (plus vieux en premier)
        in_scope.sort(key=lambda v: v.get("uploaded_at", ""))

        to_delete: list[dict] = []

        # Critère âge
        if older_than_days is not None:
            cutoff = dt.datetime.now() - dt.timedelta(days=older_than_days)
            for v in in_scope:
                try:
                    ts = dt.datetime.fromisoformat(v.get("uploaded_at", ""))
                    if ts < cutoff:
                        to_delete.append(v)
                except (ValueError, TypeError):
                    continue

        # Critère "garder N dernières"
        if keep_last_n is not None and len(in_scope) > keep_last_n:
            extras = in_scope[: len(in_scope) - keep_last_n]
            for v in extras:
                if v not in to_delete:
                    to_delete.append(v)

        # Effacer physiquement + mettre à jour le manifest
        deleted_filenames: list[str] = []
        for v in to_delete:
            fname = v.get("filename")
            if not fname:
                continue
            path = self.versions_dir / fname
            try:
                path.unlink(missing_ok=True)
                deleted_filenames.append(fname)
            except OSError:
                pass

        # Reconstruire le manifest
        kept_scope = [v for v in in_scope if v not in to_delete]
        data["versions"] = other + kept_scope
        # Re-trier par date croissante pour cohérence
        data["versions"].sort(key=lambda v: v.get("uploaded_at", ""))
        self._write_manifest(data)
        return deleted_filenames

    def total_size_bytes(self) -> int:
        """Somme des tailles des versions enregistrées (utile pour l'UI de nettoyage)."""
        return sum(v.size_bytes for v in self.list_versions())

    # ---------- manifest ----------
    def _read_manifest(self) -> dict:
        """Lit le manifest du repo. Tolérant aux corruptions.

        Si manifest.json est tronqué (sync cloud foireuse, crash en écriture)
        ou édité à la main de manière incohérente, on log et on renvoie un
        manifest vide plutôt que de crasher l'UI. Les .zip physiques restent
        sur disque — `health_check()` les redétectera comme orphelins et
        proposera une réintégration.
        """
        if not self.manifest_path.exists():
            return {"versions": []}
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"[sync] manifest.json illisible : {e} — fallback vide", file=sys.stderr)
            return {"versions": []}
        if not isinstance(data, dict):
            print("[sync] manifest.json invalide (pas un objet) — fallback vide", file=sys.stderr)
            return {"versions": []}
        if not isinstance(data.get("versions"), list):
            data["versions"] = []
        return data

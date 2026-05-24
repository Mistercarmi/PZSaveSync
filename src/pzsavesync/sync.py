"""Push/pull versionné d'un BUNDLE PZ (save+db+config) vers un dossier partagé."""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pzsavesync import bundle as bundle_mod  # utilisé dans health_check/adopt_orphans
from pzsavesync import snapshot as snapshot_mod
from pzsavesync.bundle import BundleMode
from pzsavesync.diff_errors import (
    DiffTooBigError,
    NoSnapshotAvailableError,
    ParentBundleSHAmismatchError,
)

_log = logging.getLogger(__name__)

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


def _estimate_full_bundle_size(save_name: str, root: Path | None) -> int:
    """Estime la taille (uncompressed) qu'aurait un bundle FULL pour cette save.

    Utilisé pour calculer le gain ratio à afficher dans l'UI. Approche pessimiste
    (compte les sources uncompressed) — la valeur reflète "ce qu'on a évité de
    zipper et d'envoyer" plus que "taille zip économisée". Suffisant pour
    l'affichage utilisateur ("X MB → Y MB").
    """
    root = root or bundle_mod.zomboid_root()
    save_dir = root / "Saves" / "Multiplayer" / save_name
    total = 0
    if save_dir.exists():
        for f in save_dir.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    continue
    # Ajouter db + server (négligeable mais réaliste)
    try:
        cf = bundle_mod.discover_companion_files(save_name, root)
        if cf.db is not None:
            total += cf.db.stat().st_size
        for comp in cf.db_companions:
            try:
                total += comp.stat().st_size
            except OSError:
                pass
        for srv in cf.server_files:
            try:
                total += srv.stat().st_size
            except OSError:
                pass
    except Exception:
        pass
    return total


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
    # --- v0.4.0 : champs bundle différentiel ---
    bundle_mode: str = "full"  # "full" | "diff"
    parent_bundle_sha256: str = ""  # vide si full ; sha du parent si diff
    full_size_estimate_bytes: int = 0  # taille estimée si on avait fait un full (pour afficher le gain)

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
            "bundle_mode": self.bundle_mode,
            "parent_bundle_sha256": self.parent_bundle_sha256,
            "full_size_estimate_bytes": self.full_size_estimate_bytes,
        }


@dataclass
class PushStats:
    """Stats post-push pour l'affichage UI du gain.

    `mode_used` est ce qui a été effectivement utilisé (peut différer du mode
    demandé en cas de fallback AUTO → FULL).
    """
    mode_used: str  # "full" | "diff"
    full_size_estimate_bytes: int
    actual_size_bytes: int
    files_total_in_save: int = 0
    files_pushed: int = 0
    files_unchanged_skipped: int = 0

    @property
    def gain_ratio(self) -> float:
        """Ratio 0.0-1.0 d'économie vs full. 0 si pas de gain (full)."""
        if self.full_size_estimate_bytes == 0 or self.mode_used == "full":
            return 0.0
        if self.actual_size_bytes >= self.full_size_estimate_bytes:
            return 0.0
        return 1.0 - (self.actual_size_bytes / self.full_size_estimate_bytes)


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
        # Filtrer aux seuls champs connus de Version pour tolérer
        # les manifestes pré-v0.4.0 et les éventuels champs futurs.
        known = set(Version.__dataclass_fields__.keys())
        for v in manifest.get("versions", []):
            v = dict(v)
            v.setdefault("save_name", "")
            v.setdefault("has_db", False)
            v.setdefault("server_files", [])
            # Compat v0.4.0
            v.setdefault("bundle_mode", "full")
            v.setdefault("parent_bundle_sha256", "")
            v.setdefault("full_size_estimate_bytes", 0)
            filtered = {k: val for k, val in v.items() if k in known}
            out.append(Version(**filtered))
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
        *,
        mode: BundleMode = BundleMode.FULL,
    ) -> tuple[Version, PushStats]:
        """Crée un bundle (full ou diff) et le pousse dans le dossier partagé.

        - mode=FULL : comportement v0.3.x (bundle complet save+db+server).
        - mode=DIFF : nécessite un snapshot pré-existant pour cette save (post-pull).
          Vérifie aussi que le parent_sha == latest_version.sha256 du cloud (sinon
          `ParentBundleSHAmismatchError` — quelqu'un a poussé entre temps).
        - mode=AUTO : DIFF si snapshot disponible ET parent_sha cohérent, sinon FULL.

        Retourne (Version persistée, PushStats pour l'UI).

        `progress` est transmis à `build_bundle` pour l'UI de progression.
        `root` permet d'injecter une racine Zomboid alternative (tests).
        """
        self.init_if_needed()

        # Estimer la taille d'un full pour pouvoir afficher le gain réalisé
        full_size_estimate = _estimate_full_bundle_size(save_name, root)

        # Préparer le mode + snapshot parent
        actual_mode, parent_snapshot = self._resolve_mode_and_snapshot(
            save_name=save_name, requested_mode=mode,
        )

        ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_user = "".join(c for c in uploaded_by if c.isalnum() or c in "-_") or "anon"
        safe_save = "".join(c for c in save_name if c.isalnum() or c in "-_") or "save"
        filename = f"bundle_{safe_save}_{ts}_{safe_user}.zip"
        target = self.versions_dir / filename

        # Fix v0.4.0 — DiffTooBig fallback : si > 85% des chunks ont changé,
        # _build_diff_bundle raise DiffTooBigError. En mode AUTO, on retry
        # silencieusement en FULL. En mode DIFF explicite, on propage l'erreur
        # au caller (GUI peut afficher un dialog "Diff trop important, FULL ?").
        try:
            manifest = bundle_mod.build_bundle(
                save_name=save_name,
                out_zip=target,
                created_by=uploaded_by,
                note=note,
                root=root,
                progress=progress,
                mode=actual_mode,
                parent_snapshot=parent_snapshot,
            )
        except DiffTooBigError as e:
            if mode == BundleMode.AUTO:
                _log.info("DiffTooBig en mode AUTO (%s) — fallback FULL silencieux", e)
                # Nettoyage : un .tmp peut avoir été laissé par le diff avorté
                tmp_leftover = target.with_suffix(target.suffix + ".tmp")
                for leftover in (target, tmp_leftover):
                    if leftover.exists():
                        try:
                            leftover.unlink()
                        except OSError:
                            pass
                actual_mode = BundleMode.FULL
                parent_snapshot = None
                manifest = bundle_mod.build_bundle(
                    save_name=save_name,
                    out_zip=target,
                    created_by=uploaded_by,
                    note=note,
                    root=root,
                    progress=progress,
                    mode=BundleMode.FULL,
                )
            else:
                # Mode DIFF explicite : on propage, le GUI décide (proposer
                # bascule FULL via une exception typée que l'UI catch).
                raise

        actual_size = target.stat().st_size

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
            files_total_in_save=len(manifest.expected_save_files) if manifest.expected_save_files else manifest.save_files,
            files_pushed=manifest.save_files,
            files_unchanged_skipped=(
                max(0, len(manifest.expected_save_files) - len(manifest.diff_files))
                if manifest.bundle_mode == "diff" else 0
            ),
        )
        return version, stats

    def _resolve_mode_and_snapshot(
        self, save_name: str, requested_mode: BundleMode,
    ) -> tuple[BundleMode, "snapshot_mod.Snapshot | None"]:
        """Détermine le mode effectif + charge le snapshot parent si applicable.

        Effets :
        - FULL : retourne (FULL, None) sans rien charger.
        - DIFF explicite : charge le snapshot, vérifie parent SHA, raise si KO.
        - AUTO : essaie DIFF, fallback FULL silencieux si pas de snapshot ou
          si parent SHA mismatch (UI peut alerter via PushStats).
        """
        if requested_mode == BundleMode.FULL:
            return BundleMode.FULL, None

        # Charger le snapshot le plus récent pour cette save
        try:
            snap = snapshot_mod.find_latest_snapshot_for_save(save_name)
        except Exception as e:
            _log.warning("Lecture snapshot échouée (%s) — fallback FULL", e)
            snap = None

        if snap is None:
            if requested_mode == BundleMode.DIFF:
                raise NoSnapshotAvailableError(
                    f"Pas de snapshot pour '{save_name}'. Importe d'abord un bundle "
                    f"depuis le cloud pour créer un snapshot, ou utilise le mode FULL."
                )
            # AUTO : fallback silencieux
            return BundleMode.FULL, None

        # Vérifier que parent SHA == latest_version.sha (on n'a pas pris de retard)
        latest = self.latest_version()
        if latest is not None and latest.parent_bundle_sha256:
            # latest est elle-même un diff — pour matcher, on doit pouvoir lire
            # son zip et extraire son sha256
            pass  # on tolère, edge case rare
        if latest is not None:
            # Récupérer le sha du bundle latest depuis son zip (manifest interne)
            try:
                latest_manifest = bundle_mod.read_manifest(self.versions_dir / latest.filename)
                latest_sha = latest_manifest.sha256
            except Exception:
                latest_sha = ""

            if latest_sha and snap.parent_bundle_sha256 != latest_sha:
                if requested_mode == BundleMode.DIFF:
                    raise ParentBundleSHAmismatchError(
                        "Un autre joueur a poussé une nouvelle version depuis ton dernier import. "
                        "Pull la dernière version avant de re-pousser un diff."
                    )
                # AUTO : fallback FULL silencieux
                _log.info("AUTO push : parent SHA mismatch, fallback FULL")
                return BundleMode.FULL, None

        return BundleMode.DIFF, snap

    def pull_bundle(self, version: Version, backup_dir: Path, *, verify_hash: bool = True):
        """Restaure le bundle d'une version. Backup automatique de l'existant.

        Après extract réussi, calcule un snapshot SHA256 du save_dir local pour
        permettre les futurs push différentiels. Échec snapshot = non-bloquant.

        `verify_hash=False` permet de skip la vérif SHA256 si le caller (GUI)
        l'a déjà faite — évite un double calcul de 5-30s sur grosse save.
        """
        archive = self.versions_dir / version.filename
        if not archive.exists():
            raise FileNotFoundError(f"Archive manquante : {archive}")
        report = bundle_mod.extract_bundle(archive, backup_dir=backup_dir, verify_hash=verify_hash)

        # Snapshot post-import (best-effort, ne bloque pas le pull si échoue)
        try:
            manifest = bundle_mod.read_manifest(archive)
            snap = snapshot_mod.compute_snapshot(
                save_dir=report.save_dir,
                save_name=report.save_name,
                parent_sha=manifest.sha256,
                parent_filename=version.filename,
            )
            snapshot_mod.save_snapshot(snap)
        except Exception as e:
            _log.warning("Snapshot post-import échoué (%s) — push diff indisponible jusqu'à un nouveau pull", e)

        return report

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

        # FIX 4 v0.4.0 — protection seed FULL parent de DIFFs :
        # On ne peut PAS supprimer une version FULL si une version DIFF gardée
        # référence son sha256 comme parent_bundle_sha256. Sinon le DIFF
        # devient orphelin et provoque le bug FIX 3 (save corrompue au pull).
        kept_after_delete = [v for v in in_scope if v not in to_delete]
        kept_parent_shas = {
            v.get("parent_bundle_sha256")
            for v in kept_after_delete
            if v.get("bundle_mode") == "diff" and v.get("parent_bundle_sha256")
        }
        if kept_parent_shas:
            # Pour chaque candidate FULL à supprimer, lire son SHA et vérifier
            # qu'aucun DIFF gardé ne le référence.
            protected: list[dict] = []
            for v in list(to_delete):
                if v.get("bundle_mode") != "full":
                    continue
                fname = v.get("filename")
                if not fname:
                    continue
                try:
                    m = bundle_mod.read_manifest(self.versions_dir / fname)
                    if m.sha256 in kept_parent_shas:
                        protected.append(v)
                        to_delete.remove(v)
                        _log.info(
                            "prune_versions : protection FULL %s "
                            "(parent d'au moins 1 DIFF gardé)", fname,
                        )
                except Exception as e:
                    # Si on ne peut pas lire le manifest, par prudence on protège
                    # (mieux vaut garder une version qu'on ne sait pas analyser
                    # que risquer de casser la chaîne).
                    _log.warning(
                        "prune_versions : impossible de lire manifest de %s (%s), "
                        "version protégée par sécurité", fname, e,
                    )
                    protected.append(v)
                    to_delete.remove(v)

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


# ============================================================ factory

def make_repo(cfg) -> "SharedRepo":
    """Retourne le SharedRepo pour le profil actif.

    Utilisé par la GUI pour centraliser la construction du repo.
    """
    prof = cfg.current
    if not prof.shared_folder:
        raise ValueError(
            "Aucun dossier partagé configuré.\n"
            "Configure un dossier dans l'onglet Réglages."
        )
    return SharedRepo(Path(prof.shared_folder))

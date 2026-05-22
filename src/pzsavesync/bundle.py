"""Bundle PZ = save complète prête à être passée à un pote.

Structure du zip :
    bundle_manifest.json
    save/                          → Zomboid/Saves/Multiplayer/<save_name>/
        ... (contenu du dossier save)
    db/<save_name>.db              → Zomboid/db/<save_name>.db
    db/<save_name>.db-wal          → si présent (transactions SQLite non-checkpointées)
    db/<save_name>.db-shm          → si présent
    db/<save_name>.db-journal      → si présent
    server/
        <save_name>.ini            → Zomboid/Server/<save_name>.ini
        <save_name>_SandboxVars.lua
        <save_name>_spawnregions.lua
        <save_name>_spawnpoints.lua → si présent (custom respawn)

Le manifest porte le nom de la save d'origine, donc l'extraction restaure dans
le BON dossier chez le destinataire même si lui n'a jamais eu cette save avant.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable


MANIFEST_FILENAME = "bundle_manifest.json"
BUNDLE_VERSION = 3  # v3 : ajout _spawnpoints.lua + fichiers SQLite WAL/SHM/journal
_REQUIRED_MANIFEST_FIELDS = ("bundle_version", "save_name", "created_at", "created_by")
_BAD_NAME_CHARS = '<>:"/\\|?*'

# Suffixes SQLite compagnons d'un fichier .db (mode WAL principalement).
# Si PZ est tué avant checkpoint, .db-wal contient les dernières transactions
# (joueurs, vehicules, factions). Sans lui = perte de progression DB.
_DB_COMPANION_SUFFIXES = ("-wal", "-shm", "-journal")

# Sécurité : limites max à l'extraction (anti zip-bomb)
MAX_BUNDLE_SIZE_BYTES = 5 * 1024 * 1024 * 1024  # 5 GB compressé
MAX_UNCOMPRESSED_SIZE_BYTES = 20 * 1024 * 1024 * 1024  # 20 GB décompressé
MAX_FILES_IN_BUNDLE = 500_000  # nombre max de fichiers (une save PZ multi longue peut largement dépasser 50k chunks)

# Callback de progression : (étape, courant, total) -> None
# étape ∈ {"scan", "zip", "extract"} ; courant/total en octets ou en fichiers
ProgressCb = Callable[[str, int, int], None]


@dataclass
class BundleManifest:
    bundle_version: int
    save_name: str
    created_at: str
    created_by: str
    note: str = ""
    has_db: bool = False
    server_files: list[str] = field(default_factory=list)
    save_files: int = 0
    save_bytes: int = 0
    mods: list[str] = field(default_factory=list)
    workshop_items: list[str] = field(default_factory=list)
    sha256: str = ""  # depuis v2 : hash du contenu (hors champ sha256 lui-même)
    inferred_server_prefix: str = ""  # depuis v3 : prefix utilisé côté hôte si != save_name

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CompanionFiles:
    """Fichiers compagnons d'une save (hors save_dir).

    `server_prefix` est le prefix réellement utilisé chez l'hôte pour le
    .ini / .db (souvent identique au save_name, mais peut différer si l'hôte
    a un Server name distinct du World name — cas par défaut : "servertest").
    `exact_match` = True quand le prefix == save_name.

    `db_companions` : fichiers SQLite WAL/SHM/journal qui accompagnent la .db
    quand SQLite est en mode WAL et que PZ n'a pas checkpointé. Si on les
    laisse derrière, on perd les dernières transactions (joueurs, vehicules).
    """
    save_dir: Path | None = None
    db: Path | None = None
    db_companions: list[Path] = field(default_factory=list)
    ini: Path | None = None
    sandbox: Path | None = None
    spawn: Path | None = None
    spawn_points: Path | None = None
    server_prefix: str = ""
    exact_match: bool = True

    @property
    def server_files(self) -> list[Path]:
        return [
            p for p in (self.ini, self.sandbox, self.spawn, self.spawn_points)
            if p is not None
        ]

    @property
    def has_any_companion(self) -> bool:
        return any(
            p is not None
            for p in (self.db, self.ini, self.sandbox, self.spawn, self.spawn_points)
        )


def _sha256_of_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_of_zip_content(zip_path: Path) -> str:
    """Hash du contenu du zip, en excluant le manifest (qui contient le hash lui-même).

    On hash : pour chaque membre (trié), nom + taille + contenu — comme ça l'ordre
    de compression n'influence pas le résultat.
    """
    h = hashlib.sha256()
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = sorted(n for n in zf.namelist() if n != MANIFEST_FILENAME)
        for name in names:
            info = zf.getinfo(name)
            h.update(name.encode("utf-8"))
            h.update(b"|")
            h.update(str(info.file_size).encode())
            h.update(b"|")
            with zf.open(name) as fp:
                while True:
                    chunk = fp.read(1024 * 1024)
                    if not chunk:
                        break
                    h.update(chunk)
    return h.hexdigest()


def zomboid_root() -> Path:
    """Chemin Zomboid (Windows / macOS / Linux). Override via $PZ_ZOMBOID_ROOT."""
    override = os.environ.get("PZ_ZOMBOID_ROOT")
    if override:
        return Path(override)
    return Path.home() / "Zomboid"


def _validate_save_name(name: str) -> None:
    """Vérifie qu'un save_name est utilisable comme nom de dossier/fichier."""
    if not name or not name.strip():
        raise ValueError("save_name vide.")
    if any(c in name for c in _BAD_NAME_CHARS):
        raise ValueError(
            f"save_name '{name}' contient un caractère interdit ({_BAD_NAME_CHARS})."
        )
    if name.startswith(".") or name.startswith("-"):
        raise ValueError(f"save_name '{name}' ne peut pas commencer par '.' ou '-'.")
    if name in {".", ".."}:
        raise ValueError(f"save_name '{name}' invalide.")


def _safe_join(base: Path, rel: str) -> Path:
    """Joint base + rel en refusant tout path traversal (zip slip)."""
    if not rel:
        raise ValueError("chemin vide dans le zip.")
    rel_path = Path(rel)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise ValueError(f"chemin zip suspect : '{rel}'")
    base_resolved = base.resolve()
    result = (base / rel_path).resolve()
    try:
        result.relative_to(base_resolved)
    except ValueError:
        raise ValueError(f"path traversal détecté : '{rel}' sort de {base}")
    return result


def _atomic_extract_file(zf: zipfile.ZipFile, name: str, target: Path) -> None:
    """Extrait un membre du zip vers target en écriture atomique (tmp + rename)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        with zf.open(name) as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst)
        os.replace(tmp, target)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _is_safe_mod_name(name: str) -> bool:
    """Un nom de mod ne doit pas contenir de séparateurs de chemin ni de caractères système."""
    if not name or len(name) > 200:
        return False
    if any(c in name for c in '/\\<>:"|?*\x00'):
        return False
    if ".." in name:
        return False
    return True


def parse_ini_mods(ini_path: Path) -> tuple[list[str], list[str]]:
    """Extrait Mods= et WorkshopItems= depuis un .ini PZ.

    Retourne (mods, workshop_ids). Tolérant aux erreurs : retourne des listes
    vides si le fichier n'existe pas ou ne peut pas être lu.

    Encoding : `utf-8-sig` strip automatiquement le BOM UTF-8 (`\\ufeff`)
    que Notepad ajoute parfois. Sans ça, la 1ʳᵉ ligne devient
    `\\ufeffMods=...` et `startswith("Mods=")` rate → aucun mod détecté.

    Workshop IDs : doivent être strictement numériques (filtre les valeurs
    bidons / tentatives d'injection).
    """
    mods: list[str] = []
    workshop_ids: list[str] = []
    try:
        text = ini_path.read_text(encoding="utf-8-sig", errors="ignore")
    except (OSError, FileNotFoundError):
        return mods, workshop_ids
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Mods="):
            raw = [m.strip() for m in line[len("Mods="):].split(";") if m.strip()]
            mods = [m for m in raw if _is_safe_mod_name(m)]
        elif line.startswith("WorkshopItems="):
            raw = [w.strip() for w in line[len("WorkshopItems="):].split(";") if w.strip()]
            # Un Workshop ID Steam est uniquement numérique (typiquement 9-10 chiffres)
            workshop_ids = [w for w in raw if w.isdigit() and len(w) <= 20]
    return mods, workshop_ids


# Seuil de confiance pour l'inférence : si l'écart de mtime entre la save_dir et
# le candidat .ini/.db dépasse ce délai, on considère que c'est probablement pas
# le bon fichier et on n'infère pas (mieux vaut un bundle incomplet qu'un mauvais
# .ini embarqué qui écraserait la config chez le destinataire).
MTIME_INFERENCE_MAX_DELTA_SECONDS = 90 * 24 * 3600  # 90 jours


@dataclass
class _ServerSet:
    """Un set de fichiers Server cohérents (même prefix).

    `spawn_points` (custom respawn) est OPTIONNEL : PZ n'en génère qu'avec
    certains mods ou un sandbox custom. Sa présence ne change pas la
    'complétude' du set (sinon on n'aurait jamais de set complet en standard).
    """
    prefix: str
    ini: Path
    sandbox: Path | None
    spawn: Path | None
    spawn_points: Path | None = None

    @property
    def complete(self) -> bool:
        return self.sandbox is not None and self.spawn is not None

    @property
    def mtime(self) -> float:
        return self.ini.stat().st_mtime


def _scan_server_sets(server_dir: Path) -> list[_ServerSet]:
    """Liste tous les sets Server (.ini + éventuellement _SandboxVars + _spawnregions + _spawnpoints)."""
    if not server_dir.exists():
        return []
    sets: list[_ServerSet] = []
    for ini in server_dir.glob("*.ini"):
        if not ini.is_file():
            continue
        prefix = ini.stem
        sb = server_dir / f"{prefix}_SandboxVars.lua"
        sp = server_dir / f"{prefix}_spawnregions.lua"
        spp = server_dir / f"{prefix}_spawnpoints.lua"
        sets.append(_ServerSet(
            prefix=prefix,
            ini=ini,
            sandbox=sb if sb.exists() else None,
            spawn=sp if sp.exists() else None,
            spawn_points=spp if spp.exists() else None,
        ))
    return sets


def _find_db_companions(db_path: Path) -> list[Path]:
    """Trouve les fichiers SQLite compagnons (.db-wal, .db-shm, .db-journal) à côté d'un .db."""
    if db_path is None or not db_path.exists():
        return []
    companions: list[Path] = []
    for suffix in _DB_COMPANION_SUFFIXES:
        comp = db_path.with_name(db_path.name + suffix)
        if comp.exists() and comp.is_file():
            companions.append(comp)
    return companions


def _pick_best_server_set(sets: list[_ServerSet], reference_mtime: float) -> _ServerSet | None:
    """Choisit le set Server le plus probable pour une save.

    Priorisation stricte :
    1. S'il existe au moins un set **complet** (.ini + sandbox + spawn), on
       choisit parmi eux celui à la mtime la plus proche de la save_dir.
       Les sets incomplets (.ini orphelin) sont ignorés tant qu'un complet
       est candidat.
    2. Sinon (tous incomplets), on prend le moins mauvais en delta mtime.
    3. Rejet si même le meilleur dépasse ``MTIME_INFERENCE_MAX_DELTA_SECONDS``.
    """
    if not sets:
        return None
    complete = [s for s in sets if s.complete]
    pool = complete if complete else sets
    best = min(pool, key=lambda s: abs(s.mtime - reference_mtime))
    if abs(best.mtime - reference_mtime) > MTIME_INFERENCE_MAX_DELTA_SECONDS:
        return None
    return best


def _pick_db_for_prefix(db_dir: Path, preferred_prefix: str, reference_mtime: float) -> Path | None:
    """Trouve le .db le plus probable pour une save.

    1. Si `db/{preferred_prefix}.db` existe → on le prend (cross-vérification
       avec le Server set retenu, forte confiance).
    2. Sinon, mtime correlation avec rejet si delta > seuil.
    """
    if not db_dir.exists():
        return None
    direct = db_dir / f"{preferred_prefix}.db"
    if direct.exists():
        return direct
    candidates = [p for p in db_dir.glob("*.db") if p.is_file()]
    if not candidates:
        return None
    best = min(candidates, key=lambda p: abs(p.stat().st_mtime - reference_mtime))
    if abs(best.stat().st_mtime - reference_mtime) > MTIME_INFERENCE_MAX_DELTA_SECONDS:
        return None
    return best


def discover_companion_files(
    save_name: str, root: Path | None = None,
) -> CompanionFiles:
    """Découvre les fichiers compagnons d'une save (DB, .ini, _SandboxVars, _spawnregions).

    Stratégie en cascade :
    1. **Match exact** sur ``save_name`` — cas standard, confiance totale.
    2. **Inférence** sinon, avec deux signaux croisés :
       a. *Set complet préféré* : un .ini accompagné de son _SandboxVars.lua ET
          de son _spawnregions.lua du même prefix bat un .ini orphelin.
       b. *Corrélation mtime* : PZ touche la save_dir, le .db et le .ini à chaque
          sauvegarde, donc leurs dates de modification sont alignées à la minute
          près. On prend le candidat avec le plus petit écart.
       c. *Cross-vérification db ↔ server* : si on a inféré ``server_prefix=X``
          et qu'il existe ``db/X.db``, on le prend en priorité (forte confiance).
    3. **Seuil de sécurité** : si même le meilleur candidat est modifié il y a
       plus de ``MTIME_INFERENCE_MAX_DELTA_SECONDS`` (90 jours) que la save_dir,
       on refuse d'inférer — mieux vaut un bundle sans config qu'un mauvais .ini.

    Couvre le cas où l'hôte a un **Server name** (par défaut "servertest") distinct
    du **World name** = ``save_name``.
    """
    root = root or zomboid_root()
    save_dir = root / "Saves" / "Multiplayer" / save_name
    server_dir = root / "Server"
    db_dir = root / "db"

    cf = CompanionFiles(
        save_dir=save_dir if save_dir.exists() else None,
        server_prefix=save_name,
        exact_match=True,
    )

    # --- Match exact d'abord ---
    exact_db = db_dir / f"{save_name}.db"
    if exact_db.exists():
        cf.db = exact_db
        cf.db_companions = _find_db_companions(exact_db)
    exact_ini = server_dir / f"{save_name}.ini"
    if exact_ini.exists():
        cf.ini = exact_ini
    exact_sandbox = server_dir / f"{save_name}_SandboxVars.lua"
    if exact_sandbox.exists():
        cf.sandbox = exact_sandbox
    exact_spawn = server_dir / f"{save_name}_spawnregions.lua"
    if exact_spawn.exists():
        cf.spawn = exact_spawn
    exact_spawn_points = server_dir / f"{save_name}_spawnpoints.lua"
    if exact_spawn_points.exists():
        cf.spawn_points = exact_spawn_points

    if cf.db is not None or cf.ini is not None:
        return cf  # match exact partiel ou complet → on garde

    # --- Inférence : aucun match exact ---
    if not save_dir.exists():
        return cf  # rien à corréler
    save_mtime = save_dir.stat().st_mtime

    best_set = _pick_best_server_set(_scan_server_sets(server_dir), save_mtime)
    # Pour le .db : on cherche d'abord un match avec le prefix du set Server
    # retenu ; sinon mtime correlation pure ; sinon None.
    preferred_prefix = best_set.prefix if best_set is not None else save_name
    inferred_db = _pick_db_for_prefix(db_dir, preferred_prefix, save_mtime)

    if best_set is None and inferred_db is None:
        return cf  # rien d'utilisable

    cf.exact_match = False
    if best_set is not None:
        cf.ini = best_set.ini
        cf.sandbox = best_set.sandbox
        cf.spawn = best_set.spawn
        cf.spawn_points = best_set.spawn_points
        cf.server_prefix = best_set.prefix
    if inferred_db is not None:
        cf.db = inferred_db
        cf.db_companions = _find_db_companions(inferred_db)
        # Si pas de set Server trouvé, on prend le stem du .db comme prefix
        if best_set is None:
            cf.server_prefix = inferred_db.stem

    return cf


def find_companions(save_name: str, root: Path | None = None) -> dict[str, Path]:
    """Retourne les chemins des fichiers compagnons existants pour une save.

    Wrapper rétro-compatible autour de ``discover_companion_files`` — détecte
    aussi les fichiers Server/DB sous un prefix différent de ``save_name``.
    """
    cf = discover_companion_files(save_name, root)
    found: dict[str, Path] = {}
    if cf.save_dir is not None:
        found["save_dir"] = cf.save_dir
    if cf.db is not None:
        found["db"] = cf.db
    for comp in cf.db_companions:
        # Clé du genre "db_wal" / "db_shm" / "db_journal" (suffix après ".db-")
        tag = comp.name.rsplit(".db-", 1)[-1] if ".db-" in comp.name else comp.name
        found[f"db_{tag}"] = comp
    if cf.ini is not None:
        found["server_ini"] = cf.ini
    if cf.sandbox is not None:
        found["server_SandboxVars.lua"] = cf.sandbox
    if cf.spawn is not None:
        found["server_spawnregions.lua"] = cf.spawn
    if cf.spawn_points is not None:
        found["server_spawnpoints.lua"] = cf.spawn_points
    return found


def build_bundle(
    save_name: str,
    out_zip: Path,
    created_by: str,
    note: str = "",
    root: Path | None = None,
    progress: ProgressCb | None = None,
) -> BundleManifest:
    """Crée un bundle zip à partir d'une save locale (écriture atomique).

    Si `progress` est fourni, il est appelé pendant le zip avec :
        progress("zip", fichiers_traités, fichiers_totaux)
    Et à la fin :
        progress("hash", 1, 1)
    """
    _validate_save_name(save_name)
    root = root or zomboid_root()
    save_dir = root / "Saves" / "Multiplayer" / save_name
    if not save_dir.exists():
        raise FileNotFoundError(
            f"Save '{save_name}' introuvable sous {save_dir}. "
            "Vérifie que tu as bien hébergé/joué cette partie au moins une fois."
        )

    cf = discover_companion_files(save_name, root)
    # Les noms des fichiers dans le bundle sont TOUJOURS sous {save_name}.ext,
    # même si chez l'hôte le prefix réel est différent (ex: "servertest").
    # Côté destinataire, ça garantit que la save extraite est cohérente.
    db_target_name = f"{save_name}.db"
    # Paires (chemin_source, nom_dans_bundle) pour les fichiers SQLite compagnons.
    # On garde la même base de nom (renommée sous save_name) + suffixe -wal/-shm/-journal.
    db_companion_pairs: list[tuple[Path, str]] = []
    if cf.db is not None:
        for comp in cf.db_companions:
            # extension genre ".db-wal" → on garde le même suffixe sous save_name
            for sfx in _DB_COMPANION_SUFFIXES:
                if comp.name.endswith(".db" + sfx):
                    db_companion_pairs.append((comp, f"{save_name}.db{sfx}"))
                    break

    server_pairs: list[tuple[Path, str]] = []
    if cf.ini is not None:
        server_pairs.append((cf.ini, f"{save_name}.ini"))
    if cf.sandbox is not None:
        server_pairs.append((cf.sandbox, f"{save_name}_SandboxVars.lua"))
    if cf.spawn is not None:
        server_pairs.append((cf.spawn, f"{save_name}_spawnregions.lua"))
    if cf.spawn_points is not None:
        server_pairs.append((cf.spawn_points, f"{save_name}_spawnpoints.lua"))

    # Pré-scan pour avoir le total de fichiers (pour la barre de progression)
    if progress:
        progress("scan", 0, 1)
    save_files_list = [f for f in save_dir.rglob("*") if f.is_file()]

    # Sanity check : refuser de pousser une save vide.
    # PZ écrit toujours au minimum les fichiers de chunk + metadata après
    # une session jouée. Une save_dir sans fichier = corruption ou mauvaise
    # sélection — un push enverrait du vide chez le pote, qui ne pourrait
    # plus rien faire (et perdrait son propre état au pull si keep_last_n=1).
    if not save_files_list:
        raise ValueError(
            f"La save '{save_name}' est vide : 0 fichier dans "
            f"{save_dir}. Refusé pour éviter de pousser du vide chez ton pote. "
            "Lance PZ → joue 5 minutes → re-tente le push."
        )

    extra_count = (1 if cf.db else 0) + len(db_companion_pairs) + len(server_pairs)
    total = len(save_files_list) + extra_count
    if progress:
        progress("scan", total, total)

    out_zip.parent.mkdir(parents=True, exist_ok=True)
    manifest = BundleManifest(
        bundle_version=BUNDLE_VERSION,
        save_name=save_name,
        created_at=dt.datetime.now().isoformat(timespec="seconds"),
        created_by=created_by,
        note=note,
        has_db=cf.db is not None,
        inferred_server_prefix=cf.server_prefix if not cf.exact_match else "",
    )

    # Extraction des mods depuis le .ini (avant écriture pour les avoir dans le manifest)
    if cf.ini is not None:
        manifest.mods, manifest.workshop_items = parse_ini_mods(cf.ini)

    # Écriture atomique : on écrit dans .tmp puis on rename
    tmp_zip = out_zip.with_suffix(out_zip.suffix + ".tmp")
    done = 0
    try:
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            # Save folder
            for file in save_files_list:
                rel = file.relative_to(save_dir)
                zf.write(file, f"save/{rel.as_posix()}")
                manifest.save_files += 1
                manifest.save_bytes += file.stat().st_size
                done += 1
                if progress and done % 8 == 0:
                    progress("zip", done, total)

            # DB (renommé sous {save_name}.db même si chez l'hôte c'est ex: servertest.db)
            if cf.db is not None:
                zf.write(cf.db, f"db/{db_target_name}")
                done += 1
                if progress:
                    progress("zip", done, total)

            # DB SQLite companions (.db-wal / .db-shm / .db-journal)
            for src_path, target_name in db_companion_pairs:
                zf.write(src_path, f"db/{target_name}")
                done += 1
                if progress:
                    progress("zip", done, total)

            # Server config files (renommés sous {save_name}.<ext>)
            for src_path, target_name in server_pairs:
                zf.write(src_path, f"server/{target_name}")
                manifest.server_files.append(target_name)
                done += 1
                if progress:
                    progress("zip", done, total)

            # Manifest provisoire (sans sha256 encore — il sera ré-écrit après hash)
            zf.writestr(MANIFEST_FILENAME, json.dumps(manifest.to_dict(), indent=2))

        # Calculer le hash du contenu (hors manifest) et réécrire le manifest avec
        if progress:
            progress("hash", 0, 1)
        manifest.sha256 = _sha256_of_zip_content(tmp_zip)
        # Réécrire le manifest dans le zip avec le sha256
        _rewrite_manifest_in_zip(tmp_zip, manifest)
        if progress:
            progress("hash", 1, 1)

        os.replace(tmp_zip, out_zip)
    except Exception:
        try:
            tmp_zip.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    return manifest


def _rewrite_manifest_in_zip(zip_path: Path, manifest: BundleManifest) -> None:
    """Réécrit le manifest dans un zip existant en préservant le reste.

    zipfile ne sait pas modifier en place ; on recopie dans un nouveau zip puis on remplace.
    """
    tmp = zip_path.with_suffix(zip_path.suffix + ".rwm.tmp")
    try:
        with zipfile.ZipFile(zip_path, "r") as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                if item.filename == MANIFEST_FILENAME:
                    continue
                dst.writestr(item, src.read(item.filename))
            dst.writestr(MANIFEST_FILENAME, json.dumps(manifest.to_dict(), indent=2))
        os.replace(tmp, zip_path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def read_manifest(zip_path: Path) -> BundleManifest:
    """Lit et VALIDE le manifest d'un bundle."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = set(zf.namelist())
        if MANIFEST_FILENAME not in names:
            raise ValueError(
                "Ce zip ne contient pas de bundle_manifest.json — ce n'est pas un bundle PZSaveSync valide."
            )
        with zf.open(MANIFEST_FILENAME) as fp:
            try:
                data = json.loads(fp.read().decode("utf-8"))
            except json.JSONDecodeError as e:
                raise ValueError(f"Manifest JSON invalide : {e}")

    if not isinstance(data, dict):
        raise ValueError("Manifest invalide (pas un objet JSON).")
    missing = [k for k in _REQUIRED_MANIFEST_FIELDS if k not in data]
    if missing:
        raise ValueError(f"Manifest incomplet, champs manquants : {missing}")
    # Validation du save_name AVANT toute utilisation
    _validate_save_name(str(data["save_name"]))

    # Filtrer aux seuls champs connus de la dataclass (compat anciens manifestes)
    known = set(BundleManifest.__dataclass_fields__.keys())
    filtered = {k: v for k, v in data.items() if k in known}
    try:
        return BundleManifest(**filtered)
    except TypeError as e:
        raise ValueError(f"Manifest invalide : {e}")


@dataclass
class ExtractReport:
    save_name: str
    save_dir: Path
    db_path: Path | None
    server_files: list[Path]
    backed_up_to: Path | None
    mods: list[str] = field(default_factory=list)
    workshop_items: list[str] = field(default_factory=list)


def verify_bundle_integrity(zip_path: Path) -> tuple[bool, str]:
    """Vérifie le hash SHA256 du bundle contre celui du manifest.

    Renvoie (ok, message). Si le manifest n'a pas de champ sha256 (anciens
    bundles v1), renvoie (True, "manifest sans sha256 — vérification ignorée").
    """
    try:
        manifest = read_manifest(zip_path)
    except ValueError as e:
        return False, f"Manifest invalide : {e}"
    if not manifest.sha256:
        return True, "manifest sans sha256 (bundle v1) — vérification ignorée"
    actual = _sha256_of_zip_content(zip_path)
    if actual != manifest.sha256:
        return False, f"Hash SHA256 ne correspond pas (bundle peut-être corrompu pendant la synchro cloud)"
    return True, "hash SHA256 OK"


def extract_bundle(
    zip_path: Path,
    root: Path | None = None,
    backup_dir: Path | None = None,
    verify_hash: bool = True,
    allow_no_backup: bool = False,
) -> ExtractReport:
    """Extrait un bundle dans la bonne arborescence Zomboid du destinataire.

    - Validation save_name + protection contre zip slip.
    - Vérification du hash SHA256 contre le manifest (depuis bundle v2).
    - Backup automatique des fichiers qui seraient écrasés (save_dir, db,
      fichiers server) dans backup_dir/<timestamp>/...
    - Écriture atomique de chaque fichier (tmp + rename).

    SÉCURITÉ : ``backup_dir`` est OBLIGATOIRE par défaut — l'extraction écrase
    la save_dir locale, donc sans backup on perd définitivement la progression
    du destinataire. Pour bypass (tests, scripts éphémères), passer
    ``allow_no_backup=True`` explicitement.
    """
    root = root or zomboid_root()
    if backup_dir is None and not allow_no_backup:
        raise ValueError(
            "backup_dir est obligatoire — l'extraction écrase la save locale. "
            "Passe un dossier de backup (ex: ~/PZSaveSync_LocalBackups) ou "
            "allow_no_backup=True si tu sais ce que tu fais."
        )
    manifest = read_manifest(zip_path)
    save_name = manifest.save_name
    _validate_save_name(save_name)

    # Anti zip-bomb : vérifier taille compressée + décompressée + nombre de fichiers
    try:
        compressed_size = zip_path.stat().st_size
    except OSError:
        compressed_size = 0
    if compressed_size > MAX_BUNDLE_SIZE_BYTES:
        raise ValueError(
            f"Bundle trop gros ({compressed_size / 1024 / 1024 / 1024:.1f} GB > "
            f"{MAX_BUNDLE_SIZE_BYTES / 1024 / 1024 / 1024:.0f} GB). "
            f"Risque de saturation disque — extraction refusée."
        )

    with zipfile.ZipFile(zip_path, "r") as zf:
        infos = zf.infolist()
        if len(infos) > MAX_FILES_IN_BUNDLE:
            raise ValueError(
                f"Bundle suspect : {len(infos)} fichiers (max {MAX_FILES_IN_BUNDLE}). "
                f"Extraction refusée."
            )
        total_uncompressed = sum(i.file_size for i in infos)
        if total_uncompressed > MAX_UNCOMPRESSED_SIZE_BYTES:
            raise ValueError(
                f"Bundle suspect : décompressé {total_uncompressed / 1024 / 1024 / 1024:.1f} GB > "
                f"{MAX_UNCOMPRESSED_SIZE_BYTES / 1024 / 1024 / 1024:.0f} GB. "
                f"Risque de saturation disque — extraction refusée."
            )

    if verify_hash:
        ok, msg = verify_bundle_integrity(zip_path)
        if not ok:
            raise ValueError(
                f"Bundle corrompu : {msg}. "
                "Re-synchronise ton dossier partagé et réessaie, "
                "ou demande à ton pote de re-pousser la version."
            )

    save_dir = root / "Saves" / "Multiplayer" / save_name
    db_path = root / "db" / f"{save_name}.db"
    server_dir = root / "Server"

    # ---- Backup ----
    backed_up_to: Path | None = None
    if backup_dir is not None:
        ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backed_up_to = backup_dir / f"pre_import_{save_name}_{ts}"
        backed_up_to.mkdir(parents=True, exist_ok=True)
        if save_dir.exists():
            shutil.make_archive(
                str(backed_up_to / "save"), "zip", root_dir=save_dir,
            )
        if db_path.exists():
            shutil.copy2(db_path, backed_up_to / db_path.name)
        # Backup des compagnons SQLite (.db-wal/.db-shm/.db-journal)
        for sfx in _DB_COMPANION_SUFFIXES:
            comp = db_path.with_name(db_path.name + sfx)
            if comp.exists():
                shutil.copy2(comp, backed_up_to / comp.name)
        for suffix in (".ini", "_SandboxVars.lua", "_spawnregions.lua", "_spawnpoints.lua"):
            f = server_dir / f"{save_name}{suffix}"
            if f.exists():
                shutil.copy2(f, backed_up_to / f.name)

    # ---- Effacement de l'ancien save_dir ----
    if save_dir.exists():
        shutil.rmtree(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    server_dir.mkdir(parents=True, exist_ok=True)
    (root / "db").mkdir(parents=True, exist_ok=True)

    # SÉCURITÉ SQLITE : on supprime les compagnons -wal/-shm/-journal résiduels
    # du destinataire AVANT d'extraire. Sinon, si le bundle ne contient pas de
    # wal mais que le destinataire en a un (correspondant à son ancienne .db
    # qu'on vient de remplacer), SQLite tenterait d'appliquer ce wal sur la
    # nouvelle .db → corruption. Le backup ci-dessus garde une copie.
    for sfx in _DB_COMPANION_SUFFIXES:
        stale = db_path.with_name(db_path.name + sfx)
        if stale.exists():
            try:
                stale.unlink()
            except OSError:
                pass

    extracted_db: Path | None = None
    extracted_server: list[Path] = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if name == MANIFEST_FILENAME:
                continue
            if name.endswith("/"):
                continue
            posix = name.replace("\\", "/")

            if posix.startswith("save/"):
                rel = posix[len("save/"):]
                target = _safe_join(save_dir, rel)
                _atomic_extract_file(zf, name, target)

            elif posix.startswith("db/"):
                fname = Path(posix).name
                target = _safe_join(root / "db", fname)
                _atomic_extract_file(zf, name, target)
                # Le .db principal (pas un compagnon -wal/-shm/-journal)
                if not any(fname.endswith(".db" + sfx) for sfx in _DB_COMPANION_SUFFIXES):
                    extracted_db = target

            elif posix.startswith("server/"):
                fname = Path(posix).name
                target = _safe_join(server_dir, fname)
                _atomic_extract_file(zf, name, target)
                extracted_server.append(target)
            # else: fichier hors structure attendue → ignoré silencieusement

    return ExtractReport(
        save_name=save_name,
        save_dir=save_dir,
        db_path=extracted_db,
        server_files=extracted_server,
        backed_up_to=backed_up_to,
        mods=list(manifest.mods),
        workshop_items=list(manifest.workshop_items),
    )


def _format_mods_summary(mods: list[str], workshop_items: list[str]) -> list[str]:
    """Lignes de résumé des mods/IDs Workshop pour summarize_manifest."""
    lines: list[str] = []
    if mods:
        if len(mods) <= 5:
            lines.append(f"Mods        : {', '.join(mods)}")
        else:
            preview = ", ".join(mods[:5])
            lines.append(f"Mods        : {len(mods)} ({preview}, +{len(mods)-5})")
    else:
        lines.append("Mods        : aucun listé")
    if workshop_items:
        if len(workshop_items) <= 5:
            lines.append(f"Workshop IDs: {', '.join(workshop_items)}")
        else:
            preview = ", ".join(workshop_items[:5])
            lines.append(
                f"Workshop IDs: {len(workshop_items)} ({preview}, +{len(workshop_items)-5})"
            )
    return lines


def summarize_manifest(m: BundleManifest) -> str:
    lines = [
        f"Save        : {m.save_name}",
        f"Créé par    : {m.created_by}",
        f"Date        : {m.created_at}",
        f"Fichiers    : {m.save_files} ({m.save_bytes / 1024 / 1024:.1f} MB)",
        f"DB joueurs  : {'oui' if m.has_db else 'NON'}",
        f"Config srv  : {', '.join(m.server_files) if m.server_files else 'aucune'}",
    ]
    lines.extend(_format_mods_summary(m.mods, m.workshop_items))
    if m.note:
        lines.append(f"Note        : {m.note}")
    return "\n".join(lines)

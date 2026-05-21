"""Bundle PZ = save complète prête à être passée à un pote.

Structure du zip :
    bundle_manifest.json
    save/                          → Zomboid/Saves/Multiplayer/<save_name>/
        ... (contenu du dossier save)
    db/<save_name>.db              → Zomboid/db/<save_name>.db
    server/
        <save_name>.ini            → Zomboid/Server/<save_name>.ini
        <save_name>_SandboxVars.lua
        <save_name>_spawnregions.lua

Le manifest porte le nom de la save d'origine, donc l'extraction restaure dans
le BON dossier chez le destinataire même si lui n'a jamais eu cette save avant.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path


MANIFEST_FILENAME = "bundle_manifest.json"
BUNDLE_VERSION = 1
_REQUIRED_MANIFEST_FIELDS = ("bundle_version", "save_name", "created_at", "created_by")
_BAD_NAME_CHARS = '<>:"/\\|?*'


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

    def to_dict(self) -> dict:
        return asdict(self)


def zomboid_root() -> Path:
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


def parse_ini_mods(ini_path: Path) -> tuple[list[str], list[str]]:
    """Extrait Mods= et WorkshopItems= depuis un .ini PZ.

    Retourne (mods, workshop_ids). Tolérant aux erreurs : retourne des listes
    vides si le fichier n'existe pas ou ne peut pas être lu.
    """
    mods: list[str] = []
    workshop_ids: list[str] = []
    try:
        text = ini_path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, FileNotFoundError):
        return mods, workshop_ids
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Mods="):
            mods = [m.strip() for m in line[len("Mods="):].split(";") if m.strip()]
        elif line.startswith("WorkshopItems="):
            workshop_ids = [
                w.strip() for w in line[len("WorkshopItems="):].split(";") if w.strip()
            ]
    return mods, workshop_ids


def find_companions(save_name: str, root: Path | None = None) -> dict[str, Path]:
    """Retourne les chemins des fichiers compagnons existants pour une save."""
    root = root or zomboid_root()
    found: dict[str, Path] = {}
    save_dir = root / "Saves" / "Multiplayer" / save_name
    if save_dir.exists():
        found["save_dir"] = save_dir
    db = root / "db" / f"{save_name}.db"
    if db.exists():
        found["db"] = db
    server_dir = root / "Server"
    for suffix in (".ini", "_SandboxVars.lua", "_spawnregions.lua"):
        f = server_dir / f"{save_name}{suffix}"
        if f.exists():
            found[f"server_{suffix.lstrip('.').replace('_', '')}"] = f
    return found


def build_bundle(
    save_name: str,
    out_zip: Path,
    created_by: str,
    note: str = "",
    root: Path | None = None,
) -> BundleManifest:
    """Crée un bundle zip à partir d'une save locale (écriture atomique)."""
    _validate_save_name(save_name)
    root = root or zomboid_root()
    save_dir = root / "Saves" / "Multiplayer" / save_name
    if not save_dir.exists():
        raise FileNotFoundError(
            f"Save '{save_name}' introuvable sous {save_dir}. "
            "Vérifie que tu as bien hébergé/joué cette partie au moins une fois."
        )

    server_dir = root / "Server"
    db_path = root / "db" / f"{save_name}.db"
    ini_path = server_dir / f"{save_name}.ini"

    out_zip.parent.mkdir(parents=True, exist_ok=True)
    manifest = BundleManifest(
        bundle_version=BUNDLE_VERSION,
        save_name=save_name,
        created_at=dt.datetime.now().isoformat(timespec="seconds"),
        created_by=created_by,
        note=note,
        has_db=db_path.exists(),
    )

    # Extraction des mods depuis le .ini (avant écriture pour les avoir dans le manifest)
    if ini_path.exists():
        manifest.mods, manifest.workshop_items = parse_ini_mods(ini_path)

    # Écriture atomique : on écrit dans .tmp puis on rename
    tmp_zip = out_zip.with_suffix(out_zip.suffix + ".tmp")
    try:
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            # Save folder
            for file in save_dir.rglob("*"):
                if file.is_file():
                    rel = file.relative_to(save_dir)
                    zf.write(file, f"save/{rel.as_posix()}")
                    manifest.save_files += 1
                    manifest.save_bytes += file.stat().st_size

            # DB
            if db_path.exists():
                zf.write(db_path, f"db/{db_path.name}")

            # Server config files
            for suffix in (".ini", "_SandboxVars.lua", "_spawnregions.lua"):
                f = server_dir / f"{save_name}{suffix}"
                if f.exists():
                    zf.write(f, f"server/{f.name}")
                    manifest.server_files.append(f.name)

            # Manifest en dernier (toujours présent)
            zf.writestr(MANIFEST_FILENAME, json.dumps(manifest.to_dict(), indent=2))

        os.replace(tmp_zip, out_zip)
    except Exception:
        try:
            tmp_zip.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    return manifest


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


def extract_bundle(
    zip_path: Path,
    root: Path | None = None,
    backup_dir: Path | None = None,
) -> ExtractReport:
    """Extrait un bundle dans la bonne arborescence Zomboid du destinataire.

    - Validation save_name + protection contre zip slip.
    - Backup automatique des fichiers qui seraient écrasés (save_dir, db,
      fichiers server) dans backup_dir/<timestamp>/...
    - Écriture atomique de chaque fichier (tmp + rename).
    """
    root = root or zomboid_root()
    manifest = read_manifest(zip_path)
    save_name = manifest.save_name
    _validate_save_name(save_name)

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
        for suffix in (".ini", "_SandboxVars.lua", "_spawnregions.lua"):
            f = server_dir / f"{save_name}{suffix}"
            if f.exists():
                shutil.copy2(f, backed_up_to / f.name)

    # ---- Effacement de l'ancien save_dir ----
    if save_dir.exists():
        shutil.rmtree(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    server_dir.mkdir(parents=True, exist_ok=True)
    (root / "db").mkdir(parents=True, exist_ok=True)

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

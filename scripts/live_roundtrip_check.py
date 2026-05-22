"""Round-trip de validation sur la VRAIE save de l'utilisateur (read-only).

Sans toucher à la save originale, on :
1. Crée un bundle dans un dossier temporaire (le builder lit seulement).
2. Vérifie le manifest : DB joueurs présente, fichiers serveur, spawnpoints, etc.
3. Extrait dans un autre dossier temporaire (fake Zomboid).
4. Hash tous les fichiers d'origine et du résultat → doivent matcher exactement.
5. Affiche le rapport.

Usage : python scripts\\live_roundtrip_check.py [save_name]
        Si save_name omis, prend la première save Multiplayer trouvée qui
        est jouable côté serveur.
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

# UTF-8 sur stdout — sinon Windows cp1252 plante sur les flèches/✓
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

# Permet de lancer directement (pas en mode -m)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pzsavesync import bundle as bundle_mod
from pzsavesync import saves as saves_mod


def file_hash(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in sorted(root.rglob("*")):
        if f.is_file():
            out[f.relative_to(root).as_posix()] = file_hash(f)
    return out


def main(target_save: str | None = None) -> int:
    zomboid = saves_mod.zomboid_root()
    if not zomboid.exists():
        print(f"❌ Pas de dossier Zomboid sous {zomboid}")
        return 1

    saves_list = saves_mod.list_all_with_info()
    transferable = [s for s in saves_list if s.transferable]
    if not transferable:
        print("❌ Aucune save serveur transférable trouvée.")
        return 1

    if target_save:
        match = next((s for s in transferable if s.name == target_save), None)
        if not match:
            print(f"❌ Save '{target_save}' introuvable ou non-transférable.")
            print("Saves serveur dispo :")
            for s in transferable:
                print(f"   • {s.name}")
            return 1
    else:
        match = transferable[0]

    save_name = match.name
    save_dir_src = zomboid / "Saves" / "Multiplayer" / save_name
    print(f"== Save ciblée : {save_name} ({match.info.size_mb:.1f} MB, "
          f"{match.info.file_count} fichiers, {match.info.chunkdata_files} chunks) ==")

    cf = bundle_mod.discover_companion_files(save_name)
    print(f"\nCompanion files découverts :")
    print(f"   server_prefix  : {cf.server_prefix} "
          f"(exact_match={cf.exact_match})")
    print(f"   db             : {cf.db}")
    print(f"   db_companions  : {[c.name for c in cf.db_companions] or '(aucun)'}")
    print(f"   .ini           : {cf.ini}")
    print(f"   _SandboxVars   : {cf.sandbox}")
    print(f"   _spawnregions  : {cf.spawn}")
    print(f"   _spawnpoints   : {cf.spawn_points or '(aucun)'}")

    with tempfile.TemporaryDirectory(prefix="pzsavesync_roundtrip_") as td:
        td_path = Path(td)
        bundle_path = td_path / f"bundle_{save_name}.zip"
        fake_zomboid = td_path / "fake_pote_zomboid"

        # ==== 1. Build ====
        print(f"\n== 1) Build bundle → {bundle_path.name} ==")
        manifest = bundle_mod.build_bundle(
            save_name=save_name,
            out_zip=bundle_path,
            created_by="local_check",
            note="round-trip validation",
        )
        size_mb = bundle_path.stat().st_size / 1024 / 1024
        print(f"   ✓ Bundle créé ({size_mb:.1f} MB compressé)")
        print(f"   - save_files     : {manifest.save_files}")
        print(f"   - save_bytes     : {manifest.save_bytes/1024/1024:.1f} MB")
        print(f"   - has_db         : {manifest.has_db}")
        print(f"   - server_files   : {manifest.server_files}")
        print(f"   - inferred_prefix: {manifest.inferred_server_prefix or '(exact match)'}")
        print(f"   - mods           : {len(manifest.mods)} listés")
        print(f"   - workshop_ids   : {len(manifest.workshop_items)} listés")
        print(f"   - sha256         : {manifest.sha256[:16]}...")

        # ==== 2. Hash de la source ====
        print(f"\n== 2) Hash de la save d'origine (sans toucher au PC hôte) ==")
        src_hashes_save = hash_tree(save_dir_src)
        print(f"   ✓ {len(src_hashes_save)} fichiers hashés dans save_dir")
        src_extra: dict[str, str] = {}
        if cf.db is not None:
            src_extra[f"db/{cf.db.name}"] = file_hash(cf.db)
        for comp in cf.db_companions:
            src_extra[f"db/{comp.name}"] = file_hash(comp)
        for p in cf.server_files:
            src_extra[f"server/{p.name}"] = file_hash(p)
        print(f"   ✓ {len(src_extra)} fichiers compagnons hashés")

        # ==== 3. Extract dans un fake Zomboid (vide) ====
        print(f"\n== 3) Extract dans un fake Zomboid (côté pote simulé) ==")
        backup_dir = td_path / "backup"
        report = bundle_mod.extract_bundle(
            zip_path=bundle_path,
            root=fake_zomboid,
            backup_dir=backup_dir,
            verify_hash=True,
        )
        print(f"   ✓ Save extraite : {report.save_dir}")
        print(f"   ✓ DB extraite   : {report.db_path}")
        print(f"   ✓ Server files  : {len(report.server_files)} fichier(s)")
        for f in report.server_files:
            print(f"      • {f.name}")

        # ==== 4. Hash du résultat ====
        print(f"\n== 4) Hash du résultat côté 'pote' ==")
        dst_save = fake_zomboid / "Saves" / "Multiplayer" / save_name
        dst_hashes_save = hash_tree(dst_save)
        print(f"   ✓ {len(dst_hashes_save)} fichiers hashés dans save_dir")
        dst_extra: dict[str, str] = {}
        dst_db = fake_zomboid / "db" / f"{save_name}.db"
        if dst_db.exists():
            dst_extra[f"db/{dst_db.name}"] = file_hash(dst_db)
        # Companions SQLite si présents
        for sfx in bundle_mod._DB_COMPANION_SUFFIXES:
            comp = dst_db.with_name(dst_db.name + sfx)
            if comp.exists():
                dst_extra[f"db/{comp.name}"] = file_hash(comp)
        for suffix in (".ini", "_SandboxVars.lua", "_spawnregions.lua", "_spawnpoints.lua"):
            f = fake_zomboid / "Server" / f"{save_name}{suffix}"
            if f.exists():
                dst_extra[f"server/{f.name}"] = file_hash(f)
        print(f"   ✓ {len(dst_extra)} fichiers compagnons hashés")

        # ==== 5. Comparaison ====
        print(f"\n== 5) Comparaison hash par hash ==")
        errors: list[str] = []

        # Save dir
        src_keys = set(src_hashes_save.keys())
        dst_keys = set(dst_hashes_save.keys())
        missing_in_dst = src_keys - dst_keys
        extra_in_dst = dst_keys - src_keys
        if missing_in_dst:
            errors.append(f"⚠ {len(missing_in_dst)} fichier(s) save MANQUANT(S) côté pote :")
            for k in sorted(missing_in_dst)[:10]:
                errors.append(f"    - {k}")
        if extra_in_dst:
            errors.append(f"⚠ {len(extra_in_dst)} fichier(s) save EN TROP côté pote :")
            for k in sorted(extra_in_dst)[:10]:
                errors.append(f"    - {k}")
        diff_save = [
            k for k in src_keys & dst_keys
            if src_hashes_save[k] != dst_hashes_save[k]
        ]
        if diff_save:
            errors.append(f"⚠ {len(diff_save)} fichier(s) save avec HASH DIFFÉRENT :")
            for k in diff_save[:10]:
                errors.append(f"    - {k}")

        # Companions (renommage attendu : si server_prefix != save_name, on
        # compare l'hash mais pas le nom)
        # Construction des hashes par identification (db, ini, sandbox, spawn, spawnpoints)
        def classify(key: str) -> str | None:
            # ex: "db/Gitano_Z.db" → "db"
            #     "db/Gitano_Z.db-wal" → "db-wal"
            #     "server/Gitano_Z.ini" → "ini"
            #     "server/Gitano_Z_SandboxVars.lua" → "sandbox"
            #     etc.
            if key.startswith("db/"):
                tail = key[3:]
                for sfx in bundle_mod._DB_COMPANION_SUFFIXES:
                    if tail.endswith(".db" + sfx):
                        return f"db{sfx}"
                if tail.endswith(".db"):
                    return "db"
            if key.startswith("server/"):
                tail = key[7:]
                if tail.endswith("_SandboxVars.lua"):
                    return "sandbox"
                if tail.endswith("_spawnregions.lua"):
                    return "spawnregions"
                if tail.endswith("_spawnpoints.lua"):
                    return "spawnpoints"
                if tail.endswith(".ini"):
                    return "ini"
            return None

        src_by_kind = {classify(k): h for k, h in src_extra.items() if classify(k)}
        dst_by_kind = {classify(k): h for k, h in dst_extra.items() if classify(k)}
        all_kinds = set(src_by_kind.keys()) | set(dst_by_kind.keys())
        for kind in sorted(all_kinds):
            if kind not in dst_by_kind:
                errors.append(f"⚠ Companion '{kind}' présent côté hôte mais MANQUANT côté pote")
            elif kind not in src_by_kind:
                errors.append(f"⚠ Companion '{kind}' EN TROP côté pote (pas chez l'hôte)")
            elif src_by_kind[kind] != dst_by_kind[kind]:
                errors.append(f"⚠ Companion '{kind}' a un HASH DIFFÉRENT")

        if errors:
            print("\n❌ ROUND-TRIP ÉCHOUÉ :")
            for e in errors:
                print(f"   {e}")
            return 2

        total_files = len(src_hashes_save) + len(src_extra)
        print(f"   ✅ {total_files} fichiers identiques bit-à-bit côté pote.")
        print(f"\n✅ ROUND-TRIP OK — la save peut être pushée sans risque de perte.")
        print(f"   Bundle créé        : {bundle_path}")
        print(f"   Détruit à la sortie (dossier temporaire).")
        return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(main(target))

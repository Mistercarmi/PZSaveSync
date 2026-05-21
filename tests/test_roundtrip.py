"""Test bout-en-bout : export bundle, import sur 'autre PC', verifie l'integrite."""
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Force UTF-8 sur stdout pour eviter UnicodeEncodeError sur Windows cp1252
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pzsavesync import bundle as bundle_mod
from pzsavesync import inspector


def file_hash(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_dir(root: Path) -> dict[str, str]:
    out = {}
    for f in root.rglob("*"):
        if f.is_file():
            out[f.relative_to(root).as_posix()] = file_hash(f)
    return out


def make_fake_zomboid(root: Path, save_name: str):
    """Construit un faux Zomboid avec save+db+server pour simuler le PC d'un pote."""
    save_dir = root / "Saves" / "Multiplayer" / save_name
    save_dir.mkdir(parents=True)
    (save_dir / "map.bin").write_bytes(b"fake-map-data")
    (save_dir / "map_825_1155.bin").write_bytes(b"chunk1")
    (save_dir / "map_825_1156.bin").write_bytes(b"chunk2")
    (save_dir / "chunkdata_27_38.bin").write_bytes(b"cd1")
    (save_dir / "gos_campfire.bin").write_bytes(b"camp")
    (save_dir / "WorldDictionary.bin").write_bytes(b"mods-list-binary")
    sub = save_dir / "isoregiondata"
    sub.mkdir()
    (sub / "region_0.bin").write_bytes(b"region")

    (root / "db").mkdir()
    # vraie petite DB SQLite avec une table de joueurs
    import sqlite3
    db = root / "db" / f"{save_name}.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE whitelist(username TEXT)")
    con.executemany("INSERT INTO whitelist(username) VALUES (?)",
                    [("Player1",), ("Player2",)])
    con.commit()
    con.close()

    (root / "Server").mkdir()
    (root / "Server" / f"{save_name}.ini").write_text("Public=false\nMods=\n", encoding="utf-8")
    (root / "Server" / f"{save_name}_SandboxVars.lua").write_text(
        "SandboxVars = { Zombies = 3, }", encoding="utf-8"
    )
    (root / "Server" / f"{save_name}_spawnregions.lua").write_text(
        "function SpawnRegions() return {} end", encoding="utf-8"
    )


def main():
    save_name = "servertest"
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        host = td / "PC_HOTE"
        guest = td / "PC_POTE"
        host.mkdir(); guest.mkdir()

        print(f"== 1) Crée un faux Zomboid 'hôte' avec save {save_name} ==")
        make_fake_zomboid(host, save_name)

        print("== 2) Hash de l'état initial (hôte) ==")
        h_save = hash_dir(host / "Saves" / "Multiplayer" / save_name)
        h_db = file_hash(host / "db" / f"{save_name}.db")
        h_ini = file_hash(host / "Server" / f"{save_name}.ini")
        h_sb = file_hash(host / "Server" / f"{save_name}_SandboxVars.lua")
        h_sp = file_hash(host / "Server" / f"{save_name}_spawnregions.lua")

        print("== 3) Export du bundle depuis 'l'hôte' ==")
        bundle_zip = td / "bundle.zip"
        m = bundle_mod.build_bundle(
            save_name=save_name,
            out_zip=bundle_zip,
            created_by="TestHost",
            note="Session 1",
            root=host,
        )
        print(f"   bundle.zip : {bundle_zip.stat().st_size} octets")
        print(bundle_mod.summarize_manifest(m))
        assert m.has_db
        assert len(m.server_files) == 3

        print("== 4) Inspection (sans extraction) ==")
        m2 = bundle_mod.read_manifest(bundle_zip)
        assert m2.save_name == save_name
        info = inspector.inspect_zip(bundle_zip)
        print(inspector.format_info(info, "(bundle inspecté)"))

        print("== 5) Import sur 'PC_POTE' (vide au départ) ==")
        backups = td / "guest_backups"
        report = bundle_mod.extract_bundle(bundle_zip, root=guest, backup_dir=backups)
        print(f"   save_dir : {report.save_dir}")
        print(f"   db       : {report.db_path}")
        print(f"   server   : {report.server_files}")

        print("== 6) Vérifie que le PC_POTE a EXACTEMENT le même contenu ==")
        h_save2 = hash_dir(guest / "Saves" / "Multiplayer" / save_name)
        assert h_save == h_save2, "Save dir mismatch !"
        assert file_hash(guest / "db" / f"{save_name}.db") == h_db, "DB mismatch"
        assert file_hash(guest / "Server" / f"{save_name}.ini") == h_ini, "ini mismatch"
        assert file_hash(guest / "Server" / f"{save_name}_SandboxVars.lua") == h_sb, "sandbox mismatch"
        assert file_hash(guest / "Server" / f"{save_name}_spawnregions.lua") == h_sp, "spawnregions mismatch"
        print("   [OK] Tous les hash matchent. La save est intacte.")

        print("== 7) Le pote joue (modifie un fichier), re-export ==")
        (guest / "Saves" / "Multiplayer" / save_name / "map_825_1157.bin").write_bytes(b"chunk3-new")
        (guest / "Saves" / "Multiplayer" / save_name / "gos_campfire.bin").write_bytes(b"camp-modified")
        bundle_zip2 = td / "bundle2.zip"
        m3 = bundle_mod.build_bundle(
            save_name=save_name, out_zip=bundle_zip2,
            created_by="TestGuest", note="Session 2", root=guest,
        )
        print(f"   bundle2.zip : {bundle_zip2.stat().st_size} octets")

        print("== 8) Re-import sur l'hôte → vérifie qu'il récupère les modifs ==")
        backups2 = td / "host_backups"
        report2 = bundle_mod.extract_bundle(bundle_zip2, root=host, backup_dir=backups2)
        new_chunk = host / "Saves" / "Multiplayer" / save_name / "map_825_1157.bin"
        assert new_chunk.exists() and new_chunk.read_bytes() == b"chunk3-new"
        camp = host / "Saves" / "Multiplayer" / save_name / "gos_campfire.bin"
        assert camp.read_bytes() == b"camp-modified"
        # Backup créé
        assert report2.backed_up_to and report2.backed_up_to.exists()
        print(f"   [OK] Hôte a bien les modifs du pote")
        print(f"   [OK] Backup pré-import sauvegardé : {report2.backed_up_to}")

        print("\n=== ALL OK : cycle aller-retour validé ===")


if __name__ == "__main__":
    main()

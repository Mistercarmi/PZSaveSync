"""Tests pour les fixes v0.3.4 : ne rien perdre, tout récupérer côté pote.

Couvre :
- Fix #1 : `_spawnpoints.lua` embarqué et restauré.
- Fix #3 : fichiers SQLite compagnons (.db-wal/.db-shm/.db-journal) embarqués
           et restaurés.
- Fix #3-bis : nettoyage des compagnons SQLite résiduels chez le destinataire
              quand le bundle n'en a pas (sinon corruption SQLite).
- Fix #4 : `extract_bundle(backup_dir=None)` refusé sans `allow_no_backup=True`.
- Restore : un backup local peut être restauré et un pre-restore backup est créé.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from pzsavesync import bundle as bundle_mod
from pzsavesync import restore as restore_mod
from pzsavesync.sync import SharedRepo


def _make_layout(
    root: Path,
    save_name: str,
    *,
    with_spawnpoints: bool = False,
    with_db_wal: bool = False,
    with_db_shm: bool = False,
):
    """Crée une arborescence Zomboid factice, avec options spawnpoints/WAL/SHM."""
    save_dir = root / "Saves" / "Multiplayer" / save_name
    save_dir.mkdir(parents=True)
    (save_dir / "map_0_0.bin").write_bytes(b"chunk")
    (root / "db").mkdir(parents=True, exist_ok=True)
    (root / "db" / f"{save_name}.db").write_bytes(b"SQLite-fake")
    if with_db_wal:
        (root / "db" / f"{save_name}.db-wal").write_bytes(b"WAL-frame-pending")
    if with_db_shm:
        (root / "db" / f"{save_name}.db-shm").write_bytes(b"shared-mem")
    (root / "Server").mkdir(parents=True, exist_ok=True)
    (root / "Server" / f"{save_name}.ini").write_text("PVP=true\n", encoding="utf-8")
    (root / "Server" / f"{save_name}_SandboxVars.lua").write_text("v=1", encoding="utf-8")
    (root / "Server" / f"{save_name}_spawnregions.lua").write_text("v=1", encoding="utf-8")
    if with_spawnpoints:
        (root / "Server" / f"{save_name}_spawnpoints.lua").write_text(
            "function Spawnpoints() return { {x=10, y=20} } end", encoding="utf-8",
        )


# -----------------------------------------------------------------------------
# Fix #1 — _spawnpoints.lua
# -----------------------------------------------------------------------------

def test_spawnpoints_embedded_in_bundle(tmp_path):
    """Si _spawnpoints.lua existe côté hôte, il doit être dans le bundle."""
    _make_layout(tmp_path, "MaSave", with_spawnpoints=True)
    cf = bundle_mod.discover_companion_files("MaSave", root=tmp_path)
    assert cf.spawn_points is not None
    assert cf.spawn_points.name == "MaSave_spawnpoints.lua"

    out = tmp_path / "bundle.zip"
    m = bundle_mod.build_bundle("MaSave", out, "alice", root=tmp_path)
    assert "MaSave_spawnpoints.lua" in m.server_files

    with zipfile.ZipFile(out, "r") as zf:
        names = set(zf.namelist())
    assert "server/MaSave_spawnpoints.lua" in names


def test_spawnpoints_restored_on_extract(tmp_path):
    """Le _spawnpoints.lua doit arriver dans Server/ chez le pote."""
    src = tmp_path / "src"; src.mkdir()
    _make_layout(src, "MaSave", with_spawnpoints=True)
    out = tmp_path / "bundle.zip"
    bundle_mod.build_bundle("MaSave", out, "alice", root=src)

    dst = tmp_path / "dst"; dst.mkdir()
    backups = tmp_path / "backups"
    report = bundle_mod.extract_bundle(out, root=dst, backup_dir=backups)
    spp = dst / "Server" / "MaSave_spawnpoints.lua"
    assert spp.exists()
    assert b"x=10" in spp.read_bytes()
    assert spp in report.server_files


def test_spawnpoints_inferred_when_server_name_differs(tmp_path):
    """Si l'hôte utilise prefix 'servertest' avec un _spawnpoints.lua, on l'embarque
    sous le nom de la save du destinataire."""
    save_name = "Gitano_Z"
    save_dir = tmp_path / "Saves" / "Multiplayer" / save_name
    save_dir.mkdir(parents=True)
    (save_dir / "map_0_0.bin").write_bytes(b"chunk")
    (tmp_path / "db").mkdir(); (tmp_path / "Server").mkdir()
    prefix = "servertest"
    (tmp_path / "db" / f"{prefix}.db").write_bytes(b"db")
    (tmp_path / "Server" / f"{prefix}.ini").write_text("PVP=true", encoding="utf-8")
    (tmp_path / "Server" / f"{prefix}_SandboxVars.lua").write_text("v=1", encoding="utf-8")
    (tmp_path / "Server" / f"{prefix}_spawnregions.lua").write_text("v=1", encoding="utf-8")
    (tmp_path / "Server" / f"{prefix}_spawnpoints.lua").write_text("custom", encoding="utf-8")
    import os, time
    now = time.time()
    os.utime(save_dir, (now, now))
    for p in (tmp_path / "Server").iterdir():
        os.utime(p, (now, now))
    os.utime(tmp_path / "db" / f"{prefix}.db", (now, now))

    cf = bundle_mod.discover_companion_files(save_name, root=tmp_path)
    assert cf.spawn_points is not None
    assert cf.spawn_points.name == f"{prefix}_spawnpoints.lua"

    out = tmp_path / "bundle.zip"
    m = bundle_mod.build_bundle(save_name, out, "alice", root=tmp_path)
    # v0.4.0 fix bug map M : noms d'origine préservés (pas renommés sous save_name)
    assert f"{prefix}_spawnpoints.lua" in m.server_files
    with zipfile.ZipFile(out, "r") as zf:
        names = set(zf.namelist())
    # Sous nom d'origine, PAS renommé sous save_name
    assert f"server/{prefix}_spawnpoints.lua" in names
    assert f"server/{save_name}_spawnpoints.lua" not in names


# -----------------------------------------------------------------------------
# Fix #3 — SQLite WAL/SHM/journal
# -----------------------------------------------------------------------------

def test_db_wal_embedded_in_bundle(tmp_path):
    """Si .db-wal existe côté hôte, il est dans le bundle."""
    _make_layout(tmp_path, "MaSave", with_db_wal=True, with_db_shm=True)
    cf = bundle_mod.discover_companion_files("MaSave", root=tmp_path)
    assert len(cf.db_companions) == 2
    names = {c.name for c in cf.db_companions}
    assert "MaSave.db-wal" in names
    assert "MaSave.db-shm" in names

    out = tmp_path / "bundle.zip"
    bundle_mod.build_bundle("MaSave", out, "alice", root=tmp_path)
    with zipfile.ZipFile(out, "r") as zf:
        names = set(zf.namelist())
    assert "db/MaSave.db" in names
    assert "db/MaSave.db-wal" in names
    assert "db/MaSave.db-shm" in names


def test_db_wal_restored_on_extract(tmp_path):
    """Le .db-wal doit arriver chez le pote (sinon perte des dernières transactions)."""
    src = tmp_path / "src"; src.mkdir()
    _make_layout(src, "MaSave", with_db_wal=True)
    out = tmp_path / "bundle.zip"
    bundle_mod.build_bundle("MaSave", out, "alice", root=src)

    dst = tmp_path / "dst"; dst.mkdir()
    backups = tmp_path / "backups"
    bundle_mod.extract_bundle(out, root=dst, backup_dir=backups)
    wal = dst / "db" / "MaSave.db-wal"
    assert wal.exists()
    assert wal.read_bytes() == b"WAL-frame-pending"


def test_stale_db_wal_cleaned_when_bundle_has_none(tmp_path):
    """Anti-corruption SQLite : si le pote a un .db-wal résiduel et que le bundle
    n'en a pas, il faut le supprimer (backup d'abord) sinon SQLite l'appliquera
    sur la nouvelle .db → corruption."""
    src = tmp_path / "src"; src.mkdir()
    _make_layout(src, "MaSave", with_db_wal=False)  # bundle SANS wal
    out = tmp_path / "bundle.zip"
    bundle_mod.build_bundle("MaSave", out, "alice", root=src)

    dst = tmp_path / "dst"; dst.mkdir()
    _make_layout(dst, "MaSave", with_db_wal=True, with_db_shm=True)  # dest AVEC wal
    backups = tmp_path / "backups"
    bundle_mod.extract_bundle(out, root=dst, backup_dir=backups)
    # Le wal résiduel doit avoir disparu pour éviter mismatch
    assert not (dst / "db" / "MaSave.db-wal").exists()
    assert not (dst / "db" / "MaSave.db-shm").exists()
    # Mais il doit être dans le backup
    backup_subdirs = list(backups.iterdir())
    assert len(backup_subdirs) == 1
    backed = backup_subdirs[0]
    assert (backed / "MaSave.db-wal").exists()
    assert (backed / "MaSave.db-shm").exists()


# -----------------------------------------------------------------------------
# Fix #4 — backup_dir obligatoire
# -----------------------------------------------------------------------------

def test_extract_refuses_no_backup_by_default(tmp_path):
    """extract_bundle(backup_dir=None) doit lever ValueError par défaut."""
    src = tmp_path / "src"; src.mkdir()
    _make_layout(src, "MaSave")
    out = tmp_path / "bundle.zip"
    bundle_mod.build_bundle("MaSave", out, "alice", root=src)

    dst = tmp_path / "dst"; dst.mkdir()
    with pytest.raises(ValueError, match="backup_dir"):
        bundle_mod.extract_bundle(out, root=dst, backup_dir=None)


def test_extract_allows_no_backup_with_explicit_flag(tmp_path):
    """allow_no_backup=True permet le bypass (pour tests / scripts éphémères)."""
    src = tmp_path / "src"; src.mkdir()
    _make_layout(src, "MaSave")
    out = tmp_path / "bundle.zip"
    bundle_mod.build_bundle("MaSave", out, "alice", root=src)

    dst = tmp_path / "dst"; dst.mkdir()
    # Doit fonctionner avec allow_no_backup=True
    report = bundle_mod.extract_bundle(
        out, root=dst, backup_dir=None, allow_no_backup=True,
    )
    assert report.save_name == "MaSave"
    assert report.backed_up_to is None


# -----------------------------------------------------------------------------
# Fix #2 — prune par save_name (test au niveau sync.py + dans gui via wrapper)
# -----------------------------------------------------------------------------

def test_prune_scoped_to_save_name_preserves_other_saves(tmp_path):
    """Quand on prune avec save_name='A' et keep_last_n=1, la save B garde
    toutes ses versions (même si plus anciennes que les A pruned)."""
    import datetime as dt
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    versions = []
    # 5 versions de save A (du plus vieux au plus récent)
    for i in range(5):
        ts = (dt.datetime.now() - dt.timedelta(days=10 - i)).isoformat(timespec="seconds")
        versions.append({
            "filename": f"a{i}.zip", "save_name": "SaveA", "uploaded_by": "alice",
            "uploaded_at": ts, "size_bytes": 1024, "has_db": True,
            "server_files": [], "note": "",
        })
    # 1 version de save B, plus ancienne que la dernière A
    versions.append({
        "filename": "b0.zip", "save_name": "SaveB", "uploaded_by": "bob",
        "uploaded_at": (dt.datetime.now() - dt.timedelta(days=20)).isoformat(timespec="seconds"),
        "size_bytes": 1024, "has_db": True, "server_files": [], "note": "",
    })
    for v in versions:
        (repo.versions_dir / v["filename"]).write_bytes(b"x")
    data = repo._read_manifest()
    data["versions"] = versions
    repo._write_manifest(data)

    # Prune scoped à SaveA — keep_last_n=2 (le MIN_KEEP_LAST_N clamp)
    deleted = repo.prune_versions(keep_last_n=2, save_name="SaveA")
    remaining = repo.list_versions()
    remaining_names = {v.filename for v in remaining}
    # SaveB est PRÉSERVÉE
    assert "b0.zip" in remaining_names
    # SaveA : on garde les 2 plus récentes (a4 + a3)
    assert "a4.zip" in remaining_names
    assert "a3.zip" in remaining_names
    # Les autres SaveA sont supprimées
    assert len([n for n in remaining_names if n.startswith("a")]) == 2
    assert len(deleted) == 3  # a0..a2


def test_prune_unscoped_global_still_dangerous_for_other_saves(tmp_path):
    """Documente le risque résiduel : un prune global keep_last_n=2 supprime
    quand même les versions excédentaires toutes saves confondues. C'est
    pour ça que gui.py scope toujours par save_name à l'auto-prune.

    Note : depuis le clamp v0.3.5 (MIN_KEEP_LAST_N=2), N=1 et N=0 sont
    automatiquement remontés à 2 → 2 versions seront gardées dans ce test.
    """
    import datetime as dt
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    # 3 versions de SaveA récentes + 1 SaveB ancienne (4 au total)
    versions = [
        {"filename": "a0.zip", "save_name": "SaveA", "uploaded_by": "a",
         "uploaded_at": (dt.datetime.now() - dt.timedelta(days=3)).isoformat(timespec="seconds"),
         "size_bytes": 1, "has_db": True, "server_files": [], "note": ""},
        {"filename": "a1.zip", "save_name": "SaveA", "uploaded_by": "a",
         "uploaded_at": (dt.datetime.now() - dt.timedelta(days=2)).isoformat(timespec="seconds"),
         "size_bytes": 1, "has_db": True, "server_files": [], "note": ""},
        {"filename": "a2.zip", "save_name": "SaveA", "uploaded_by": "a",
         "uploaded_at": dt.datetime.now().isoformat(timespec="seconds"),
         "size_bytes": 1, "has_db": True, "server_files": [], "note": ""},
        {"filename": "b0.zip", "save_name": "SaveB", "uploaded_by": "b",
         "uploaded_at": (dt.datetime.now() - dt.timedelta(days=10)).isoformat(timespec="seconds"),
         "size_bytes": 1, "has_db": True, "server_files": [], "note": ""},
    ]
    for v in versions:
        (repo.versions_dir / v["filename"]).write_bytes(b"x")
    data = repo._read_manifest()
    data["versions"] = versions
    repo._write_manifest(data)

    # PRUNE GLOBAL keep_last_n=2 (toutes saves confondues)
    repo.prune_versions(keep_last_n=2)
    remaining = {v.filename for v in repo.list_versions()}
    # Garde les 2 plus récentes globalement → a2 + a1 ; b0 et a0 sautent
    assert "a2.zip" in remaining
    assert "a1.zip" in remaining
    assert "b0.zip" not in remaining  # ← preuve que le prune global peut tuer une autre save
    # → c'est pour ça que gui.py scope par save_name dans l'auto-prune.


# -----------------------------------------------------------------------------
# Restore module
# -----------------------------------------------------------------------------

def test_list_backups_finds_real_backups(tmp_path):
    """list_backups parse correctement les dossiers pre_import_*."""
    backup_root = tmp_path
    # Backup valide
    b1 = backup_root / "pre_import_Gitano_Z_20260522-143000"
    b1.mkdir()
    (b1 / "save.zip").write_bytes(b"save-archive")
    (b1 / "Gitano_Z.db").write_bytes(b"db")
    (b1 / "Gitano_Z.db-wal").write_bytes(b"wal")
    (b1 / "Gitano_Z.ini").write_text("PVP=true", encoding="utf-8")
    (b1 / "Gitano_Z_spawnpoints.lua").write_text("v", encoding="utf-8")
    # Dossier non-backup à ignorer
    (backup_root / "random_folder").mkdir()
    # Backup d'une autre save plus ancien
    b2 = backup_root / "pre_import_OtherSave_20260101-120000"
    b2.mkdir()
    (b2 / "save.zip").write_bytes(b"other")

    backups = restore_mod.list_backups(backup_root)
    assert len(backups) == 2
    # Tri par date desc
    assert backups[0].save_name == "Gitano_Z"
    assert backups[0].timestamp == "20260522-143000"
    assert backups[0].has_save_zip is True
    assert backups[0].has_db is True
    assert "Gitano_Z.db-wal" in backups[0].db_companions
    assert "Gitano_Z.ini" in backups[0].server_files
    assert "Gitano_Z_spawnpoints.lua" in backups[0].server_files
    assert backups[1].save_name == "OtherSave"


def test_restore_backup_round_trip(tmp_path):
    """Cycle complet : on simule un état, on backup via extract_bundle, on
    modifie l'état, puis on restore et on vérifie qu'on retrouve l'original."""
    root = tmp_path / "zomboid"; root.mkdir()
    _make_layout(root, "MaSave", with_spawnpoints=True, with_db_wal=True)

    # Capture l'état d'origine
    original_chunk = (root / "Saves" / "Multiplayer" / "MaSave" / "map_0_0.bin").read_bytes()
    original_db = (root / "db" / "MaSave.db").read_bytes()
    original_wal = (root / "db" / "MaSave.db-wal").read_bytes()
    original_ini = (root / "Server" / "MaSave.ini").read_bytes()
    original_spp = (root / "Server" / "MaSave_spawnpoints.lua").read_bytes()

    # Crée un bundle "frais" et l'extrait pour générer un backup automatique
    src = tmp_path / "src"; src.mkdir()
    _make_layout(src, "MaSave")  # version DIFFÉRENTE (pas de spawnpoints, pas de wal)
    (src / "Saves" / "Multiplayer" / "MaSave" / "map_0_0.bin").write_bytes(b"DIFFERENT")
    out = tmp_path / "bundle.zip"
    bundle_mod.build_bundle("MaSave", out, "intruder", root=src)
    backups_dir = tmp_path / "backups"
    bundle_mod.extract_bundle(out, root=root, backup_dir=backups_dir)
    # Maintenant root a la version "DIFFERENT"
    assert (root / "Saves" / "Multiplayer" / "MaSave" / "map_0_0.bin").read_bytes() == b"DIFFERENT"
    assert not (root / "db" / "MaSave.db-wal").exists()  # wal nettoyé (anti-corruption)
    # _spawnpoints.lua : extract_bundle ne l'efface pas s'il n'est pas dans
    # le bundle. Le restore va le ramener tel qu'il était au moment du backup.

    # Restore depuis le backup
    backups = restore_mod.list_backups(backups_dir)
    assert len(backups) == 1
    safety = tmp_path / "safety"
    report = restore_mod.restore_backup(
        backups[0], root=root, safety_backup_dir=safety,
    )
    # Vérifie qu'on a retrouvé l'original
    assert (root / "Saves" / "Multiplayer" / "MaSave" / "map_0_0.bin").read_bytes() == original_chunk
    assert (root / "db" / "MaSave.db").read_bytes() == original_db
    assert (root / "db" / "MaSave.db-wal").read_bytes() == original_wal
    assert (root / "Server" / "MaSave.ini").read_bytes() == original_ini
    assert (root / "Server" / "MaSave_spawnpoints.lua").read_bytes() == original_spp
    assert report.pre_restore_backup is not None
    assert report.pre_restore_backup.exists()


def test_restore_refuses_without_safety_backup_dir(tmp_path):
    """Sécurité : restore_backup() exige safety_backup_dir."""
    backup_root = tmp_path / "bks"; backup_root.mkdir()
    b = backup_root / "pre_import_MaSave_20260101-120000"
    b.mkdir()
    (b / "save.zip").write_bytes(b"x")
    backups = restore_mod.list_backups(backup_root)
    assert len(backups) == 1
    with pytest.raises(ValueError, match="safety_backup_dir"):
        restore_mod.restore_backup(backups[0], safety_backup_dir=None)


def test_restore_refuses_incomplete_backup(tmp_path):
    """Un backup sans save.zip n'est pas restaurable."""
    backup_root = tmp_path
    b = backup_root / "pre_import_MaSave_20260101-120000"
    b.mkdir()
    # PAS de save.zip
    (b / "MaSave.db").write_bytes(b"orphan")
    backups = restore_mod.list_backups(backup_root)
    assert len(backups) == 1
    assert backups[0].restorable is False
    with pytest.raises(ValueError, match="incomplet|restaurer"):
        restore_mod.restore_backup(backups[0], safety_backup_dir=tmp_path / "s")

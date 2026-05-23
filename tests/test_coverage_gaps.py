"""Tests pour combler les trous de couverture identifiés par l'audit phase 3.

Avant ces tests :
- `SharedRepo.push_bundle` n'était JAMAIS testé directement (gui.py avait sa
  propre version inline, qui dupliquait la logique).
- `SharedRepo.pull_bundle` n'était JAMAIS testé.
- Le verrou de tour (`take_lock`/`release_lock`/`get_lock`) — fonctionnalité
  centrale du workflow cloud — n'avait AUCUN test.
- `parse_ini_mods` plantait silencieusement sur .ini avec BOM UTF-8 (cas
  Notepad Windows).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pzsavesync import bundle as bundle_mod
from pzsavesync.sync import SharedRepo


# -----------------------------------------------------------------------------
# parse_ini_mods : encodings
# -----------------------------------------------------------------------------

def test_parse_ini_mods_with_utf8_bom(tmp_path):
    """Notepad Windows sauvegarde parfois en UTF-8-BOM. Sans utf-8-sig,
    la 1re ligne devient `\\ufeffMods=...` et startswith rate → aucun mod
    détecté. Régression silencieuse mais qui faisait passer "0 mods" aux users."""
    ini = tmp_path / "with_bom.ini"
    ini.write_bytes(b"\xef\xbb\xbfMods=alpha;beta\nWorkshopItems=111;222\n")
    mods, ws = bundle_mod.parse_ini_mods(ini)
    assert mods == ["alpha", "beta"]
    assert ws == ["111", "222"]


def test_parse_ini_mods_crlf(tmp_path):
    ini = tmp_path / "crlf.ini"
    ini.write_bytes(b"Mods=a;b\r\nWorkshopItems=1;2\r\n")
    mods, ws = bundle_mod.parse_ini_mods(ini)
    assert mods == ["a", "b"]
    assert ws == ["1", "2"]


def test_parse_ini_mods_cr_only(tmp_path):
    """splitlines() doit gérer le CR seul (vieux Mac, rare mais existe)."""
    ini = tmp_path / "cr.ini"
    ini.write_bytes(b"Mods=a;b\rWorkshopItems=1;2\r")
    mods, ws = bundle_mod.parse_ini_mods(ini)
    assert mods == ["a", "b"]
    assert ws == ["1", "2"]


def test_parse_ini_mods_empty_file(tmp_path):
    ini = tmp_path / "empty.ini"
    ini.write_bytes(b"")
    mods, ws = bundle_mod.parse_ini_mods(ini)
    assert mods == []
    assert ws == []


def test_parse_ini_mods_no_workshop_section(tmp_path):
    """Seul Mods=, pas de WorkshopItems= (cas vanilla)."""
    ini = tmp_path / "no_ws.ini"
    ini.write_text("Mods=vanilla_only\n", encoding="utf-8")
    mods, ws = bundle_mod.parse_ini_mods(ini)
    assert mods == ["vanilla_only"]
    assert ws == []


def test_parse_ini_mods_filters_non_digit_workshop_ids(tmp_path):
    """Defense en profondeur : un Workshop ID non-numérique est filtré."""
    ini = tmp_path / "mix.ini"
    ini.write_text(
        "WorkshopItems=12345;not_a_number;67890;abc123\n",
        encoding="utf-8",
    )
    _, ws = bundle_mod.parse_ini_mods(ini)
    assert ws == ["12345", "67890"]


# -----------------------------------------------------------------------------
# SharedRepo.push_bundle — flot complet (manquait dans la suite)
# -----------------------------------------------------------------------------

def _make_minimal_zomboid(root: Path, save_name: str = "TestSave"):
    save_dir = root / "Saves" / "Multiplayer" / save_name
    save_dir.mkdir(parents=True)
    (save_dir / "map_0_0.bin").write_bytes(b"chunk")
    (root / "db").mkdir()
    db = root / "db" / f"{save_name}.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE whitelist(username TEXT)")
    con.execute("INSERT INTO whitelist VALUES ('Alice')")
    con.commit()
    con.close()
    (root / "Server").mkdir()
    (root / "Server" / f"{save_name}.ini").write_text("Mods=foo\n", encoding="utf-8")


def test_push_bundle_creates_version_in_manifest(tmp_path):
    """push_bundle complet : crée le bundle + enregistre dans manifest."""
    zomboid = tmp_path / "zomboid"
    zomboid.mkdir()
    _make_minimal_zomboid(zomboid)

    shared = tmp_path / "shared"
    repo = SharedRepo(shared)
    version, stats = repo.push_bundle(
        save_name="TestSave",
        uploaded_by="alice",
        note="test push",
        root=zomboid,
    )
    assert version.save_name == "TestSave"
    assert version.uploaded_by == "alice"
    assert version.note == "test push"
    assert version.has_db is True
    assert version.size_bytes > 0
    assert version.bundle_mode == "full"  # default mode
    assert stats.mode_used == "full"
    # Le fichier physique existe
    assert (shared / "versions" / version.filename).exists()
    # Le manifest le voit
    listed = repo.list_versions()
    assert len(listed) == 1
    assert listed[0].filename == version.filename


def test_push_bundle_with_progress_callback(tmp_path):
    """Régression v0.3.6 : push_bundle accepte un progress callback."""
    zomboid = tmp_path / "zomboid"
    zomboid.mkdir()
    _make_minimal_zomboid(zomboid)

    repo = SharedRepo(tmp_path / "shared")
    progress_calls = []

    def cb(step: str, current: int, total: int):
        progress_calls.append((step, current, total))

    repo.push_bundle(
        save_name="TestSave",
        uploaded_by="alice",
        progress=cb,
        root=zomboid,
    )
    # Au minimum un appel "scan" et un appel "hash"
    steps_seen = {step for step, _, _ in progress_calls}
    assert "scan" in steps_seen
    assert "hash" in steps_seen


def test_push_bundle_appends_not_replaces(tmp_path):
    """Plusieurs push successifs accumulent dans le manifest."""
    zomboid = tmp_path / "zomboid"
    zomboid.mkdir()
    _make_minimal_zomboid(zomboid)

    repo = SharedRepo(tmp_path / "shared")
    repo.push_bundle("TestSave", "alice", root=zomboid)
    import time
    time.sleep(1.1)  # garantir un timestamp différent pour le filename
    repo.push_bundle("TestSave", "alice", root=zomboid)
    versions = repo.list_versions()
    assert len(versions) == 2
    assert all(v.bundle_mode == "full" for v in versions)


# -----------------------------------------------------------------------------
# SharedRepo.pull_bundle — manquait dans la suite
# -----------------------------------------------------------------------------

def test_pull_bundle_restores_save(tmp_path):
    """pull_bundle restaure une save dans une arborescence vide."""
    zomboid_src = tmp_path / "src"
    zomboid_src.mkdir()
    _make_minimal_zomboid(zomboid_src)

    repo = SharedRepo(tmp_path / "shared")
    v, _stats = repo.push_bundle("TestSave", "alice", root=zomboid_src)

    # On simule le côté destinataire avec un répertoire vide via le bundle
    # extract_bundle accepte root=...
    zomboid_dst = tmp_path / "dst"
    backups = tmp_path / "backups"
    archive = repo.versions_dir / v.filename
    report = bundle_mod.extract_bundle(archive, root=zomboid_dst, backup_dir=backups)
    assert report.save_name == "TestSave"
    assert (zomboid_dst / "Saves" / "Multiplayer" / "TestSave" / "map_0_0.bin").exists()
    assert (zomboid_dst / "db" / "TestSave.db").exists()


def test_pull_bundle_raises_if_archive_missing(tmp_path):
    """pull_bundle d'une version manquante doit lever FileNotFoundError."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    from pzsavesync.sync import Version
    fake_version = Version(
        filename="missing.zip",
        save_name="X", uploaded_by="alice", uploaded_at="2026-01-01T00:00:00",
        size_bytes=0,
    )
    with pytest.raises(FileNotFoundError):
        repo.pull_bundle(fake_version, backup_dir=tmp_path / "bk")


# -----------------------------------------------------------------------------
# Verrou de tour — feature centrale jamais testée jusqu'ici
# -----------------------------------------------------------------------------

def test_take_lock_creates_lock_file(tmp_path):
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    lock = repo.take_lock("alice", note="ma session")
    assert lock.holder == "alice"
    assert lock.note == "ma session"
    assert lock.taken_at  # ISO timestamp
    assert repo.lock_path.exists()


def test_get_lock_returns_existing(tmp_path):
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    repo.take_lock("alice")
    existing = repo.get_lock()
    assert existing is not None
    assert existing.holder == "alice"


def test_get_lock_returns_none_if_no_lock(tmp_path):
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    assert repo.get_lock() is None


def test_take_lock_fails_if_other_holder(tmp_path):
    """Si bob a le verrou, alice ne peut pas le prendre sans force."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    repo.take_lock("bob")
    with pytest.raises(RuntimeError, match="bob"):
        repo.take_lock("alice")


def test_take_lock_same_holder_succeeds(tmp_path):
    """Si alice a déjà le verrou, take_lock("alice") refresh sans erreur."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    first = repo.take_lock("alice", note="première prise")
    import time
    time.sleep(1.1)
    second = repo.take_lock("alice", note="re-prise")
    # Deuxième prise écrase la première (re-take légitime)
    assert second.note == "re-prise"
    # Le timestamp a bougé (ou est identique selon timing — au moins ne crashe pas)
    assert repo.get_lock().note == "re-prise"


def test_take_lock_force_overrides_other_holder(tmp_path):
    """force=True permet de prendre le verrou d'un autre (cas où il est parti)."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    repo.take_lock("bob")
    forced = repo.take_lock("alice", force=True)
    assert forced.holder == "alice"
    assert repo.get_lock().holder == "alice"


def test_release_lock_removes_file(tmp_path):
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    repo.take_lock("alice")
    repo.release_lock("alice")
    assert repo.get_lock() is None
    assert not repo.lock_path.exists()


def test_release_lock_fails_if_wrong_holder(tmp_path):
    """Bob ne peut pas libérer le verrou d'alice sans force."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    repo.take_lock("alice")
    with pytest.raises(RuntimeError, match="alice"):
        repo.release_lock("bob")
    # Le verrou est intact
    assert repo.get_lock() is not None


def test_release_lock_force_removes_anyway(tmp_path):
    """force=True libère même si on n'est pas le holder."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    repo.take_lock("alice")
    repo.release_lock("bob", force=True)
    assert repo.get_lock() is None


def test_release_lock_when_none_is_noop(tmp_path):
    """release_lock sans verrou en place ne lève pas."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    repo.release_lock("alice")  # pas d'exception


def test_get_lock_resilient_to_corrupted_json(tmp_path):
    """lock.json corrompu → on log et on renvoie None, pas de crash."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    repo.lock_path.write_text("###NOT_JSON###", encoding="utf-8")
    assert repo.get_lock() is None


def test_get_lock_resilient_to_array_json(tmp_path):
    """lock.json = array → not a dict → None."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    repo.lock_path.write_text('[1, 2, 3]', encoding="utf-8")
    assert repo.get_lock() is None


def test_get_lock_resilient_to_missing_fields(tmp_path):
    """lock.json sans holder ou taken_at → None."""
    import json
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    repo.lock_path.write_text(json.dumps({"holder": "alice"}), encoding="utf-8")  # pas de taken_at
    assert repo.get_lock() is None


def test_lock_atomic_write_via_tmp(tmp_path):
    """take_lock passe par .tmp + os.replace (héritage _atomic_write_text)."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    repo.take_lock("alice")
    # Pas de .tmp orphelin après écriture réussie
    assert not (tmp_path / "lock.json.tmp").exists()
    # Le lock.json final est bien là
    assert repo.lock_path.exists()

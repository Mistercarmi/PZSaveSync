"""Tests pour les fixes v0.3.6 — résilience et défense en profondeur.

Couvre :
- Fix #1 : config.save() est atomique (pas de config tronquée si crash)
- Fix #2 : SharedRepo._read_manifest() tolère un manifest.json corrompu
- Fix #3 : inspector.inspect_zip() n'extrait pas l'archive entière + zip-bomb caps
- Fix #4 : cleanup_orphan_tmp_files() respecte un délai anti-concurrence
- Bonus : restore.list_backups voit les pre_restore_*
"""
from __future__ import annotations

import json
import os
import time
import zipfile
from pathlib import Path

import pytest

from pzsavesync import bundle as bundle_mod
from pzsavesync import config as config_mod
from pzsavesync import inspector
from pzsavesync import restore as restore_mod
from pzsavesync.sync import SharedRepo


# -----------------------------------------------------------------------------
# Fix #1 — config.save() atomique
# -----------------------------------------------------------------------------

def test_config_save_uses_atomic_write_via_tmp(monkeypatch, tmp_path):
    """save() doit passer par un .tmp puis os.replace, pas écrire en direct.

    On simule un échec PENDANT l'écriture (write_text qui crashe) et on
    vérifie que le config.json existant n'a pas été tronqué.
    """
    monkeypatch.setattr(config_mod, "APP_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "config.json")

    # Première sauvegarde réussit : contenu de référence
    cfg = config_mod.Config()
    cfg.player_name = "Alice"
    cfg.shared_folder = "D:\\partage"
    config_mod.save(cfg)
    original_bytes = config_mod.CONFIG_PATH.read_bytes()
    assert b"Alice" in original_bytes

    # On rend write_text inopérant pour simuler un crash en plein écriture
    real_write_text = Path.write_text

    def boom(self, *a, **kw):
        if str(self).endswith(".tmp"):
            raise OSError("simulated crash mid-write")
        return real_write_text(self, *a, **kw)

    monkeypatch.setattr(Path, "write_text", boom)

    cfg.player_name = "ALICE_TRONQUE"
    with pytest.raises(OSError):
        config_mod.save(cfg)

    # Le config.json existant N'A PAS été touché — c'est le contrat atomique
    assert config_mod.CONFIG_PATH.read_bytes() == original_bytes
    # Et le .tmp a été nettoyé après l'échec
    assert not (tmp_path / "config.json.tmp").exists()


def test_config_save_load_round_trip(monkeypatch, tmp_path):
    """Sanity check : save() → load() round-trip préserve toutes les valeurs."""
    monkeypatch.setattr(config_mod, "APP_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "config.json")

    cfg = config_mod.Config()
    cfg.player_name = "Bob"
    cfg.shared_folder = "/home/bob/Dropbox/PZ"
    cfg.save_name = "Muldraugh_42"
    cfg.discord_webhook = "https://discord.com/api/webhooks/123/abc"
    cfg.hide_help_banner = True
    cfg.keep_last_n_versions = 5
    config_mod.save(cfg)

    reloaded = config_mod.load()
    assert reloaded.player_name == "Bob"
    assert reloaded.shared_folder == "/home/bob/Dropbox/PZ"
    assert reloaded.save_name == "Muldraugh_42"
    assert reloaded.discord_webhook == "https://discord.com/api/webhooks/123/abc"
    assert reloaded.hide_help_banner is True
    assert reloaded.keep_last_n_versions == 5


# -----------------------------------------------------------------------------
# Fix #2 — _read_manifest tolérant
# -----------------------------------------------------------------------------

def test_read_manifest_handles_truncated_json(tmp_path):
    """Si manifest.json est tronqué, on log et on renvoie un manifest vide."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    # Écraser le manifest avec du JSON tronqué (sync cloud foireuse)
    repo.manifest_path.write_text('{"versions": [{"filename": "incomp', encoding="utf-8")
    data = repo._read_manifest()
    assert data == {"versions": []}
    # list_versions() ne doit pas crasher non plus
    assert repo.list_versions() == []


def test_read_manifest_handles_array_instead_of_object(tmp_path):
    """Si manifest.json contient un array (édit manuel), on tombe back vide."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    repo.manifest_path.write_text('["pas", "un", "dict"]', encoding="utf-8")
    data = repo._read_manifest()
    assert data == {"versions": []}


def test_read_manifest_handles_versions_not_a_list(tmp_path):
    """Si versions n'est pas un array (édit manuel), on le force à []."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    repo.manifest_path.write_text(
        '{"versions": "boom", "extra": "kept"}', encoding="utf-8",
    )
    data = repo._read_manifest()
    assert data["versions"] == []
    assert data["extra"] == "kept"


def test_list_versions_resilient_when_manifest_corrupt(tmp_path):
    """L'UI ne doit plus crasher si le manifest.json est cassé."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    repo.manifest_path.write_text("###NOT_JSON###", encoding="utf-8")
    # Avant le fix : list_versions levait JSONDecodeError → UI crash
    # Après : retourne []
    assert repo.list_versions() == []
    assert repo.latest_version() is None


# -----------------------------------------------------------------------------
# Fix #3 — inspect_zip safe
# -----------------------------------------------------------------------------

def test_inspect_zip_does_not_extract_all_to_disk(tmp_path, monkeypatch):
    """inspect_zip ne doit PLUS appeler zf.extractall — uniquement zf.open ciblé."""
    # On crée un bundle légitime
    src = tmp_path / "src"
    src.mkdir()
    (src / "Saves" / "Multiplayer" / "S").mkdir(parents=True)
    (src / "Saves" / "Multiplayer" / "S" / "map_0_0.bin").write_bytes(b"chunk")
    (src / "db").mkdir(); (src / "Server").mkdir()
    out = tmp_path / "bundle.zip"
    bundle_mod.build_bundle("S", out, "alice", root=src)

    # On instrumente zipfile.ZipFile.extractall pour qu'il throw — si inspect_zip
    # l'appelle, le test fail.
    called = {"extractall": False}
    real_extractall = zipfile.ZipFile.extractall

    def trap(self, *a, **kw):
        called["extractall"] = True
        raise AssertionError("inspect_zip ne doit pas extraire tout le bundle !")

    monkeypatch.setattr(zipfile.ZipFile, "extractall", trap)

    info = inspector.inspect_zip(out)
    assert called["extractall"] is False
    assert info.exists
    assert info.kind == "server_save"
    assert info.map_chunks == 1


def test_inspect_zip_refuses_zip_bomb_by_file_count(tmp_path, monkeypatch):
    """Une archive avec > 500 000 entries doit être rejetée à l'inspection."""
    # On patche la limite à 5 pour la rendre testable rapidement
    monkeypatch.setattr(inspector, "_INSPECT_MAX_FILES", 5)
    out = tmp_path / "bomb.zip"
    with zipfile.ZipFile(out, "w") as zf:
        for i in range(10):
            zf.writestr(f"file_{i}.bin", b"x")
    info = inspector.inspect_zip(out)
    assert info.exists is False
    assert any("suspect" in n for n in info.notes)


def test_inspect_zip_refuses_zip_bomb_by_uncompressed_size(tmp_path, monkeypatch):
    """Une archive dont le décompressé dépasse la limite est rejetée."""
    monkeypatch.setattr(inspector, "_INSPECT_MAX_UNCOMPRESSED", 100)  # 100 octets
    out = tmp_path / "bomb.zip"
    with zipfile.ZipFile(out, "w") as zf:
        # Chaque fichier fait 200 octets → on dépasse vite
        for i in range(3):
            zf.writestr(f"f_{i}.bin", b"x" * 200)
    info = inspector.inspect_zip(out)
    assert info.exists is False
    assert any("suspect" in n for n in info.notes)


def test_inspect_zip_handles_bad_zip_gracefully(tmp_path):
    """Un fichier qui n'est pas un zip ne doit pas crasher l'inspection."""
    fake = tmp_path / "not_a_zip.zip"
    fake.write_bytes(b"This is not a zip archive")
    info = inspector.inspect_zip(fake)
    assert info.exists is False
    assert any("illisible" in n.lower() for n in info.notes)


def test_inspect_zip_extracts_players_from_bundle_db(tmp_path):
    """Le bundle contient une .db avec des joueurs — l'inspection les lit."""
    import sqlite3
    src = tmp_path / "src"
    src.mkdir()
    save_dir = src / "Saves" / "Multiplayer" / "MaSave"
    save_dir.mkdir(parents=True)
    (save_dir / "map_0_0.bin").write_bytes(b"chunk")
    (src / "Server").mkdir()
    (src / "db").mkdir()
    db_path = src / "db" / "MaSave.db"
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE whitelist(username TEXT)")
    con.executemany("INSERT INTO whitelist VALUES (?)", [("Alice",), ("Bob",)])
    con.commit()
    con.close()

    out = tmp_path / "bundle.zip"
    bundle_mod.build_bundle("MaSave", out, "alice", root=src)

    info = inspector.inspect_zip(out)
    assert info.exists
    assert info.kind == "server_save"
    assert info.players_source == "db"
    assert set(info.players) == {"Alice", "Bob"}


# -----------------------------------------------------------------------------
# Fix #4 — cleanup .tmp avec délai anti-concurrence
# -----------------------------------------------------------------------------

def test_cleanup_orphan_tmp_respects_min_age(tmp_path):
    """Les .tmp récents (< 5 min) ne doivent PAS être supprimés.

    Sinon une 2e instance de l'app pourrait clobber le .tmp d'un push en
    cours dans une 1re instance.
    """
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    # .tmp tout neuf — simule un push en cours dans une autre instance
    recent = repo.versions_dir / "in_progress.zip.tmp"
    recent.write_bytes(b"in progress data")

    # Avec le défaut (5 min), il doit être épargné
    deleted = repo.cleanup_orphan_tmp_files()
    assert "in_progress.zip.tmp" not in deleted
    assert recent.exists()


def test_cleanup_orphan_tmp_deletes_old_residues(tmp_path):
    """Les .tmp anciens (> 5 min) sont nettoyés comme résidus de crash."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    old = repo.versions_dir / "old_crash.zip.tmp"
    old.write_bytes(b"residue from a crashed session")
    # Backdate la mtime de 1 heure
    one_hour_ago = time.time() - 3600
    os.utime(old, (one_hour_ago, one_hour_ago))

    deleted = repo.cleanup_orphan_tmp_files()
    assert "old_crash.zip.tmp" in deleted
    assert not old.exists()


def test_cleanup_orphan_tmp_min_age_zero_for_tests(tmp_path):
    """min_age_seconds=0 force la suppression sans délai (tests / debug)."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    fresh = repo.versions_dir / "fresh.zip.tmp"
    fresh.write_bytes(b"x")
    deleted = repo.cleanup_orphan_tmp_files(min_age_seconds=0)
    assert "fresh.zip.tmp" in deleted


# -----------------------------------------------------------------------------
# Bonus — restore.list_backups voit les pre_restore_*
# -----------------------------------------------------------------------------

def test_list_backups_sees_both_import_and_restore_kinds(tmp_path):
    """list_backups remonte aussi les pre_restore_* (avant : ignorés).

    Use case : l'user fait restore_backup() qui crée un pre_restore_*. S'il
    se trompe de backup à restaurer, il veut pouvoir revenir au pre_restore.
    """
    # Backup avant pull/import
    b_imp = tmp_path / "pre_import_MaSave_20260101-100000"
    b_imp.mkdir()
    (b_imp / "save.zip").write_bytes(b"x")
    # Backup avant restauration
    b_res = tmp_path / "pre_restore_MaSave_20260101-110000"
    b_res.mkdir()
    (b_res / "save.zip").write_bytes(b"x")

    backups = restore_mod.list_backups(tmp_path)
    assert len(backups) == 2
    kinds = {b.kind for b in backups}
    assert kinds == {"import", "restore"}
    # Tri par date desc — le pre_restore (11:00) en premier
    assert backups[0].kind == "restore"
    assert backups[1].kind == "import"


def test_backup_entry_kind_label(tmp_path):
    """kind_label est lisible pour l'UI."""
    b_imp = tmp_path / "pre_import_S_20260101-100000"
    b_imp.mkdir()
    (b_imp / "save.zip").write_bytes(b"x")
    b_res = tmp_path / "pre_restore_S_20260101-110000"
    b_res.mkdir()
    (b_res / "save.zip").write_bytes(b"x")
    backups = restore_mod.list_backups(tmp_path)
    labels = {b.kind: b.kind_label for b in backups}
    assert labels["import"] == "avant import"
    assert labels["restore"] == "avant restauration"

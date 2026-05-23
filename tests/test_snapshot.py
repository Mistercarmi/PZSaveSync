"""Tests du module snapshot.py (v0.4.0)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from pzsavesync import snapshot as snap_mod
from pzsavesync.snapshot import (
    DEFAULT_KEEP_RECENT,
    Snapshot,
    SnapshotCorruptError,
    compute_snapshot,
    cleanup_orphan_snapshots,
    diff_against_snapshot,
    find_latest_snapshot_for_save,
    load_snapshot_for_parent,
    save_snapshot,
    snapshot_path,
    snapshots_dir,
)


@pytest.fixture(autouse=True)
def isolated_app_dir(tmp_path, monkeypatch):
    """Isole APP_DIR pour chaque test : aucun snapshot réel n'est touché."""
    fake_app_dir = tmp_path / "PZSaveSync"
    fake_app_dir.mkdir()
    monkeypatch.setattr(snap_mod, "APP_DIR", fake_app_dir)
    return fake_app_dir


def _make_save(root: Path, files: dict[str, bytes]) -> Path:
    """Construit un faux save_dir avec les fichiers donnés (clé = chemin POSIX relatif)."""
    save_dir = root / "save"
    save_dir.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = save_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    return save_dir


# --------- compute_snapshot ---------

def test_compute_snapshot_hashes_all_files(tmp_path):
    save_dir = _make_save(tmp_path, {
        "map_1_1.bin": b"chunk-1",
        "map_1_2.bin": b"chunk-2",
        "subdir/players.db": b"db-bytes",
    })
    snap = compute_snapshot(save_dir, "TestSave", "parent_sha_abc", "bundle.zip")

    assert snap.save_name == "TestSave"
    assert snap.parent_bundle_sha256 == "parent_sha_abc"
    assert snap.parent_bundle_filename == "bundle.zip"
    assert len(snap.save_files) == 3
    assert "map_1_1.bin" in snap.save_files
    assert "subdir/players.db" in snap.save_files
    # Hash est bien un SHA256 hex (64 chars)
    for h in snap.save_files.values():
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


def test_compute_snapshot_uses_posix_paths_on_windows(tmp_path):
    save_dir = _make_save(tmp_path, {"a/b/c.bin": b"x"})
    snap = compute_snapshot(save_dir, "S", "sha")
    # Pas de backslash dans les clés, même sur Windows
    for k in snap.save_files.keys():
        assert "\\" not in k
    assert "a/b/c.bin" in snap.save_files


def test_compute_snapshot_raises_if_save_dir_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        compute_snapshot(tmp_path / "ghost", "S", "sha")


def test_compute_snapshot_raises_if_save_dir_is_file(tmp_path):
    f = tmp_path / "file"
    f.write_text("not a dir")
    with pytest.raises(NotADirectoryError):
        compute_snapshot(f, "S", "sha")


def test_compute_snapshot_empty_dir_returns_empty_hashes(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    snap = compute_snapshot(empty, "S", "sha")
    assert snap.save_files == {}


def test_compute_snapshot_progress_callback_called(tmp_path):
    save_dir = _make_save(tmp_path, {f"f_{i}.bin": b"x" for i in range(5)})
    calls: list[tuple[str, int, int]] = []
    compute_snapshot(save_dir, "S", "sha", progress=lambda *a: calls.append(a))
    assert calls  # au moins un appel
    assert all(c[0] == "snapshot" for c in calls)


# --------- save/load roundtrip ---------

def test_save_load_snapshot_roundtrip(tmp_path):
    save_dir = _make_save(tmp_path, {"a.bin": b"1", "b.bin": b"2"})
    original = compute_snapshot(save_dir, "MySave", "abc123def456", "src.zip")
    path = save_snapshot(original)

    assert path.exists()
    loaded = load_snapshot_for_parent("MySave", "abc123def456")
    assert loaded is not None
    assert loaded.save_name == original.save_name
    assert loaded.parent_bundle_sha256 == original.parent_bundle_sha256
    assert loaded.save_files == original.save_files
    assert loaded.parent_bundle_filename == "src.zip"


def test_save_snapshot_atomic_writes_no_tmp_leftover(tmp_path):
    save_dir = _make_save(tmp_path, {"a.bin": b"1"})
    snap = compute_snapshot(save_dir, "S", "sha")
    save_snapshot(snap)
    # Pas de .tmp orphelin
    leftover = list(snapshots_dir().glob("*.tmp"))
    assert leftover == []


def test_load_snapshot_returns_none_for_missing(tmp_path):
    assert load_snapshot_for_parent("Ghost", "noexists") is None


def test_load_snapshot_raises_for_corrupt_json(tmp_path):
    target = snapshot_path("Broken", "abc123")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(SnapshotCorruptError):
        load_snapshot_for_parent("Broken", "abc123")


def test_load_snapshot_raises_for_root_not_dict(tmp_path):
    target = snapshot_path("Broken", "abc123")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("[1, 2, 3]", encoding="utf-8")  # liste, pas dict
    with pytest.raises(SnapshotCorruptError):
        load_snapshot_for_parent("Broken", "abc123")


def test_load_snapshot_raises_when_save_files_wrong_type(tmp_path):
    target = snapshot_path("Bad", "abc")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        "schema_version": 1,
        "save_name": "Bad",
        "parent_bundle_sha256": "abc",
        "save_files": ["not", "a", "dict"],  # devrait être dict
    }), encoding="utf-8")
    with pytest.raises(SnapshotCorruptError):
        load_snapshot_for_parent("Bad", "abc")


def test_load_snapshot_ignores_unknown_fields(tmp_path):
    """Compat ascendante : un snapshot avec champs futurs doit se charger sans crash."""
    target = snapshot_path("Future", "abc")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        "schema_version": 2,
        "save_name": "Future",
        "parent_bundle_sha256": "abc",
        "save_files": {"x.bin": "f" * 64},
        "totally_new_field": "ignored",
    }), encoding="utf-8")
    snap = load_snapshot_for_parent("Future", "abc")
    assert snap is not None
    assert snap.save_files == {"x.bin": "f" * 64}


# --------- find_latest_snapshot_for_save ---------

def test_find_latest_snapshot_picks_most_recent(tmp_path):
    save_dir = _make_save(tmp_path, {"a.bin": b"1"})
    s1 = compute_snapshot(save_dir, "MySave", "sha_oldest_1234")
    p1 = save_snapshot(s1)
    # Forcer mtime ancien
    old = time.time() - 86400 * 10
    os.utime(p1, (old, old))

    s2 = compute_snapshot(save_dir, "MySave", "sha_newest_5678")
    save_snapshot(s2)

    found = find_latest_snapshot_for_save("MySave")
    assert found is not None
    assert found.parent_bundle_sha256 == "sha_newest_5678"


def test_find_latest_snapshot_returns_none_when_no_snapshots(tmp_path):
    assert find_latest_snapshot_for_save("Nothing") is None


def test_find_latest_snapshot_skips_corrupt_files(tmp_path):
    save_dir = _make_save(tmp_path, {"a.bin": b"1"})
    good = compute_snapshot(save_dir, "Mix", "sha_good_aaaa")
    save_snapshot(good)
    # Snapshot corrompu
    bad = snapshot_path("Mix", "sha_corrupt_bbbb")
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("garbage", encoding="utf-8")
    # Le corrompu est plus récent → on doit quand même tomber sur le bon
    found = find_latest_snapshot_for_save("Mix")
    assert found is not None
    assert found.parent_bundle_sha256 == "sha_good_aaaa"


# --------- diff_against_snapshot ---------

def test_diff_detects_added(tmp_path):
    save_dir = _make_save(tmp_path, {"a.bin": b"a"})
    snap = compute_snapshot(save_dir, "S", "sha")
    # On ajoute un fichier
    (save_dir / "b.bin").write_bytes(b"b")
    diff = diff_against_snapshot(snap, save_dir)
    assert diff.added == ["b.bin"]
    assert diff.modified == []
    assert diff.unchanged == ["a.bin"]
    assert diff.deleted == []


def test_diff_detects_modified(tmp_path):
    save_dir = _make_save(tmp_path, {"a.bin": b"original"})
    snap = compute_snapshot(save_dir, "S", "sha")
    (save_dir / "a.bin").write_bytes(b"modified")
    diff = diff_against_snapshot(snap, save_dir)
    assert diff.modified == ["a.bin"]
    assert diff.added == []
    assert diff.unchanged == []


def test_diff_detects_unchanged(tmp_path):
    save_dir = _make_save(tmp_path, {"a.bin": b"x", "b.bin": b"y"})
    snap = compute_snapshot(save_dir, "S", "sha")
    diff = diff_against_snapshot(snap, save_dir)
    assert set(diff.unchanged) == {"a.bin", "b.bin"}
    assert diff.added == []
    assert diff.modified == []
    assert diff.deleted == []


def test_diff_detects_deleted(tmp_path):
    save_dir = _make_save(tmp_path, {"a.bin": b"x", "b.bin": b"y"})
    snap = compute_snapshot(save_dir, "S", "sha")
    (save_dir / "b.bin").unlink()
    diff = diff_against_snapshot(snap, save_dir)
    assert diff.deleted == ["b.bin"]
    assert diff.unchanged == ["a.bin"]


def test_diff_current_hashes_matches_actual_state(tmp_path):
    save_dir = _make_save(tmp_path, {"a.bin": b"foo", "b.bin": b"bar"})
    snap = compute_snapshot(save_dir, "S", "sha")
    diff = diff_against_snapshot(snap, save_dir)
    # current_hashes doit être complet = tous les fichiers actuels
    assert set(diff.current_hashes.keys()) == {"a.bin", "b.bin"}
    # Et égal aux hashes du snapshot (rien n'a changé)
    assert diff.current_hashes == snap.save_files


def test_diff_combines_all_categories(tmp_path):
    save_dir = _make_save(tmp_path, {
        "unchanged.bin": b"same",
        "modified.bin": b"v1",
        "deleted.bin": b"goodbye",
    })
    snap = compute_snapshot(save_dir, "S", "sha")
    # Modifie, ajoute, supprime
    (save_dir / "modified.bin").write_bytes(b"v2")
    (save_dir / "deleted.bin").unlink()
    (save_dir / "added.bin").write_bytes(b"hello")
    diff = diff_against_snapshot(snap, save_dir)
    assert diff.unchanged == ["unchanged.bin"]
    assert diff.modified == ["modified.bin"]
    assert diff.deleted == ["deleted.bin"]
    assert diff.added == ["added.bin"]


def test_diff_raises_if_save_dir_missing(tmp_path):
    save_dir = _make_save(tmp_path, {"a.bin": b"1"})
    snap = compute_snapshot(save_dir, "S", "sha")
    import shutil
    shutil.rmtree(save_dir)
    with pytest.raises(FileNotFoundError):
        diff_against_snapshot(snap, save_dir)


# --------- cleanup_orphan_snapshots ---------

def _touch_old(p: Path, days_ago: int):
    ts = time.time() - (days_ago * 86400)
    os.utime(p, (ts, ts))


def test_cleanup_keeps_most_recent_per_save_even_if_old(tmp_path):
    save_dir = _make_save(tmp_path, {"a.bin": b"1"})
    snap = compute_snapshot(save_dir, "Mine", "sha_xxxxxxxxxxxx")
    p = save_snapshot(snap)
    _touch_old(p, 365)  # > max_age_days par défaut

    deleted = cleanup_orphan_snapshots(max_age_days=180)
    assert deleted == []  # Le plus récent par save est toujours protégé
    assert p.exists()


def _unique_sha(i: int) -> str:
    """Génère un SHA hex 64-chars dont les 12 premiers sont uniques pour i.

    snapshot_path tronque le sha à 12 chars pour le nom de fichier, donc
    les 12 premiers chars DOIVENT différer pour avoir des snapshots distincts.
    """
    return f"{i:012x}" + ("0" * 52)


def test_cleanup_keeps_n_recent_and_purges_old_extras(tmp_path):
    save_dir = _make_save(tmp_path, {"a.bin": b"1"})
    # Crée 8 snapshots avec mtime décroissant (le 1er = le plus récent)
    paths: list[Path] = []
    for i in range(8):
        snap = compute_snapshot(save_dir, "Big", _unique_sha(i))
        p = save_snapshot(snap)
        # plus i augmente, plus le snapshot est ancien
        _touch_old(p, 200 + i)
        paths.append(p)

    deleted = cleanup_orphan_snapshots(max_age_days=180, keep_n_recent=DEFAULT_KEEP_RECENT)
    # Les 5 premiers (les plus récents) doivent rester, les 3 derniers virés
    survivors = [p for p in paths if p.exists()]
    assert len(survivors) == DEFAULT_KEEP_RECENT
    assert len(deleted) == 3


def test_cleanup_keeps_files_younger_than_recent_protection(tmp_path):
    save_dir = _make_save(tmp_path, {"a.bin": b"1"})
    # 10 snapshots tous récents (< 30 jours) → aucun ne doit être viré
    paths: list[Path] = []
    for i in range(10):
        snap = compute_snapshot(save_dir, "Recent", _unique_sha(i))
        p = save_snapshot(snap)
        _touch_old(p, 5)  # 5 jours
        paths.append(p)

    deleted = cleanup_orphan_snapshots(max_age_days=180, keep_n_recent=3)
    assert deleted == []
    assert all(p.exists() for p in paths)


def test_cleanup_only_targets_specified_save_name(tmp_path):
    save_dir = _make_save(tmp_path, {"a.bin": b"1"})
    # Mine : 8 snapshots vieux
    mine_paths: list[Path] = []
    for i in range(8):
        snap = compute_snapshot(save_dir, "Mine", _unique_sha(i))
        p = save_snapshot(snap)
        _touch_old(p, 200 + i)
        mine_paths.append(p)
    # Other : 8 snapshots vieux pareil
    other_paths: list[Path] = []
    for i in range(8):
        # Décalage d'index pour éviter collision avec ceux de "Mine"
        snap = compute_snapshot(save_dir, "Other", _unique_sha(100 + i))
        p = save_snapshot(snap)
        _touch_old(p, 200 + i)
        other_paths.append(p)

    cleanup_orphan_snapshots(save_name="Mine", max_age_days=180, keep_n_recent=3)
    mine_survivors = [p for p in mine_paths if p.exists()]
    other_survivors = [p for p in other_paths if p.exists()]
    assert len(mine_survivors) == 3
    assert len(other_survivors) == 8  # Pas touché


def test_cleanup_handles_missing_snapshots_dir(tmp_path):
    # Pas de dossier snapshots → ne doit pas crasher
    deleted = cleanup_orphan_snapshots()
    assert deleted == []


# --------- snapshot_path naming ---------

def test_snapshot_path_uses_short_sha_for_readability(tmp_path):
    p = snapshot_path("MySave", "abc123def456789xyz")
    assert "abc123def456" in p.name
    assert p.suffix == ".json"


def test_snapshot_path_sanitizes_save_name_for_windows(tmp_path):
    # Caractères interdits sous Windows
    p = snapshot_path("Bad/Name:Test", "abc123def456")
    assert "/" not in p.name
    assert ":" not in p.name


def test_snapshot_path_handles_empty_sha(tmp_path):
    p = snapshot_path("S", "")
    # Pas de crash, fallback "nosha"
    assert p.name.endswith(".json")
    assert "nosha" in p.name

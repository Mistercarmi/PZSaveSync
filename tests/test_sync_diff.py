"""Tests de l'intégration sync.py ↔ bundle différentiel (PR 4)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pzsavesync import bundle as bundle_mod
from pzsavesync import snapshot as snap_mod
from pzsavesync.bundle import BundleMode
from pzsavesync.diff_errors import (
    NoSnapshotAvailableError,
    ParentBundleSHAmismatchError,
)
from pzsavesync.sync import PushStats, SharedRepo, Version


@pytest.fixture(autouse=True)
def isolated_app_dir(tmp_path_factory, monkeypatch):
    """Isole APP_DIR pour ne pas polluer ~/PZSaveSync/snapshots."""
    fake = tmp_path_factory.mktemp("PZSaveSync_iso")
    monkeypatch.setattr(snap_mod, "APP_DIR", fake)
    return fake


def _make_minimal_zomboid(root: Path, save_name: str = "TestSave"):
    """Crée un faux Zomboid minimal avec une save jouable."""
    save_dir = root / "Saves" / "Multiplayer" / save_name
    save_dir.mkdir(parents=True)
    for i in range(5):
        (save_dir / f"map_{i}_{i}.bin").write_bytes(b"chunk-" + str(i).encode())
    (save_dir / "players.db").write_bytes(b"db-init")

    (root / "db").mkdir(parents=True)
    (root / "db" / f"{save_name}.db").write_bytes(b"server-db")
    (root / "Server").mkdir(parents=True)
    (root / "Server" / f"{save_name}.ini").write_text(
        "Mods=mod_a\nWorkshopItems=12345\n", encoding="utf-8",
    )
    (root / "Server" / f"{save_name}_SandboxVars.lua").write_text("x", encoding="utf-8")
    (root / "Server" / f"{save_name}_spawnregions.lua").write_text("y", encoding="utf-8")


# --------- push_bundle retourne (Version, PushStats) ---------

def test_push_bundle_returns_tuple_version_and_stats(tmp_path):
    zomboid = tmp_path / "zomboid"
    _make_minimal_zomboid(zomboid)
    repo = SharedRepo(tmp_path / "shared")

    result = repo.push_bundle("TestSave", "alice", root=zomboid)
    assert isinstance(result, tuple)
    assert len(result) == 2
    v, stats = result
    assert isinstance(v, Version)
    assert isinstance(stats, PushStats)
    assert stats.mode_used == "full"


def test_push_bundle_full_mode_sets_version_bundle_mode(tmp_path):
    zomboid = tmp_path / "zomboid"
    _make_minimal_zomboid(zomboid)
    repo = SharedRepo(tmp_path / "shared")

    v, stats = repo.push_bundle("TestSave", "alice", root=zomboid, mode=BundleMode.FULL)
    assert v.bundle_mode == "full"
    assert v.parent_bundle_sha256 == ""
    assert v.full_size_estimate_bytes > 0
    assert stats.mode_used == "full"
    assert stats.gain_ratio == 0.0  # full = pas de gain


def test_push_bundle_auto_falls_back_to_full_without_snapshot(tmp_path):
    """AUTO sans snapshot → mode FULL silencieux."""
    zomboid = tmp_path / "zomboid"
    _make_minimal_zomboid(zomboid)
    repo = SharedRepo(tmp_path / "shared")

    v, stats = repo.push_bundle("TestSave", "alice", root=zomboid, mode=BundleMode.AUTO)
    assert v.bundle_mode == "full"
    assert stats.mode_used == "full"


def test_push_bundle_diff_explicit_raises_without_snapshot(tmp_path):
    """mode=DIFF explicite sans snapshot → NoSnapshotAvailableError."""
    zomboid = tmp_path / "zomboid"
    _make_minimal_zomboid(zomboid)
    repo = SharedRepo(tmp_path / "shared")

    with pytest.raises(NoSnapshotAvailableError):
        repo.push_bundle("TestSave", "alice", root=zomboid, mode=BundleMode.DIFF)


# --------- pull_bundle crée un snapshot ---------

def test_pull_bundle_creates_snapshot_post_import(tmp_path):
    """Après pull réussi, un snapshot doit exister pour la save."""
    src_zomboid = tmp_path / "src"
    _make_minimal_zomboid(src_zomboid)
    repo = SharedRepo(tmp_path / "shared")

    v, _stats = repo.push_bundle("TestSave", "alice", root=src_zomboid)

    # Pull dans un Zomboid vide
    dst_zomboid = tmp_path / "dst"
    dst_zomboid.mkdir()
    import os
    monkey_env = os.environ.copy()
    os.environ["PZ_ZOMBOID_ROOT"] = str(dst_zomboid)
    try:
        backups = tmp_path / "backups"
        repo.pull_bundle(v, backup_dir=backups)
    finally:
        os.environ.clear()
        os.environ.update(monkey_env)

    # Snapshot doit avoir été créé
    snap = snap_mod.find_latest_snapshot_for_save("TestSave")
    assert snap is not None
    assert snap.save_name == "TestSave"
    assert snap.parent_bundle_sha256  # non vide


def test_pull_bundle_snapshot_enables_diff_push(tmp_path, monkeypatch):
    """Workflow complet : pull crée snapshot → push DIFF fonctionne."""
    src_zomboid = tmp_path / "src"
    _make_minimal_zomboid(src_zomboid)
    repo = SharedRepo(tmp_path / "shared")

    v_seed, _ = repo.push_bundle("TestSave", "alice", root=src_zomboid)

    dst_zomboid = tmp_path / "dst"
    dst_zomboid.mkdir()
    monkeypatch.setenv("PZ_ZOMBOID_ROOT", str(dst_zomboid))
    backups = tmp_path / "backups"
    repo.pull_bundle(v_seed, backup_dir=backups)

    # Modifie un fichier dans la save extraite
    map_file = dst_zomboid / "Saves" / "Multiplayer" / "TestSave" / "map_0_0.bin"
    map_file.write_bytes(b"chunk-MODIFIED")
    # Ajoute un nouveau fichier
    new_file = dst_zomboid / "Saves" / "Multiplayer" / "TestSave" / "map_9_9.bin"
    new_file.write_bytes(b"new-chunk")

    # Push DIFF doit fonctionner maintenant
    v_diff, stats = repo.push_bundle(
        "TestSave", "bob", root=dst_zomboid, mode=BundleMode.AUTO,
    )
    assert v_diff.bundle_mode == "diff"
    assert stats.mode_used == "diff"
    assert v_diff.parent_bundle_sha256  # SHA du seed
    # Le bundle diff doit être significativement plus petit que le seed
    assert v_diff.size_bytes < v_seed.size_bytes


def test_push_bundle_diff_detects_parent_sha_mismatch(tmp_path, monkeypatch):
    """Si l'hôte a poussé entre temps, DIFF doit détecter et raise."""
    src_zomboid = tmp_path / "src"
    _make_minimal_zomboid(src_zomboid)
    repo = SharedRepo(tmp_path / "shared")

    # 1. Alice push v1 (seed)
    v1, _ = repo.push_bundle("TestSave", "alice", root=src_zomboid)

    # 2. Bob pull v1 → snapshot créé pour v1
    bob_zomboid = tmp_path / "bob"
    bob_zomboid.mkdir()
    monkeypatch.setenv("PZ_ZOMBOID_ROOT", str(bob_zomboid))
    repo.pull_bundle(v1, backup_dir=tmp_path / "bob_backups")

    # 3. Alice push v2 (en cachette — modifie un fichier de sa save d'abord)
    monkeypatch.delenv("PZ_ZOMBOID_ROOT", raising=False)
    (src_zomboid / "Saves" / "Multiplayer" / "TestSave" / "map_1_1.bin").write_bytes(b"alice-update")
    import time
    time.sleep(1.1)  # timestamp distinct
    v2, _ = repo.push_bundle("TestSave", "alice", root=src_zomboid)

    # 4. Bob essaie de push un diff → il référence v1 mais latest est v2 → mismatch
    monkeypatch.setenv("PZ_ZOMBOID_ROOT", str(bob_zomboid))
    (bob_zomboid / "Saves" / "Multiplayer" / "TestSave" / "new_chunk.bin").write_bytes(b"bob-new")
    with pytest.raises(ParentBundleSHAmismatchError, match="autre joueur"):
        repo.push_bundle("TestSave", "bob", root=bob_zomboid, mode=BundleMode.DIFF)


def test_push_bundle_auto_silent_fallback_on_sha_mismatch(tmp_path, monkeypatch):
    """En mode AUTO, parent SHA mismatch → fallback FULL silencieux."""
    src_zomboid = tmp_path / "src"
    _make_minimal_zomboid(src_zomboid)
    repo = SharedRepo(tmp_path / "shared")

    v1, _ = repo.push_bundle("TestSave", "alice", root=src_zomboid)

    bob_zomboid = tmp_path / "bob"
    bob_zomboid.mkdir()
    monkeypatch.setenv("PZ_ZOMBOID_ROOT", str(bob_zomboid))
    repo.pull_bundle(v1, backup_dir=tmp_path / "bob_backups")

    # Alice push v2 derrière son dos
    monkeypatch.delenv("PZ_ZOMBOID_ROOT", raising=False)
    (src_zomboid / "Saves" / "Multiplayer" / "TestSave" / "map_1_1.bin").write_bytes(b"alice-update")
    import time
    time.sleep(1.1)
    repo.push_bundle("TestSave", "alice", root=src_zomboid)

    # Bob push en AUTO → fallback FULL silencieux (pas d'exception)
    monkeypatch.setenv("PZ_ZOMBOID_ROOT", str(bob_zomboid))
    (bob_zomboid / "Saves" / "Multiplayer" / "TestSave" / "new_chunk.bin").write_bytes(b"bob")
    v_bob, stats = repo.push_bundle("TestSave", "bob", root=bob_zomboid, mode=BundleMode.AUTO)
    assert v_bob.bundle_mode == "full"
    assert stats.mode_used == "full"


# --------- PushStats ---------

def test_push_stats_gain_ratio_for_diff(tmp_path, monkeypatch):
    """Le gain ratio est > 0 pour un diff."""
    src_zomboid = tmp_path / "src"
    _make_minimal_zomboid(src_zomboid)
    # Beaucoup de chunks pour augmenter la taille "full"
    for i in range(20):
        (src_zomboid / "Saves" / "Multiplayer" / "TestSave" / f"map_{i}_{i}.bin").write_bytes(
            b"x" * 1024
        )
    repo = SharedRepo(tmp_path / "shared")

    v1, _ = repo.push_bundle("TestSave", "alice", root=src_zomboid)

    bob_zomboid = tmp_path / "bob"
    bob_zomboid.mkdir()
    monkeypatch.setenv("PZ_ZOMBOID_ROOT", str(bob_zomboid))
    repo.pull_bundle(v1, backup_dir=tmp_path / "bob_backups")

    # Bob modifie 1 fichier
    (bob_zomboid / "Saves" / "Multiplayer" / "TestSave" / "map_0_0.bin").write_bytes(b"y" * 1024)

    v_diff, stats = repo.push_bundle("TestSave", "bob", root=bob_zomboid, mode=BundleMode.AUTO)
    assert stats.mode_used == "diff"
    assert stats.gain_ratio > 0.5  # économie significative attendue


# --------- Version sérialisation backward compat ---------

def test_old_manifest_without_v4_fields_still_loads(tmp_path):
    """Un manifest.json sans bundle_mode (cloud pré-v0.4) doit se charger sans erreur."""
    shared = tmp_path / "shared"
    repo = SharedRepo(shared)
    repo.init_if_needed()

    # Écris un manifest pré-v4
    old_manifest = {
        "versions": [{
            "filename": "bundle_old.zip",
            "save_name": "OldSave",
            "uploaded_by": "legacy",
            "uploaded_at": "2025-01-01T12:00:00",
            "size_bytes": 12345,
            "has_db": True,
            "server_files": ["OldSave.ini"],
            "note": "from v0.3",
            # PAS de bundle_mode, parent_bundle_sha256, full_size_estimate_bytes
        }]
    }
    repo.manifest_path.write_text(json.dumps(old_manifest, indent=2), encoding="utf-8")

    versions = repo.list_versions()
    assert len(versions) == 1
    assert versions[0].bundle_mode == "full"  # default appliqué
    assert versions[0].parent_bundle_sha256 == ""
    assert versions[0].full_size_estimate_bytes == 0


def test_new_manifest_with_v4_fields_serializes_back(tmp_path):
    """Round-trip : Version → dict → Version conserve les champs v4."""
    zomboid = tmp_path / "zomboid"
    _make_minimal_zomboid(zomboid)
    repo = SharedRepo(tmp_path / "shared")

    v, _ = repo.push_bundle("TestSave", "alice", root=zomboid)

    # Re-list → doit lire les nouveaux champs depuis le manifest
    versions = repo.list_versions()
    assert len(versions) == 1
    v2 = versions[0]
    assert v2.bundle_mode == "full"
    assert v2.full_size_estimate_bytes == v.full_size_estimate_bytes

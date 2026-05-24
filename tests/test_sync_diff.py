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
    DiffTooBigError,
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


def _use_app_dir(monkeypatch, path: Path) -> None:
    """Bascule APP_DIR pour simuler un autre utilisateur (machine distincte).

    Depuis v0.5.x, le push crée aussi un snapshot post-push (pour habiliter le
    DIFF au prochain push sans pull intermédiaire). Donc tester un scénario
    Alice+Bob suppose des APP_DIR séparés — sinon Alice "voit" le snapshot
    fraîchement créé par Bob et vice-versa, ce qui ne reflète pas la réalité
    (deux machines, deux dossiers locaux).
    """
    path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(snap_mod, "APP_DIR", path)


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
    alice_app = tmp_path / "alice_app"
    bob_app = tmp_path / "bob_app"

    # 1. Alice push v1 (seed) — dans son APP_DIR
    _use_app_dir(monkeypatch, alice_app)
    v1, _ = repo.push_bundle("TestSave", "alice", root=src_zomboid)

    # 2. Bob pull v1 → snapshot créé pour v1 (dans SON APP_DIR)
    bob_zomboid = tmp_path / "bob"
    bob_zomboid.mkdir()
    monkeypatch.setenv("PZ_ZOMBOID_ROOT", str(bob_zomboid))
    _use_app_dir(monkeypatch, bob_app)
    repo.pull_bundle(v1, backup_dir=tmp_path / "bob_backups")

    # 3. Alice push v2 (en cachette — modifie un fichier de sa save d'abord)
    monkeypatch.delenv("PZ_ZOMBOID_ROOT", raising=False)
    _use_app_dir(monkeypatch, alice_app)
    (src_zomboid / "Saves" / "Multiplayer" / "TestSave" / "map_1_1.bin").write_bytes(b"alice-update")
    import time
    time.sleep(1.1)  # timestamp distinct
    v2, _ = repo.push_bundle("TestSave", "alice", root=src_zomboid)

    # 4. Bob essaie de push un diff → il référence v1 mais latest est v2 → mismatch
    monkeypatch.setenv("PZ_ZOMBOID_ROOT", str(bob_zomboid))
    _use_app_dir(monkeypatch, bob_app)
    (bob_zomboid / "Saves" / "Multiplayer" / "TestSave" / "new_chunk.bin").write_bytes(b"bob-new")
    with pytest.raises(ParentBundleSHAmismatchError, match="autre joueur"):
        repo.push_bundle("TestSave", "bob", root=bob_zomboid, mode=BundleMode.DIFF)


def test_push_bundle_auto_silent_fallback_on_sha_mismatch(tmp_path, monkeypatch):
    """En mode AUTO, parent SHA mismatch → fallback FULL silencieux."""
    src_zomboid = tmp_path / "src"
    _make_minimal_zomboid(src_zomboid)
    repo = SharedRepo(tmp_path / "shared")
    alice_app = tmp_path / "alice_app"
    bob_app = tmp_path / "bob_app"

    _use_app_dir(monkeypatch, alice_app)
    v1, _ = repo.push_bundle("TestSave", "alice", root=src_zomboid)

    bob_zomboid = tmp_path / "bob"
    bob_zomboid.mkdir()
    monkeypatch.setenv("PZ_ZOMBOID_ROOT", str(bob_zomboid))
    _use_app_dir(monkeypatch, bob_app)
    repo.pull_bundle(v1, backup_dir=tmp_path / "bob_backups")

    # Alice push v2 derrière son dos
    monkeypatch.delenv("PZ_ZOMBOID_ROOT", raising=False)
    _use_app_dir(monkeypatch, alice_app)
    (src_zomboid / "Saves" / "Multiplayer" / "TestSave" / "map_1_1.bin").write_bytes(b"alice-update")
    import time
    time.sleep(1.1)
    repo.push_bundle("TestSave", "alice", root=src_zomboid)

    # Bob push en AUTO → fallback FULL silencieux (pas d'exception)
    monkeypatch.setenv("PZ_ZOMBOID_ROOT", str(bob_zomboid))
    _use_app_dir(monkeypatch, bob_app)
    (bob_zomboid / "Saves" / "Multiplayer" / "TestSave" / "new_chunk.bin").write_bytes(b"bob")
    v_bob, stats = repo.push_bundle("TestSave", "bob", root=bob_zomboid, mode=BundleMode.AUTO)
    assert v_bob.bundle_mode == "full"
    assert stats.mode_used == "full"


# --------- Snapshot post-push (v0.5.x) ---------

def test_push_creates_snapshot_to_enable_next_diff(tmp_path):
    """v0.5.x : un push (FULL ou DIFF) crée un snapshot post-push, pour que
    l'hôte initial puisse faire DIFF dès son 2e push sans avoir à pull.
    """
    zomboid = tmp_path / "zomboid"
    _make_minimal_zomboid(zomboid)
    repo = SharedRepo(tmp_path / "shared")

    # 1er push FULL — snapshot doit être créé post-push
    v1, _ = repo.push_bundle("TestSave", "alice", root=zomboid)
    snap = snap_mod.find_latest_snapshot_for_save("TestSave")
    assert snap is not None, "snapshot post-push manquant"
    assert snap.parent_bundle_filename == v1.filename
    assert snap.parent_bundle_sha256  # non-vide
    assert snap.save_files  # contient des hashes


def test_host_second_push_uses_diff_without_pull(tmp_path):
    """v0.5.x : l'hôte qui pousse, joue, repush voit son 2e push devenir DIFF
    automatiquement grâce au snapshot post-push (avant ça il restait FULL).
    """
    zomboid = tmp_path / "zomboid"
    _make_minimal_zomboid(zomboid)
    # Beaucoup de chunks pour rendre le gain mesurable
    for i in range(20):
        (zomboid / "Saves" / "Multiplayer" / "TestSave" / f"map_{i}_{i}.bin").write_bytes(
            b"x" * 1024
        )
    repo = SharedRepo(tmp_path / "shared")

    # Push 1 (FULL forcé car aucun snapshot pré-existant)
    v1, stats1 = repo.push_bundle("TestSave", "alice", root=zomboid, mode=BundleMode.AUTO)
    assert stats1.mode_used == "full"

    # Hôte joue : modifie 1 fichier
    import time
    time.sleep(1.1)
    (zomboid / "Saves" / "Multiplayer" / "TestSave" / "map_0_0.bin").write_bytes(b"played")

    # Push 2 en AUTO → doit être DIFF maintenant (sans pull !)
    v2, stats2 = repo.push_bundle("TestSave", "alice", root=zomboid, mode=BundleMode.AUTO)
    assert stats2.mode_used == "diff", \
        "le 2e push de l'hôte devrait être DIFF grâce au snapshot post-push"
    assert v2.bundle_mode == "diff"
    assert v2.parent_bundle_sha256  # référence v1
    assert v2.size_bytes < v1.size_bytes  # gain effectif


def test_push_diff_then_next_push_also_diff(tmp_path, monkeypatch):
    """Après un push DIFF, un nouveau snapshot post-push doit aussi être créé
    pour permettre le DIFF suivant (chaîne DIFF → DIFF → DIFF).
    """
    src_zomboid = tmp_path / "src"
    _make_minimal_zomboid(src_zomboid)
    for i in range(20):
        (src_zomboid / "Saves" / "Multiplayer" / "TestSave" / f"map_{i}_{i}.bin").write_bytes(
            b"x" * 1024
        )
    repo = SharedRepo(tmp_path / "shared")

    # Seed FULL côté Alice
    v1, _ = repo.push_bundle("TestSave", "alice", root=src_zomboid, mode=BundleMode.AUTO)

    # Alice joue + push DIFF
    import time
    (src_zomboid / "Saves" / "Multiplayer" / "TestSave" / "map_0_0.bin").write_bytes(b"play1")
    time.sleep(1.1)
    v2, stats2 = repo.push_bundle("TestSave", "alice", root=src_zomboid, mode=BundleMode.AUTO)
    assert stats2.mode_used == "diff"

    # Alice rejoue + repush DIFF (snapshot post-DIFF doit pointer sur v2)
    (src_zomboid / "Saves" / "Multiplayer" / "TestSave" / "map_1_1.bin").write_bytes(b"play2")
    time.sleep(1.1)
    v3, stats3 = repo.push_bundle("TestSave", "alice", root=src_zomboid, mode=BundleMode.AUTO)
    assert stats3.mode_used == "diff", "chaîne DIFF → DIFF cassée"
    # v3 doit référencer v2 comme parent (et pas v1)
    v2_manifest = bundle_mod.read_manifest(repo.versions_dir / v2.filename)
    assert v3.parent_bundle_sha256 == v2_manifest.sha256


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


# --------- FIX 1 : DiffTooBig fallback FULL en mode AUTO ---------

def test_push_auto_fallbacks_full_when_diff_too_big(tmp_path, monkeypatch):
    """v0.4.0 FIX 1 : si > 85% des chunks ont changé, mode AUTO doit
    fallback silencieusement en FULL, pas crasher.
    """
    src_zomboid = tmp_path / "src"
    _make_minimal_zomboid(src_zomboid)
    repo = SharedRepo(tmp_path / "shared")

    # Push seed initial
    v1, _ = repo.push_bundle("TestSave", "alice", root=src_zomboid)

    bob_zomboid = tmp_path / "bob"
    bob_zomboid.mkdir()
    monkeypatch.setenv("PZ_ZOMBOID_ROOT", str(bob_zomboid))
    repo.pull_bundle(v1, backup_dir=tmp_path / "bob_backups")

    # Bob modifie 100% des fichiers (situation type "sandbox refresh complet")
    bob_save = bob_zomboid / "Saves" / "Multiplayer" / "TestSave"
    for f in bob_save.rglob("*"):
        if f.is_file():
            f.write_bytes(b"completely-different-content-" + f.name.encode())

    # Push en mode AUTO : doit fallback FULL silencieusement (sans crash)
    v_bob, stats = repo.push_bundle(
        "TestSave", "bob", root=bob_zomboid, mode=BundleMode.AUTO,
    )
    assert v_bob.bundle_mode == "full", \
        f"AUTO devrait fallback en FULL, pas {v_bob.bundle_mode}"
    assert stats.mode_used == "full"


def test_push_diff_explicit_propagates_diff_too_big(tmp_path, monkeypatch):
    """En mode DIFF explicite, DiffTooBigError est propagée (UI décide)."""
    src_zomboid = tmp_path / "src"
    _make_minimal_zomboid(src_zomboid)
    repo = SharedRepo(tmp_path / "shared")

    v1, _ = repo.push_bundle("TestSave", "alice", root=src_zomboid)

    bob_zomboid = tmp_path / "bob"
    bob_zomboid.mkdir()
    monkeypatch.setenv("PZ_ZOMBOID_ROOT", str(bob_zomboid))
    repo.pull_bundle(v1, backup_dir=tmp_path / "bob_backups")

    bob_save = bob_zomboid / "Saves" / "Multiplayer" / "TestSave"
    for f in bob_save.rglob("*"):
        if f.is_file():
            f.write_bytes(b"completely-different-" + f.name.encode())

    with pytest.raises(DiffTooBigError):
        repo.push_bundle("TestSave", "bob", root=bob_zomboid, mode=BundleMode.DIFF)


def test_push_auto_no_leftover_after_diff_fallback(tmp_path, monkeypatch):
    """Le retry FULL ne laisse pas de .tmp orphelin du diff avorté."""
    src_zomboid = tmp_path / "src"
    _make_minimal_zomboid(src_zomboid)
    repo = SharedRepo(tmp_path / "shared")

    v1, _ = repo.push_bundle("TestSave", "alice", root=src_zomboid)

    bob_zomboid = tmp_path / "bob"
    bob_zomboid.mkdir()
    monkeypatch.setenv("PZ_ZOMBOID_ROOT", str(bob_zomboid))
    repo.pull_bundle(v1, backup_dir=tmp_path / "bob_backups")

    bob_save = bob_zomboid / "Saves" / "Multiplayer" / "TestSave"
    for f in bob_save.rglob("*"):
        if f.is_file():
            f.write_bytes(b"big-change-" + f.name.encode())

    v_bob, _ = repo.push_bundle("TestSave", "bob", root=bob_zomboid, mode=BundleMode.AUTO)

    # Aucun .tmp ne doit rester dans versions/
    tmps = list(repo.versions_dir.glob("*.tmp"))
    assert tmps == [], f"Fichiers .tmp orphelins après fallback : {tmps}"


# --------- Version sérialisation backward compat ---------

# --------- FIX 4 : prune_versions protège le FULL parent de DIFFs ---------

def test_prune_versions_protects_full_parent_of_diff(tmp_path, monkeypatch):
    """v0.4.0 FIX 4 : si keep_last_n=2 garde 2 DIFFs, le FULL parent reste
    protégé même s'il serait censé être supprimé (sinon bug FIX 3).
    """
    src_zomboid = tmp_path / "src"
    _make_minimal_zomboid(src_zomboid)
    repo = SharedRepo(tmp_path / "shared")

    # Push FULL v1
    v1_full, _ = repo.push_bundle("TestSave", "alice", root=src_zomboid)
    assert v1_full.bundle_mode == "full"

    # Bob pull → snapshot créé
    bob_zomboid = tmp_path / "bob"
    bob_zomboid.mkdir()
    monkeypatch.setenv("PZ_ZOMBOID_ROOT", str(bob_zomboid))
    repo.pull_bundle(v1_full, backup_dir=tmp_path / "bob_backups")

    # Bob push 2 DIFFs (avec petites modifs)
    import time
    bob_save = bob_zomboid / "Saves" / "Multiplayer" / "TestSave"
    (bob_save / "map_0_0.bin").write_bytes(b"modif-1")
    time.sleep(1.1)
    v2_diff, _ = repo.push_bundle(
        "TestSave", "bob", root=bob_zomboid, mode=BundleMode.AUTO,
    )
    assert v2_diff.bundle_mode == "diff"

    (bob_save / "map_1_1.bin").write_bytes(b"modif-2")
    time.sleep(1.1)
    # Forcer un push DIFF (mode AUTO) — mais ça va échouer car parent SHA mismatch
    # Donc on adapte : on doit re-pull pour avoir un nouveau snapshot, ou pousser
    # un FULL et garder le test simple. Simplifions : forcer build via le mode.
    # En fait, simplifier : 3 versions total dont 1 FULL + 2 DIFF.
    # Pour cette 2e diff il faut un snapshot à jour. Pull la v2.
    repo.pull_bundle(v2_diff, backup_dir=tmp_path / "bob_backups")
    (bob_save / "map_1_1.bin").write_bytes(b"modif-3")
    v3_diff, _ = repo.push_bundle(
        "TestSave", "bob", root=bob_zomboid, mode=BundleMode.AUTO,
    )
    # v3 peut être full ou diff selon les conditions, l'important c'est qu'on ait
    # au moins une version qui pointe v1_full comme parent.

    versions_before = repo.list_versions()
    assert len(versions_before) == 3

    # Tentative de prune keep_last_n=2 (devrait supprimer v1, mais v2 le référence)
    deleted = repo.prune_versions(keep_last_n=2, save_name="TestSave")

    versions_after = repo.list_versions()
    # Le FULL v1 doit être protégé car au moins un DIFF kept le référence
    filenames_after = [v.filename for v in versions_after]
    if v2_diff.parent_bundle_sha256 or v3_diff.parent_bundle_sha256:
        # Au moins un DIFF référence v1_full → v1_full doit être préservé
        assert v1_full.filename in filenames_after, \
            "v1_full devrait être protégé car parent d'un DIFF gardé"


def test_prune_versions_can_delete_full_with_no_diff_children(tmp_path, monkeypatch):
    """Si aucun DIFF ne référence un FULL, prune peut le supprimer normalement."""
    src_zomboid = tmp_path / "src"
    _make_minimal_zomboid(src_zomboid)
    repo = SharedRepo(tmp_path / "shared")

    # Push 3 FULLs successifs (mode FULL forcé, donc pas de parent_sha)
    import time
    versions = []
    for i in range(3):
        if i > 0:
            time.sleep(1.1)
        v, _ = repo.push_bundle(
            f"TestSave", f"user{i}", root=src_zomboid, mode=BundleMode.FULL,
        )
        assert v.bundle_mode == "full"
        versions.append(v)

    # prune keep_last_n=2 doit supprimer le 1er
    deleted = repo.prune_versions(keep_last_n=2, save_name="TestSave")
    assert versions[0].filename in deleted


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

"""Tests du mode bundle différentiel (v0.4.0 PR 3).

Couvre _build_diff_bundle + _extract_diff_overlay + leurs interactions
avec snapshot.py. Le snapshot post-import et l'intégration sync.py sont
testés en PR 4.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pzsavesync import bundle as bundle_mod
from pzsavesync import snapshot as snap_mod
from pzsavesync.bundle import BundleMode
from pzsavesync.diff_errors import (
    DiffTooBigError,
    NoSnapshotAvailableError,
)
from pzsavesync.snapshot import compute_snapshot


@pytest.fixture(autouse=True)
def isolated_app_dir(tmp_path_factory, monkeypatch):
    """Isole APP_DIR pour ne pas polluer ~/PZSaveSync/snapshots."""
    fake = tmp_path_factory.mktemp("PZSaveSync_iso")
    monkeypatch.setattr(snap_mod, "APP_DIR", fake)
    return fake


def _make_save_with_files(root: Path, save_name: str, files: dict[str, bytes]) -> Path:
    """Construit une save_dir factice avec les fichiers donnés (path POSIX → bytes)."""
    save_dir = root / "Saves" / "Multiplayer" / save_name
    save_dir.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = save_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    (root / "db").mkdir(parents=True, exist_ok=True)
    (root / "Server").mkdir(parents=True, exist_ok=True)
    return save_dir


# --------- _build_diff_bundle : signatures + guards ---------

def test_build_bundle_diff_requires_parent_snapshot(tmp_path):
    _make_save_with_files(tmp_path, "S", {"a.bin": b"x"})
    out = tmp_path / "out.zip"
    with pytest.raises(NoSnapshotAvailableError):
        bundle_mod.build_bundle(
            "S", out, "me", root=tmp_path, mode=BundleMode.DIFF,
        )


def test_build_bundle_auto_falls_back_to_full_when_no_snapshot(tmp_path, fake_zomboid):
    """AUTO sans snapshot → mode FULL silencieux (comportement v0.3 conservé)."""
    out = tmp_path / "auto.zip"
    manifest = bundle_mod.build_bundle(
        "testsave", out, "me", root=fake_zomboid, mode=BundleMode.AUTO,
    )
    assert manifest.bundle_mode == "full"


def test_build_bundle_auto_uses_diff_when_snapshot_provided(tmp_path):
    save_dir = _make_save_with_files(tmp_path, "S", {"a.bin": b"x"})
    snap = compute_snapshot(save_dir, "S", "parent_sha_xyz", "src.zip")
    out = tmp_path / "auto.zip"
    manifest = bundle_mod.build_bundle(
        "S", out, "me", root=tmp_path, mode=BundleMode.AUTO, parent_snapshot=snap,
    )
    assert manifest.bundle_mode == "diff"


# --------- _build_diff_bundle : contenu du zip ---------

def test_diff_bundle_includes_only_added_and_modified(tmp_path):
    save_dir = _make_save_with_files(tmp_path, "S", {
        "unchanged.bin": b"v1",
        "to_modify.bin": b"v1",
    })
    snap = compute_snapshot(save_dir, "S", "parent_sha_abc", "src.zip")
    # Ajoute "new.bin" et modifie "to_modify.bin"
    (save_dir / "new.bin").write_bytes(b"hello")
    (save_dir / "to_modify.bin").write_bytes(b"v2")
    out = tmp_path / "diff.zip"

    manifest = bundle_mod.build_bundle(
        "S", out, "me", root=tmp_path, mode=BundleMode.DIFF, parent_snapshot=snap,
    )

    # Le manifest liste les fichiers diffs
    assert "new.bin" in manifest.diff_files
    assert "to_modify.bin" in manifest.diff_files
    assert "unchanged.bin" not in manifest.diff_files
    # expected_save_files reflète l'état COMPLET attendu (3 fichiers)
    assert set(manifest.expected_save_files.keys()) == {"unchanged.bin", "to_modify.bin", "new.bin"}


def test_diff_bundle_excludes_server_and_db_by_default(tmp_path):
    """Même si l'hôte a une .db et des fichiers server, le diff ne les inclut pas."""
    save_dir = _make_save_with_files(tmp_path, "S", {"a.bin": b"x"})
    # Crée des fichiers server/db (qui ne devraient PAS être inclus)
    (tmp_path / "db" / "S.db").write_bytes(b"db-bytes")
    (tmp_path / "Server" / "S.ini").write_text("Mods=\nWorkshopItems=\n", encoding="utf-8")

    snap = compute_snapshot(save_dir, "S", "parent_sha", "src.zip")
    (save_dir / "new.bin").write_bytes(b"hi")
    out = tmp_path / "diff.zip"

    manifest = bundle_mod.build_bundle(
        "S", out, "me", root=tmp_path, mode=BundleMode.DIFF, parent_snapshot=snap,
    )

    import zipfile
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    # Aucun fichier db/ ou server/
    assert not any(n.startswith("db/") for n in names)
    assert not any(n.startswith("server/") for n in names)
    # Seulement save/new.bin + manifest
    assert "save/new.bin" in names
    assert "db" in manifest.excluded_categories
    assert "server" in manifest.excluded_categories


def test_diff_bundle_skips_redundant_lua_patterns(tmp_path):
    """Les WorldDictionaryReadable.lua et WorldDictionaryLog.lua sont exclus du diff."""
    save_dir = _make_save_with_files(tmp_path, "S", {
        "WorldDictionaryReadable.lua": b"old-cache",
        "WorldDictionaryLog.lua": b"old-log",
        "map_1_1.bin": b"chunk",
        "map_1_2.bin": b"chunk-stable",  # ne sera pas modifié
        "map_1_3.bin": b"chunk-stable-2",
    })
    snap = compute_snapshot(save_dir, "S", "parent_sha", "src.zip")
    # Modifie les 2 Lua (redondants) + 1 chunk → 1/3 chunks modifiés = 33%
    (save_dir / "WorldDictionaryReadable.lua").write_bytes(b"new-cache")
    (save_dir / "WorldDictionaryLog.lua").write_bytes(b"new-log")
    (save_dir / "map_1_1.bin").write_bytes(b"chunk-updated")

    out = tmp_path / "diff.zip"
    manifest = bundle_mod.build_bundle(
        "S", out, "me", root=tmp_path, mode=BundleMode.DIFF, parent_snapshot=snap,
    )

    # Les Lua redundants sont exclus, le chunk est inclus
    assert "WorldDictionaryReadable.lua" not in manifest.diff_files
    assert "WorldDictionaryLog.lua" not in manifest.diff_files
    assert "map_1_1.bin" in manifest.diff_files


def test_diff_bundle_raises_if_too_many_changes(tmp_path):
    """Si > 85% des fichiers du snapshot ont changé → DiffTooBigError."""
    files = {f"f_{i}.bin": b"v1" for i in range(10)}
    save_dir = _make_save_with_files(tmp_path, "S", files)
    snap = compute_snapshot(save_dir, "S", "parent_sha", "src.zip")
    # Modifie 9 fichiers sur 10 (90% > 85%)
    for i in range(9):
        (save_dir / f"f_{i}.bin").write_bytes(b"v2")

    out = tmp_path / "diff.zip"
    with pytest.raises(DiffTooBigError):
        bundle_mod.build_bundle(
            "S", out, "me", root=tmp_path, mode=BundleMode.DIFF, parent_snapshot=snap,
        )


def test_diff_bundle_records_parent_metadata(tmp_path):
    """Le manifest diff contient parent_bundle_sha256 et parent_bundle_filename."""
    save_dir = _make_save_with_files(tmp_path, "S", {"a.bin": b"x"})
    snap = compute_snapshot(save_dir, "S", "abc123def456789", "source_bundle.zip")
    (save_dir / "new.bin").write_bytes(b"y")
    out = tmp_path / "diff.zip"

    manifest = bundle_mod.build_bundle(
        "S", out, "me", root=tmp_path, mode=BundleMode.DIFF, parent_snapshot=snap,
    )
    assert manifest.parent_bundle_sha256 == "abc123def456789"
    assert manifest.parent_bundle_filename == "source_bundle.zip"


def test_diff_bundle_has_sha256_for_integrity_check(tmp_path):
    save_dir = _make_save_with_files(tmp_path, "S", {"a.bin": b"x"})
    snap = compute_snapshot(save_dir, "S", "parent", "src.zip")
    (save_dir / "new.bin").write_bytes(b"y")
    out = tmp_path / "diff.zip"
    manifest = bundle_mod.build_bundle(
        "S", out, "me", root=tmp_path, mode=BundleMode.DIFF, parent_snapshot=snap,
    )
    assert manifest.sha256
    # verify_bundle_integrity doit valider
    ok, msg = bundle_mod.verify_bundle_integrity(out)
    assert ok, msg


# --------- _extract_diff_overlay : comportement overlay ---------

def test_overlay_preserves_unlisted_local_files(tmp_path):
    """Hôte a des fichiers locaux non listés dans le diff → ils sont préservés."""
    # Setup hôte avec save existante
    host_root = tmp_path / "host"
    host_save = _make_save_with_files(host_root, "S", {
        "a.bin": b"v1",
        "b.bin": b"v1-b",
        "c.bin": b"v1-c",
        "preserved.bin": b"local-only",  # n'a JAMAIS été dans le snapshot client
    })

    # Setup client : snapshot connaît a.bin, b.bin, c.bin (pas preserved.bin)
    client_root = tmp_path / "client"
    client_save = _make_save_with_files(client_root, "S", {
        "a.bin": b"v1",
        "b.bin": b"v1-b",
        "c.bin": b"v1-c",
    })
    snap = compute_snapshot(client_save, "S", "parent_sha", "src.zip")
    # Client modifie a.bin (1/3 = 33% modifié, sous le seuil) et ajoute new.bin
    (client_save / "a.bin").write_bytes(b"v2")
    (client_save / "new.bin").write_bytes(b"hello")

    # Client construit son diff
    diff_zip = tmp_path / "client_diff.zip"
    bundle_mod.build_bundle(
        "S", diff_zip, "client", root=client_root, mode=BundleMode.DIFF, parent_snapshot=snap,
    )

    # Hôte applique l'overlay
    bundle_mod.extract_bundle(
        diff_zip, root=host_root, verify_hash=True, allow_no_backup=True,
    )

    # Vérifie : a.bin mis à jour, new.bin ajouté, preserved.bin INTACT
    assert (host_save / "a.bin").read_bytes() == b"v2"
    assert (host_save / "new.bin").read_bytes() == b"hello"
    assert (host_save / "preserved.bin").read_bytes() == b"local-only"


def test_overlay_does_not_touch_db_files(tmp_path):
    """L'overlay ne touche pas Zomboid/db/* — l'hôte garde son cache SQLite local."""
    host_root = tmp_path / "host"
    _make_save_with_files(host_root, "S", {"a.bin": b"x"})
    (host_root / "db" / "S.db").write_bytes(b"host-db-content")

    # Client crée un diff
    client_root = tmp_path / "client"
    client_save = _make_save_with_files(client_root, "S", {"a.bin": b"x"})
    snap = compute_snapshot(client_save, "S", "parent_sha", "src.zip")
    (client_save / "new.bin").write_bytes(b"y")
    diff_zip = tmp_path / "diff.zip"
    bundle_mod.build_bundle(
        "S", diff_zip, "client", root=client_root, mode=BundleMode.DIFF, parent_snapshot=snap,
    )

    bundle_mod.extract_bundle(
        diff_zip, root=host_root, verify_hash=True, allow_no_backup=True,
    )

    # Le .db de l'hôte est intact
    assert (host_root / "db" / "S.db").read_bytes() == b"host-db-content"


def test_overlay_does_not_touch_server_config(tmp_path):
    """L'overlay ne touche pas Zomboid/Server/* — l'hôte garde sa config serveur."""
    host_root = tmp_path / "host"
    _make_save_with_files(host_root, "S", {"a.bin": b"x"})
    (host_root / "Server" / "S.ini").write_text("Mods=mod_host\n", encoding="utf-8")
    (host_root / "Server" / "S_SandboxVars.lua").write_text("HostSandbox=1", encoding="utf-8")

    client_root = tmp_path / "client"
    client_save = _make_save_with_files(client_root, "S", {"a.bin": b"x"})
    snap = compute_snapshot(client_save, "S", "parent_sha", "src.zip")
    (client_save / "new.bin").write_bytes(b"y")
    diff_zip = tmp_path / "diff.zip"
    bundle_mod.build_bundle(
        "S", diff_zip, "client", root=client_root, mode=BundleMode.DIFF, parent_snapshot=snap,
    )

    bundle_mod.extract_bundle(
        diff_zip, root=host_root, verify_hash=True, allow_no_backup=True,
    )

    assert (host_root / "Server" / "S.ini").read_text(encoding="utf-8") == "Mods=mod_host\n"
    assert (host_root / "Server" / "S_SandboxVars.lua").read_text(encoding="utf-8") == "HostSandbox=1"


def test_overlay_creates_save_dir_if_missing(tmp_path):
    """Si la save_dir hôte n'existe pas (cas edge), overlay la crée et y dépose les fichiers."""
    host_root = tmp_path / "host"
    host_root.mkdir()

    client_root = tmp_path / "client"
    client_save = _make_save_with_files(client_root, "S", {"a.bin": b"x"})
    snap = compute_snapshot(client_save, "S", "parent_sha", "src.zip")
    (client_save / "new.bin").write_bytes(b"y")
    diff_zip = tmp_path / "diff.zip"
    bundle_mod.build_bundle(
        "S", diff_zip, "client", root=client_root, mode=BundleMode.DIFF, parent_snapshot=snap,
    )

    bundle_mod.extract_bundle(
        diff_zip, root=host_root, verify_hash=True, allow_no_backup=True,
    )

    target = host_root / "Saves" / "Multiplayer" / "S" / "new.bin"
    assert target.exists()
    assert target.read_bytes() == b"y"


# --------- Roundtrip complet ---------

def test_diff_bundle_full_roundtrip(tmp_path):
    """Cycle complet : seed full hôte → import client → snapshot → modifs → push diff →
    overlay hôte → état final cohérent.
    """
    # 1. HÔTE : crée save initiale et seed full
    host_root = tmp_path / "host"
    host_save = _make_save_with_files(host_root, "Gitano", {
        "map_1_1.bin": b"chunk-a",
        "map_1_2.bin": b"chunk-b",
        "players.db": b"db-init",
        "WorldDictionaryReadable.lua": b"cache-init",
    })
    seed_zip = tmp_path / "seed.zip"
    bundle_mod.build_bundle(
        "Gitano", seed_zip, "host", root=host_root,
    )
    # Récupère le sha pour simuler le parent
    seed_manifest = bundle_mod.read_manifest(seed_zip)

    # 2. CLIENT : extrait le seed
    client_root = tmp_path / "client"
    client_root.mkdir()
    bundle_mod.extract_bundle(
        seed_zip, root=client_root, verify_hash=True, allow_no_backup=True,
    )
    client_save = client_root / "Saves" / "Multiplayer" / "Gitano"
    assert (client_save / "map_1_1.bin").read_bytes() == b"chunk-a"

    # 3. CLIENT : calcule snapshot post-import
    snap = compute_snapshot(client_save, "Gitano", seed_manifest.sha256, "seed.zip")

    # 4. CLIENT : joue, modifie des choses
    (client_save / "map_1_1.bin").write_bytes(b"chunk-a-explored")
    (client_save / "map_2_5.bin").write_bytes(b"new-chunk")
    (client_save / "players.db").write_bytes(b"db-modified")
    # Modifie aussi un fichier "redondant" qui doit être exclu
    (client_save / "WorldDictionaryReadable.lua").write_bytes(b"cache-new")

    # 5. CLIENT : build diff
    diff_zip = tmp_path / "client_diff.zip"
    diff_manifest = bundle_mod.build_bundle(
        "Gitano", diff_zip, "client", root=client_root,
        mode=BundleMode.DIFF, parent_snapshot=snap,
    )
    assert diff_manifest.bundle_mode == "diff"
    assert "map_1_1.bin" in diff_manifest.diff_files
    assert "map_2_5.bin" in diff_manifest.diff_files
    assert "players.db" in diff_manifest.diff_files
    # Lua redondant exclu
    assert "WorldDictionaryReadable.lua" not in diff_manifest.diff_files

    # 6. HÔTE : applique l'overlay
    bundle_mod.extract_bundle(
        diff_zip, root=host_root, verify_hash=True, allow_no_backup=True,
    )

    # Vérifie : chunks mis à jour, nouveau chunk ajouté, db modifiée
    assert (host_save / "map_1_1.bin").read_bytes() == b"chunk-a-explored"
    assert (host_save / "map_2_5.bin").read_bytes() == b"new-chunk"
    assert (host_save / "players.db").read_bytes() == b"db-modified"
    # map_1_2.bin n'a pas été modifié, doit être intact (overlay préserve)
    assert (host_save / "map_1_2.bin").read_bytes() == b"chunk-b"
    # Lua exclu : la version hôte (cache-init) doit être préservée
    assert (host_save / "WorldDictionaryReadable.lua").read_bytes() == b"cache-init"


def test_diff_bundle_smaller_than_full(tmp_path):
    """Le diff bundle doit être significativement plus petit que le full équivalent."""
    # 100 fichiers de 1 KB chacun
    files = {f"map_{i}.bin": b"x" * 1024 for i in range(100)}
    save_dir = _make_save_with_files(tmp_path, "Big", files)

    # Full bundle
    full_zip = tmp_path / "full.zip"
    bundle_mod.build_bundle("Big", full_zip, "me", root=tmp_path)
    full_size = full_zip.stat().st_size

    # Diff : seulement 2 fichiers modifiés
    snap = compute_snapshot(save_dir, "Big", "parent_sha", "src.zip")
    (save_dir / "map_0.bin").write_bytes(b"y" * 1024)
    (save_dir / "map_1.bin").write_bytes(b"y" * 1024)

    diff_zip = tmp_path / "diff.zip"
    bundle_mod.build_bundle(
        "Big", diff_zip, "me", root=tmp_path, mode=BundleMode.DIFF, parent_snapshot=snap,
    )
    diff_size = diff_zip.stat().st_size

    # Le diff doit être au moins 10x plus petit (en pratique ~50x dans ce test)
    assert diff_size * 10 < full_size, (
        f"diff={diff_size} vs full={full_size} — gain insuffisant"
    )


def test_overlay_validation_logs_warning_on_divergence(tmp_path, caplog):
    """Si l'hôte a un fichier avec un hash différent de expected_save_files,
    on log un warning (mais on ne fail pas).
    """
    import logging
    caplog.set_level(logging.WARNING)

    host_root = tmp_path / "host"
    # L'hôte a "shared.bin" avec un contenu différent
    host_save = _make_save_with_files(host_root, "S", {
        "shared.bin": b"host-version",
    })

    client_root = tmp_path / "client"
    client_save = _make_save_with_files(client_root, "S", {"shared.bin": b"snap-version"})
    snap = compute_snapshot(client_save, "S", "parent_sha", "src.zip")
    # Client ajoute un fichier (mais ne modifie pas shared.bin)
    (client_save / "new.bin").write_bytes(b"y")
    diff_zip = tmp_path / "diff.zip"
    bundle_mod.build_bundle(
        "S", diff_zip, "client", root=client_root, mode=BundleMode.DIFF, parent_snapshot=snap,
    )

    bundle_mod.extract_bundle(
        diff_zip, root=host_root, verify_hash=True, allow_no_backup=True,
    )

    # L'overlay attend que shared.bin ait le hash "snap-version" mais l'hôte a "host-version"
    # → warning loggué (n'avorte pas)
    assert any("hash inattendu" in r.message for r in caplog.records)
    # Mais l'overlay a bien ajouté new.bin
    assert (host_save / "new.bin").exists()


# --------- Empty diff edge case ---------

def test_diff_bundle_with_no_changes_is_valid(tmp_path):
    """Diff sans changement → bundle valide avec diff_files vide."""
    save_dir = _make_save_with_files(tmp_path, "S", {"a.bin": b"x"})
    snap = compute_snapshot(save_dir, "S", "parent_sha", "src.zip")
    # Pas de modif

    out = tmp_path / "diff.zip"
    manifest = bundle_mod.build_bundle(
        "S", out, "me", root=tmp_path, mode=BundleMode.DIFF, parent_snapshot=snap,
    )
    assert manifest.bundle_mode == "diff"
    assert manifest.diff_files == []
    # Le manifest reste valide (expected_save_files non-vide)
    assert manifest.expected_save_files

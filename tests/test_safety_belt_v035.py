"""Tests pour les garde-fous v0.3.5 :
- Refus push save vide
- Clamp keep_last_n >= 2
- Health check du repo cloud (orphelins, fantômes, réintégration)
"""
from __future__ import annotations

import datetime as dt
import json
import zipfile
from pathlib import Path

import pytest

from pzsavesync import bundle as bundle_mod
from pzsavesync.sync import SharedRepo, Version


# -----------------------------------------------------------------------------
# #1 — refus push save vide
# -----------------------------------------------------------------------------

def test_build_bundle_refuses_empty_save(tmp_path):
    """build_bundle doit lever ValueError si save_dir est vide."""
    save_dir = tmp_path / "Saves" / "Multiplayer" / "EmptySave"
    save_dir.mkdir(parents=True)
    # Vide — on ne met aucun fichier
    (tmp_path / "Server").mkdir()
    (tmp_path / "db").mkdir()
    out = tmp_path / "out.zip"
    with pytest.raises(ValueError, match="vide"):
        bundle_mod.build_bundle("EmptySave", out, "alice", root=tmp_path)
    # Le zip ne doit pas avoir été créé
    assert not out.exists()


def test_build_bundle_accepts_save_with_at_least_one_file(tmp_path):
    """1 fichier suffit — le seuil est strict > 0."""
    save_dir = tmp_path / "Saves" / "Multiplayer" / "MinSave"
    save_dir.mkdir(parents=True)
    (save_dir / "map.bin").write_bytes(b"x")
    (tmp_path / "Server").mkdir(); (tmp_path / "db").mkdir()
    out = tmp_path / "out.zip"
    m = bundle_mod.build_bundle("MinSave", out, "alice", root=tmp_path)
    assert m.save_files == 1
    assert out.exists()


# -----------------------------------------------------------------------------
# #2 — clamp keep_last_n >= 2
# -----------------------------------------------------------------------------

def _stub_version(filename, save_name, days_ago=0):
    ts = (dt.datetime.now() - dt.timedelta(days=days_ago)).isoformat(timespec="seconds")
    return {
        "filename": filename, "save_name": save_name, "uploaded_by": "alice",
        "uploaded_at": ts, "size_bytes": 1024, "has_db": True,
        "server_files": [], "note": "",
    }


def test_prune_clamps_keep_last_n_to_minimum(tmp_path):
    """Si on demande keep_last_n=1, le clamp à 2 doit s'appliquer
    silencieusement pour préserver au moins un rollback."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    versions = [_stub_version(f"v{i}.zip", "SaveA", days_ago=10 - i) for i in range(5)]
    for v in versions:
        (repo.versions_dir / v["filename"]).write_bytes(b"x")
    data = repo._read_manifest(); data["versions"] = versions
    repo._write_manifest(data)

    # On demande keep=1 mais le clamp force à 2
    repo.prune_versions(keep_last_n=1, save_name="SaveA")
    remaining = {v.filename for v in repo.list_versions()}
    assert len(remaining) == 2  # pas 1
    assert "v4.zip" in remaining and "v3.zip" in remaining


def test_prune_clamps_zero_and_negative(tmp_path):
    """keep_last_n=0 ou négatif clampé à 2 aussi (anti suppression totale)."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    versions = [_stub_version(f"v{i}.zip", "SaveA", days_ago=5 - i) for i in range(3)]
    for v in versions:
        (repo.versions_dir / v["filename"]).write_bytes(b"x")
    data = repo._read_manifest(); data["versions"] = versions
    repo._write_manifest(data)

    repo.prune_versions(keep_last_n=0, save_name="SaveA")
    assert len(repo.list_versions()) == 2


def test_prune_keep_last_n_2_unchanged(tmp_path):
    """keep_last_n=2 fonctionne normalement (déjà au minimum)."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    versions = [_stub_version(f"v{i}.zip", "SaveA", days_ago=5 - i) for i in range(5)]
    for v in versions:
        (repo.versions_dir / v["filename"]).write_bytes(b"x")
    data = repo._read_manifest(); data["versions"] = versions
    repo._write_manifest(data)

    repo.prune_versions(keep_last_n=2, save_name="SaveA")
    assert len(repo.list_versions()) == 2


# -----------------------------------------------------------------------------
# #3 — health check repo cloud
# -----------------------------------------------------------------------------

def _make_legit_bundle(tmp_path: Path, save_name: str, out_zip: Path) -> None:
    """Crée un bundle PZSaveSync légitime (avec manifest interne)."""
    src = tmp_path / f"_src_{save_name}"
    src.mkdir(parents=True, exist_ok=True)
    sd = src / "Saves" / "Multiplayer" / save_name
    sd.mkdir(parents=True)
    (sd / "map.bin").write_bytes(b"x")
    (src / "Server").mkdir(); (src / "db").mkdir()
    bundle_mod.build_bundle(save_name, out_zip, "alice", root=src)


def test_health_check_clean_repo(tmp_path):
    """Repo propre : aucune anomalie."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    # Pousse une version régulière
    out = repo.versions_dir / "bundle_clean.zip"
    _make_legit_bundle(tmp_path, "clean", out)
    data = repo._read_manifest()
    data["versions"].append(_stub_version("bundle_clean.zip", "clean"))
    repo._write_manifest(data)

    h = repo.health_check()
    assert h.is_healthy
    assert h.orphan_files == []
    assert h.missing_files == []
    assert h.tmp_residues == []


def test_health_check_detects_orphan_zip(tmp_path):
    """Un .zip présent mais absent du manifest est détecté comme orphelin."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    # Pose un vrai bundle dans versions_dir SANS l'ajouter au manifest
    orphan = repo.versions_dir / "bundle_orphan.zip"
    _make_legit_bundle(tmp_path, "orphan", orphan)

    h = repo.health_check()
    assert "bundle_orphan.zip" in h.orphan_files
    assert len(h.readable_orphans) == 1
    assert h.readable_orphans[0][0] == "bundle_orphan.zip"
    assert h.readable_orphans[0][1].save_name == "orphan"


def test_health_check_detects_missing_files(tmp_path):
    """Entrée du manifest sans .zip physique = fantôme."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    data = repo._read_manifest()
    data["versions"].append(_stub_version("ghost.zip", "ghost"))
    repo._write_manifest(data)
    # Pas de fichier physique → fantôme
    h = repo.health_check()
    assert "ghost.zip" in h.missing_files


def test_health_check_detects_tmp_residues(tmp_path):
    """Les .tmp / .rwm.tmp sont signalés (et nettoyables)."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    (repo.versions_dir / "leftover.zip.tmp").write_bytes(b"x")
    (repo.versions_dir / "weird.rwm.tmp").write_bytes(b"x")
    h = repo.health_check()
    assert "leftover.zip.tmp" in h.tmp_residues
    assert "weird.rwm.tmp" in h.tmp_residues


def test_adopt_orphans_reintegrates_them(tmp_path):
    """adopt_orphans ajoute les bundles orphelins lisibles au manifest."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    orphan = repo.versions_dir / "bundle_recovered.zip"
    _make_legit_bundle(tmp_path, "recovered", orphan)

    h = repo.health_check()
    assert h.readable_orphans
    n = repo.adopt_orphans(h.readable_orphans)
    assert n == 1
    # Maintenant le manifest le voit
    versions = repo.list_versions()
    assert any(v.filename == "bundle_recovered.zip" for v in versions)
    # Et le health_check est clean (à part les .tmp si présents — ici aucun)
    h2 = repo.health_check()
    assert "bundle_recovered.zip" not in h2.orphan_files


def test_remove_missing_from_manifest(tmp_path):
    """remove_missing_from_manifest enlève les entrées fantômes."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    data = repo._read_manifest()
    data["versions"] = [
        _stub_version("real.zip", "S"),
        _stub_version("ghost.zip", "S"),
    ]
    repo._write_manifest(data)
    (repo.versions_dir / "real.zip").write_bytes(b"x")
    # ghost.zip pas créé

    h = repo.health_check()
    assert "ghost.zip" in h.missing_files
    removed = repo.remove_missing_from_manifest(h.missing_files)
    assert removed == 1
    assert {v.filename for v in repo.list_versions()} == {"real.zip"}


def test_repo_health_summary_text(tmp_path):
    """Le summary textuel reflète l'état."""
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    # Repo propre
    assert "OK" in repo.health_check().summary

    # Avec orphelin + fantôme + tmp
    orphan = repo.versions_dir / "bundle_orphan.zip"
    _make_legit_bundle(tmp_path, "orphan", orphan)
    data = repo._read_manifest()
    data["versions"].append(_stub_version("ghost.zip", "g"))
    repo._write_manifest(data)
    (repo.versions_dir / "trash.zip.tmp").write_bytes(b"x")

    summary = repo.health_check().summary
    assert "orphelin" in summary
    assert "sans .zip" in summary
    assert ".tmp" in summary

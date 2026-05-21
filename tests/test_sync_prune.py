"""Tests du nettoyage de l'historique des versions et de la recovery .tmp."""
import datetime as dt
import json

from pzsavesync.sync import SharedRepo


def _stub_version(filename, save_name, uploaded_by, days_ago=0):
    ts = (dt.datetime.now() - dt.timedelta(days=days_ago)).isoformat(timespec="seconds")
    return {
        "filename": filename,
        "save_name": save_name,
        "uploaded_by": uploaded_by,
        "uploaded_at": ts,
        "size_bytes": 1024 * 1024,
        "has_db": True,
        "server_files": [],
        "note": "",
    }


def test_prune_keep_last_n(tmp_path):
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    versions = [
        _stub_version(f"b{i}.zip", "world", "alice", days_ago=10 - i)
        for i in range(10)
    ]
    # Crée les fichiers stub physiquement
    for v in versions:
        (repo.versions_dir / v["filename"]).write_bytes(b"x")
    data = repo._read_manifest()
    data["versions"] = versions
    repo._write_manifest(data)

    deleted = repo.prune_versions(keep_last_n=3)
    assert len(deleted) == 7
    remaining = repo.list_versions()
    assert len(remaining) == 3
    # Les 3 plus récents conservés (uploaded_at le plus récent → 0 days_ago)
    kept_names = [v.filename for v in remaining]
    assert "b9.zip" in kept_names
    assert "b8.zip" in kept_names
    assert "b7.zip" in kept_names


def test_prune_older_than_days(tmp_path):
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    versions = [
        _stub_version("old.zip", "world", "alice", days_ago=60),
        _stub_version("recent.zip", "world", "alice", days_ago=2),
    ]
    for v in versions:
        (repo.versions_dir / v["filename"]).write_bytes(b"x")
    data = repo._read_manifest()
    data["versions"] = versions
    repo._write_manifest(data)

    deleted = repo.prune_versions(older_than_days=30)
    assert "old.zip" in deleted
    assert "recent.zip" not in deleted
    remaining = repo.list_versions()
    assert len(remaining) == 1
    assert remaining[0].filename == "recent.zip"


def test_prune_requires_a_criterion(tmp_path):
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    import pytest
    with pytest.raises(ValueError):
        repo.prune_versions()


def test_cleanup_orphan_tmp(tmp_path):
    repo = SharedRepo(tmp_path)
    repo.init_if_needed()
    (repo.versions_dir / "bundle_a.zip.tmp").write_bytes(b"residue")
    (repo.versions_dir / "bundle_b.zip").write_bytes(b"ok")
    (repo.versions_dir / "bundle_c.zip.rwm.tmp").write_bytes(b"residue2")
    deleted = repo.cleanup_orphan_tmp_files()
    assert "bundle_a.zip.tmp" in deleted
    assert "bundle_c.zip.rwm.tmp" in deleted
    assert "bundle_b.zip" not in deleted
    # Le .zip légitime doit toujours être là
    assert (repo.versions_dir / "bundle_b.zip").exists()

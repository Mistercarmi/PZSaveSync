"""Tests de l'auto-détection des dossiers cloud."""
from pzsavesync import cloud_detect


def test_detect_returns_list():
    found = cloud_detect.detect()
    assert isinstance(found, list)
    # Chaque entrée a un label et un path
    for c in found:
        assert isinstance(c.label, str)
        assert c.label
        assert c.path.exists(), f"Le path {c.path} a été dit exister mais ne l'est plus"


def test_suggest_subfolder_does_not_create():
    """suggest_subfolder ne doit pas créer le dossier."""
    from pathlib import Path
    parent = Path.home()
    suggested = cloud_detect.suggest_subfolder(parent, "PZ_test_dont_create_me")
    assert suggested.name == "PZ_test_dont_create_me"
    assert suggested.parent == parent
    assert not suggested.exists()


def test_candidates_includes_major_clouds():
    """La liste interne doit au moins mentionner Dropbox, OneDrive, Google Drive."""
    candidates = cloud_detect._candidates()
    labels = {c.label for c in candidates}
    assert any("Dropbox" in l for l in labels)
    assert any("OneDrive" in l for l in labels)
    assert any("Google Drive" in l for l in labels)

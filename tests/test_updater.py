"""Tests unitaires du module updater (parsing version, is_newer)."""
from pzsavesync import updater


def test_parse_version_with_v_prefix():
    assert updater._parse_version("v1.2.3") == (1, 2, 3)


def test_parse_version_without_prefix():
    assert updater._parse_version("1.2.3") == (1, 2, 3)


def test_parse_version_empty():
    assert updater._parse_version("") == (0,)


def test_parse_version_partial():
    assert updater._parse_version("v0.3") == (0, 3)


def test_parse_version_with_suffix():
    # "1.2.3-beta" → on s'arrête à la partie qui parse en int
    assert updater._parse_version("v1.2.3-beta") == (1, 2, 3)


def test_is_newer_true():
    assert updater.is_newer("v0.3.0", "v0.2.0") is True
    assert updater.is_newer("v1.0.0", "v0.99.99") is True
    assert updater.is_newer("v0.2.1", "v0.2.0") is True


def test_is_newer_false():
    assert updater.is_newer("v0.2.0", "v0.3.0") is False
    assert updater.is_newer("v0.2.0", "v0.2.0") is False  # égal n'est pas plus récent


def test_is_newer_mixed_prefix():
    # "v0.3.0" vs "0.2.0" — le prefix v doit être normalisé
    assert updater.is_newer("v0.3.0", "0.2.0") is True

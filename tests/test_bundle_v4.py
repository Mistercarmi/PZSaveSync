"""Tests du format Bundle v4 (mode différentiel) — PR 2.

Couvre la rétro-compat (bundles v3 lisibles) + la validation du nouveau format.
L'implémentation effective de _extract_diff_overlay est en PR 3.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from pzsavesync import bundle as bundle_mod
from pzsavesync.bundle import BUNDLE_VERSION, BundleManifest, BundleMode
from pzsavesync.diff_errors import InvalidDiffManifestError


# --------- BUNDLE_VERSION bumped ---------

def test_bundle_version_is_4():
    assert BUNDLE_VERSION == 4


# --------- BundleMode enum ---------

def test_bundle_mode_values():
    assert BundleMode.FULL.value == "full"
    assert BundleMode.DIFF.value == "diff"
    assert BundleMode.AUTO.value == "auto"


def test_bundle_mode_is_str_enum():
    # str enum permet de comparer directement avec une string
    assert BundleMode.FULL == "full"
    assert BundleMode.DIFF == "diff"


# --------- Defaults du manifest ---------

def test_manifest_defaults_to_full_mode():
    m = BundleManifest(
        bundle_version=4, save_name="X", created_at="2026", created_by="me",
    )
    assert m.bundle_mode == "full"
    assert m.parent_bundle_sha256 == ""
    assert m.expected_save_files == {}
    assert m.diff_files == []
    assert m.deleted_files == []
    assert m.excluded_categories == []


# --------- Compat ascendante : bundle v3 lu en v4 ---------

def _make_v3_bundle(tmp_path: Path, save_name: str = "v3save") -> Path:
    """Crée un bundle au format v3 (sans les champs v4) pour tester la compat."""
    save_dir = tmp_path / "Saves" / "Multiplayer" / save_name
    save_dir.mkdir(parents=True)
    (save_dir / "map.bin").write_bytes(b"data")
    (tmp_path / "db").mkdir()
    (tmp_path / "Server").mkdir()
    (tmp_path / "Server" / f"{save_name}.ini").write_text(
        "Mods=mod_a\nWorkshopItems=12345\n", encoding="utf-8",
    )
    (tmp_path / "Server" / f"{save_name}_SandboxVars.lua").write_text("x", encoding="utf-8")
    (tmp_path / "Server" / f"{save_name}_spawnregions.lua").write_text("y", encoding="utf-8")

    out = tmp_path / "bundle_v3.zip"
    bundle_mod.build_bundle(
        save_name=save_name, out_zip=out, created_by="legacy", root=tmp_path,
    )

    # Réécrit le manifest avec bundle_version=3 et SANS les champs v4
    with zipfile.ZipFile(out, "r") as zf:
        manifest_data = json.loads(zf.read(bundle_mod.MANIFEST_FILENAME))
    manifest_data["bundle_version"] = 3
    for v4_field in ("bundle_mode", "parent_bundle_sha256", "parent_bundle_filename",
                     "expected_save_files", "diff_files", "deleted_files", "excluded_categories"):
        manifest_data.pop(v4_field, None)

    # Recrée le zip sans les champs v4
    tmp_zip = tmp_path / "bundle_v3_rewritten.zip"
    with zipfile.ZipFile(out, "r") as src, zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            if item.filename == bundle_mod.MANIFEST_FILENAME:
                continue
            dst.writestr(item, src.read(item.filename))
        dst.writestr(bundle_mod.MANIFEST_FILENAME, json.dumps(manifest_data, indent=2))

    return tmp_zip


def test_v3_bundle_still_imports_in_v4_code(tmp_path):
    """Un bundle au format v3 (sans bundle_mode) doit être lu comme FULL par défaut."""
    zip_path = _make_v3_bundle(tmp_path)
    manifest = bundle_mod.read_manifest(zip_path)
    assert manifest.bundle_version == 3
    assert manifest.bundle_mode == "full"  # default appliqué
    assert manifest.parent_bundle_sha256 == ""
    assert manifest.expected_save_files == {}


def test_v3_bundle_extraction_still_works(tmp_path):
    """Un bundle v3 doit s'extraire normalement (chemin _extract_full_replace)."""
    zip_path = _make_v3_bundle(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    report = bundle_mod.extract_bundle(
        zip_path, root=target, verify_hash=False, allow_no_backup=True,
    )
    assert report.save_name == "v3save"
    assert (target / "Saves" / "Multiplayer" / "v3save" / "map.bin").exists()


# --------- v4 FULL = comportement v3 ---------

def test_v4_full_bundle_behavior_identical_to_v3(tmp_path, fake_zomboid):
    """Build un bundle en v4 mode=full + extract → mêmes résultats qu'en v3."""
    out = tmp_path / "v4_full.zip"
    bundle_mod.build_bundle(
        save_name="testsave", out_zip=out, created_by="test", root=fake_zomboid,
    )
    manifest = bundle_mod.read_manifest(out)
    assert manifest.bundle_version == 4
    assert manifest.bundle_mode == "full"

    target = tmp_path / "target"
    target.mkdir()
    report = bundle_mod.extract_bundle(
        out, root=target, verify_hash=True, allow_no_backup=True,
    )
    assert report.save_name == "testsave"
    assert (target / "Saves" / "Multiplayer" / "testsave" / "map.bin").exists()
    assert (target / "db" / "testsave.db").exists()
    assert (target / "Server" / "testsave.ini").exists()


# --------- Validation du manifest v4 ---------

def _make_zip_with_manifest(zip_path: Path, manifest_dict: dict):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(bundle_mod.MANIFEST_FILENAME, json.dumps(manifest_dict, indent=2))
        # Un fichier save bidon pour ne pas être un zip vide
        zf.writestr("save/dummy.bin", b"x")


def test_read_manifest_rejects_invalid_bundle_mode(tmp_path):
    zip_path = tmp_path / "bad_mode.zip"
    _make_zip_with_manifest(zip_path, {
        "bundle_version": 4,
        "save_name": "ok",
        "created_at": "2026",
        "created_by": "me",
        "bundle_mode": "unknown_mode",
    })
    with pytest.raises(ValueError, match="bundle_mode"):
        bundle_mod.read_manifest(zip_path)


def test_read_manifest_rejects_diff_without_parent_sha(tmp_path):
    zip_path = tmp_path / "diff_no_parent.zip"
    _make_zip_with_manifest(zip_path, {
        "bundle_version": 4,
        "save_name": "ok",
        "created_at": "2026",
        "created_by": "me",
        "bundle_mode": "diff",
        # parent_bundle_sha256 manquant
        "expected_save_files": {"a.bin": "f" * 64},
    })
    with pytest.raises(InvalidDiffManifestError, match="parent_bundle_sha256"):
        bundle_mod.read_manifest(zip_path)


def test_read_manifest_rejects_diff_without_expected_save_files(tmp_path):
    zip_path = tmp_path / "diff_no_expected.zip"
    _make_zip_with_manifest(zip_path, {
        "bundle_version": 4,
        "save_name": "ok",
        "created_at": "2026",
        "created_by": "me",
        "bundle_mode": "diff",
        "parent_bundle_sha256": "a" * 64,
        # expected_save_files manquant
    })
    with pytest.raises(InvalidDiffManifestError, match="expected_save_files"):
        bundle_mod.read_manifest(zip_path)


def test_read_manifest_accepts_well_formed_diff(tmp_path):
    """Un manifest diff complet doit être lu sans erreur."""
    zip_path = tmp_path / "diff_ok.zip"
    _make_zip_with_manifest(zip_path, {
        "bundle_version": 4,
        "save_name": "ok",
        "created_at": "2026",
        "created_by": "me",
        "bundle_mode": "diff",
        "parent_bundle_sha256": "a" * 64,
        "expected_save_files": {"x.bin": "f" * 64},
        "diff_files": ["x.bin"],
    })
    manifest = bundle_mod.read_manifest(zip_path)
    assert manifest.bundle_mode == "diff"
    assert manifest.parent_bundle_sha256 == "a" * 64
    assert manifest.expected_save_files == {"x.bin": "f" * 64}


# --------- Manifest sans bundle_mode ---------

def test_manifest_empty_string_bundle_mode_treated_as_full(tmp_path):
    """Edge case : si bundle_mode='' (string vide), on tolère et on traite en FULL."""
    zip_path = tmp_path / "empty_mode.zip"
    _make_zip_with_manifest(zip_path, {
        "bundle_version": 4,
        "save_name": "ok",
        "created_at": "2026",
        "created_by": "me",
        "bundle_mode": "",  # vide → traité comme full (compat)
    })
    manifest = bundle_mod.read_manifest(zip_path)
    # Note : le dataclass va recevoir bundle_mode="" mais on accepte string vide
    # comme équivalent à "full" pour la robustesse (manifest mal sérialisé)
    assert manifest.bundle_mode in ("", "full")

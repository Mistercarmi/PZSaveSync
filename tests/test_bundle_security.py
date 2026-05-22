"""Tests de la couche sécurité de bundle.py (limites, validation, hash)."""
import json
import zipfile

import pytest

from pzsavesync import bundle as bundle_mod


def test_validate_save_name_rejects_bad_chars():
    for bad in ["save/evil", "save\\evil", "save:evil", "save?evil", "save*evil", "save<evil"]:
        with pytest.raises(ValueError):
            bundle_mod._validate_save_name(bad)


def test_validate_save_name_rejects_empty_and_relative():
    for bad in ["", "  ", ".hidden", "-dash", ".", ".."]:
        with pytest.raises(ValueError):
            bundle_mod._validate_save_name(bad)


def test_validate_save_name_accepts_good():
    for good in ["MaSave", "world_2026", "test-save", "SAVE123"]:
        # Ne doit pas lever
        bundle_mod._validate_save_name(good)


def test_is_safe_mod_name():
    assert bundle_mod._is_safe_mod_name("BetterSorting")
    assert bundle_mod._is_safe_mod_name("ProperZeds_v2")
    # Caractères système refusés
    assert not bundle_mod._is_safe_mod_name("../evil")
    assert not bundle_mod._is_safe_mod_name("a/b")
    assert not bundle_mod._is_safe_mod_name("a\\b")
    assert not bundle_mod._is_safe_mod_name("")
    assert not bundle_mod._is_safe_mod_name("a" * 250)


def test_parse_ini_workshop_ids_must_be_numeric(tmp_path):
    """Les Workshop IDs non-numériques doivent être filtrés silencieusement."""
    ini = tmp_path / "test.ini"
    ini.write_text(
        "Mods=BetterSorting;ProperZeds\n"
        "WorkshopItems=12345;not_a_number;67890;'); DROP TABLE players;--\n",
        encoding="utf-8",
    )
    mods, ws = bundle_mod.parse_ini_mods(ini)
    assert mods == ["BetterSorting", "ProperZeds"]
    # "not_a_number", "'); DROP..." → filtrés
    assert ws == ["12345", "67890"]


def test_extract_rejects_too_many_files(tmp_path):
    """Un bundle avec > MAX_FILES_IN_BUNDLE fichiers doit être rejeté."""
    # On va pas créer 50k fichiers — on patch la constante pour le test
    save_dir = tmp_path / "Saves" / "Multiplayer" / "victim"
    save_dir.mkdir(parents=True)
    for i in range(10):
        (save_dir / f"map_{i}.bin").write_bytes(b"x")
    (tmp_path / "db").mkdir()
    (tmp_path / "Server").mkdir()

    out = tmp_path / "out.zip"
    bundle_mod.build_bundle(
        save_name="victim", out_zip=out, created_by="test", root=tmp_path,
    )

    # Patch la limite à 3 et tente d'extraire
    original = bundle_mod.MAX_FILES_IN_BUNDLE
    bundle_mod.MAX_FILES_IN_BUNDLE = 3
    try:
        target = tmp_path / "target"
        target.mkdir()
        with pytest.raises(ValueError, match="suspect"):
            bundle_mod.extract_bundle(
                out, root=target, verify_hash=False, allow_no_backup=True,
            )
    finally:
        bundle_mod.MAX_FILES_IN_BUNDLE = original


def test_extract_rejects_too_large_compressed(tmp_path):
    """Un bundle > MAX_BUNDLE_SIZE_BYTES doit être rejeté à l'extraction."""
    save_dir = tmp_path / "Saves" / "Multiplayer" / "victim"
    save_dir.mkdir(parents=True)
    (save_dir / "m.bin").write_bytes(b"x")
    (tmp_path / "db").mkdir()
    (tmp_path / "Server").mkdir()
    out = tmp_path / "out.zip"
    bundle_mod.build_bundle("victim", out, "test", root=tmp_path)

    # Patch pour simuler un bundle trop gros
    original = bundle_mod.MAX_BUNDLE_SIZE_BYTES
    bundle_mod.MAX_BUNDLE_SIZE_BYTES = 100  # 100 octets max
    try:
        target = tmp_path / "target"
        target.mkdir()
        with pytest.raises(ValueError, match="trop gros"):
            bundle_mod.extract_bundle(
                out, root=target, verify_hash=False, allow_no_backup=True,
            )
    finally:
        bundle_mod.MAX_BUNDLE_SIZE_BYTES = original


def test_sha256_added_to_manifest_v2(tmp_path):
    """Le bundle v2 doit avoir un champ sha256 non vide dans le manifest."""
    save_dir = tmp_path / "Saves" / "Multiplayer" / "world"
    save_dir.mkdir(parents=True)
    (save_dir / "map.bin").write_bytes(b"world-data")
    (tmp_path / "db").mkdir()
    (tmp_path / "Server").mkdir()
    out = tmp_path / "bundle.zip"
    m = bundle_mod.build_bundle("world", out, "alice", root=tmp_path)
    assert m.sha256, "Le manifest devrait contenir un sha256"
    assert len(m.sha256) == 64, "SHA256 = 64 hex chars"

    # Vérifier qu'on peut le relire correctement
    m2 = bundle_mod.read_manifest(out)
    assert m2.sha256 == m.sha256


def test_verify_bundle_integrity_detects_corruption(tmp_path):
    """Si on altère le contenu du zip, verify_bundle_integrity doit le détecter."""
    save_dir = tmp_path / "Saves" / "Multiplayer" / "world"
    save_dir.mkdir(parents=True)
    (save_dir / "map.bin").write_bytes(b"original")
    (tmp_path / "db").mkdir()
    (tmp_path / "Server").mkdir()
    out = tmp_path / "bundle.zip"
    bundle_mod.build_bundle("world", out, "alice", root=tmp_path)

    # Bundle intact = OK
    ok, _ = bundle_mod.verify_bundle_integrity(out)
    assert ok

    # On corrompt le zip en réécrivant un fichier
    import zipfile, json
    with zipfile.ZipFile(out, "r") as zf:
        contents = {name: zf.read(name) for name in zf.namelist()}
    contents["save/map.bin"] = b"TAMPERED"
    # On garde le manifest tel quel pour que le hash stocké ne corresponde plus
    corrupted = tmp_path / "corrupted.zip"
    with zipfile.ZipFile(corrupted, "w") as zf:
        for name, data in contents.items():
            zf.writestr(name, data)

    ok, msg = bundle_mod.verify_bundle_integrity(corrupted)
    assert not ok
    assert "sha256" in msg.lower() or "correspond" in msg.lower()

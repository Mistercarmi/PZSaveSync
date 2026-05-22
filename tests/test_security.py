"""Tests de securite et des nouveautes : ZIP slip, validation, extraction mods."""
import json
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from pzsavesync import bundle as bundle_mod


def _make_minimal_save(root: Path, save_name: str, ini_content: str = "Public=false\n"):
    save_dir = root / "Saves" / "Multiplayer" / save_name
    save_dir.mkdir(parents=True)
    (save_dir / "map.bin").write_bytes(b"map")
    (root / "db").mkdir()
    (root / "db" / f"{save_name}.db").write_bytes(b"fake-db")
    (root / "Server").mkdir()
    (root / "Server" / f"{save_name}.ini").write_text(ini_content, encoding="utf-8")
    (root / "Server" / f"{save_name}_SandboxVars.lua").write_text("v=1", encoding="utf-8")
    (root / "Server" / f"{save_name}_spawnregions.lua").write_text("v=1", encoding="utf-8")


def test_mods_extraction():
    """Verifie que parse_ini_mods extrait correctement Mods= et WorkshopItems=."""
    print("== Test : extraction mods depuis .ini ==")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        ini_content = (
            "Public=false\n"
            "Mods=mod_alpha;mod_beta;mod_gamma\n"
            "WorkshopItems=2169435993;2200148440;1234567890\n"
            "Password=secret\n"
        )
        _make_minimal_save(td, "testsave", ini_content=ini_content)

        mods, workshop = bundle_mod.parse_ini_mods(td / "Server" / "testsave.ini")
        assert mods == ["mod_alpha", "mod_beta", "mod_gamma"], f"mods={mods}"
        assert workshop == ["2169435993", "2200148440", "1234567890"], f"workshop={workshop}"
        print(f"   [OK] mods extraits : {mods}")
        print(f"   [OK] workshop IDs  : {workshop}")

        # Build bundle et verifie que le manifest contient les mods
        out = td / "bundle.zip"
        m = bundle_mod.build_bundle(
            save_name="testsave", out_zip=out,
            created_by="TestUser", root=td,
        )
        assert m.mods == mods, f"manifest.mods={m.mods}"
        assert m.workshop_items == workshop, f"manifest.workshop_items={m.workshop_items}"
        print("   [OK] manifest contient les mods et workshop IDs")

        # Verifie que ExtractReport contient aussi les mods
        with tempfile.TemporaryDirectory() as td2:
            td2 = Path(td2)
            report = bundle_mod.extract_bundle(
                out, root=td2, backup_dir=None, allow_no_backup=True,
            )
            assert report.mods == mods
            assert report.workshop_items == workshop
            print("   [OK] ExtractReport contient les mods (visible au pote a l'import)")


def test_zip_slip_blocked():
    """Verifie qu'un zip malveillant avec ../ est rejete."""
    print("\n== Test : ZIP slip rejete ==")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        malicious = td / "evil.zip"

        manifest = {
            "bundle_version": 1,
            "save_name": "victim",
            "created_at": "2026-01-01T00:00:00",
            "created_by": "attacker",
        }
        with zipfile.ZipFile(malicious, "w") as zf:
            zf.writestr("bundle_manifest.json", json.dumps(manifest))
            # Tentative de path traversal
            zf.writestr("save/../../../evil.txt", b"PWNED")
            zf.writestr("save/legitimate.bin", b"ok")

        target_root = td / "target"
        target_root.mkdir()
        try:
            bundle_mod.extract_bundle(
                malicious, root=target_root, backup_dir=None, allow_no_backup=True,
            )
            raise AssertionError("ZIP slip aurait du etre rejete !")
        except ValueError as e:
            assert "traversal" in str(e).lower() or "suspect" in str(e).lower(), f"msg: {e}"
            print(f"   [OK] ValueError leve : {e}")

        # Verifie qu'aucun fichier suspect n'a fuite hors du dossier cible
        leaked = (td / "evil.txt").exists()
        assert not leaked, "Le fichier evil.txt a fuite hors du dossier cible !"
        print("   [OK] Aucune fuite de fichier hors du dossier cible")


def test_save_name_validation():
    """Verifie qu'un save_name avec caracteres interdits est rejete."""
    print("\n== Test : validation save_name ==")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        bad_names = ["", "  ", "save/evil", "save\\evil", "save:evil", ".hidden", "-dash"]
        for bad in bad_names:
            try:
                bundle_mod._validate_save_name(bad)
                raise AssertionError(f"save_name '{bad}' aurait du etre rejete !")
            except ValueError:
                pass
        print(f"   [OK] {len(bad_names)} noms invalides correctement rejetes")

        # Noms valides
        good_names = ["MaSave", "world_2026", "test-save"]
        for good in good_names:
            bundle_mod._validate_save_name(good)
        print(f"   [OK] {len(good_names)} noms valides acceptes")


def test_invalid_manifest():
    """Verifie qu'un manifest incomplet est rejete clairement."""
    print("\n== Test : validation manifest ==")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        bad_zip = td / "incomplete.zip"
        # Manifest sans 'save_name'
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("bundle_manifest.json", json.dumps({"bundle_version": 1}))
        try:
            bundle_mod.read_manifest(bad_zip)
            raise AssertionError("Manifest incomplet aurait du etre rejete !")
        except ValueError as e:
            assert "manifest" in str(e).lower(), f"msg: {e}"
            print(f"   [OK] ValueError leve : {e}")

        # JSON invalide
        bad_zip2 = td / "bad_json.zip"
        with zipfile.ZipFile(bad_zip2, "w") as zf:
            zf.writestr("bundle_manifest.json", "not json {")
        try:
            bundle_mod.read_manifest(bad_zip2)
            raise AssertionError("JSON invalide aurait du etre rejete !")
        except ValueError:
            print("   [OK] JSON corrompu rejete")


if __name__ == "__main__":
    test_mods_extraction()
    test_zip_slip_blocked()
    test_save_name_validation()
    test_invalid_manifest()
    print("\n=== ALL OK : securite + mods valides ===")

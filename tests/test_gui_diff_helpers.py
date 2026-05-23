"""Tests des helpers gui.py pour le mode diff (PR 5).

Tests "fumée" — vérifient que les fonctions module-level non-UI font leur job,
sans instancier de widgets Tkinter (testable en CI headless).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pzsavesync import bundle as bundle_mod
from pzsavesync import snapshot as snap_mod


@pytest.fixture(autouse=True)
def isolated_app_dir(tmp_path_factory, monkeypatch):
    fake = tmp_path_factory.mktemp("PZSaveSync_iso")
    monkeypatch.setattr(snap_mod, "APP_DIR", fake)
    return fake


def _make_minimal_zomboid(root: Path, save_name: str = "TestSave"):
    save_dir = root / "Saves" / "Multiplayer" / save_name
    save_dir.mkdir(parents=True)
    (save_dir / "map_0_0.bin").write_bytes(b"chunk")
    (root / "db").mkdir()
    (root / "db" / f"{save_name}.db").write_bytes(b"db")
    (root / "Server").mkdir()
    (root / "Server" / f"{save_name}.ini").write_text(
        "Mods=\nWorkshopItems=\n", encoding="utf-8",
    )
    (root / "Server" / f"{save_name}_SandboxVars.lua").write_text("x", encoding="utf-8")
    (root / "Server" / f"{save_name}_spawnregions.lua").write_text("y", encoding="utf-8")


def test_try_create_snapshot_post_import_creates_snapshot(tmp_path, monkeypatch):
    """Le helper crée un snapshot SHA256 après un extract réussi."""
    # Si on ne peut pas importer gui (env CI sans display), on skip
    try:
        from pzsavesync import gui
    except Exception as e:
        pytest.skip(f"gui n'est pas importable dans cet env : {e}")

    # 1. Crée un bundle et l'extrait
    src_zomboid = tmp_path / "src"
    _make_minimal_zomboid(src_zomboid)
    out_zip = tmp_path / "bundle.zip"
    bundle_mod.build_bundle(
        save_name="TestSave", out_zip=out_zip, created_by="alice", root=src_zomboid,
    )

    dst_zomboid = tmp_path / "dst"
    dst_zomboid.mkdir()
    monkeypatch.setenv("PZ_ZOMBOID_ROOT", str(dst_zomboid))
    report = bundle_mod.extract_bundle(
        out_zip, root=dst_zomboid, verify_hash=True, allow_no_backup=True,
    )

    # 2. Appelle le helper
    gui._try_create_snapshot_post_import(out_zip, report)

    # 3. Vérifie qu'un snapshot existe
    snap = snap_mod.find_latest_snapshot_for_save("TestSave")
    assert snap is not None
    assert snap.save_name == "TestSave"
    assert snap.parent_bundle_sha256
    assert snap.parent_bundle_filename == "bundle.zip"


def test_try_create_snapshot_post_import_does_not_crash_on_bad_input(tmp_path, capsys):
    """Si quelque chose foire (zip manquant, save_dir invalide), le helper ne raise pas."""
    try:
        from pzsavesync import gui
    except Exception as e:
        pytest.skip(f"gui n'est pas importable : {e}")

    # Cas 1 : zip inexistant
    fake_report = type("FakeReport", (), {
        "save_name": "X",
        "save_dir": tmp_path / "no_such_dir",
    })()
    # Ne doit pas raise
    gui._try_create_snapshot_post_import(tmp_path / "ghost.zip", fake_report)


def test_push_options_dialog_attributes_exist():
    """Smoke test : PushOptionsDialog expose les attributs nécessaires."""
    try:
        from pzsavesync import gui
    except Exception as e:
        pytest.skip(f"gui n'est pas importable : {e}")

    # Sans instancier (Tkinter root nécessaire), on vérifie via le code source
    import inspect
    init_source = inspect.getsource(gui.PushOptionsDialog.__init__)
    assert "use_diff" in init_source
    assert "default_diff" in init_source

    confirm_source = inspect.getsource(gui.PushOptionsDialog._confirm)
    assert "use_diff" in confirm_source

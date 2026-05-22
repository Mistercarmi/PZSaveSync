"""Tests de la découverte des fichiers compagnons (cas Server name != World name)."""
from __future__ import annotations

import os
import time
import zipfile

import pytest

from pzsavesync import bundle as bundle_mod


def _make_layout(
    tmp_path,
    save_name: str,
    server_prefix: str | None,
    *,
    with_sandbox: bool = True,
    with_spawn: bool = True,
    with_db: bool = True,
    align_mtimes: bool = True,
):
    """Crée une arborescence Zomboid factice.

    - `server_prefix=None` → aucun fichier serveur (cas client cache pur).
    - `with_sandbox` / `with_spawn` / `with_db` → permettent de créer un set
      Server partiel (ini sans _SandboxVars par exemple).
    - `align_mtimes` → si True, force save_dir + fichiers Server/db à la même
      mtime "maintenant" (corrélation parfaite). Mettre à False pour tester le
      cas où les fichiers serveur datent d'une autre époque.
    """
    save_dir = tmp_path / "Saves" / "Multiplayer" / save_name
    save_dir.mkdir(parents=True)
    (save_dir / "map_0_0.bin").write_bytes(b"chunk-data")

    (tmp_path / "Server").mkdir(exist_ok=True)
    (tmp_path / "db").mkdir(exist_ok=True)

    if server_prefix is not None:
        ini = tmp_path / "Server" / f"{server_prefix}.ini"
        ini.write_text("PVP=true\nMods=BetterSorting\nWorkshopItems=12345\n", encoding="utf-8")
        if with_sandbox:
            (tmp_path / "Server" / f"{server_prefix}_SandboxVars.lua").write_text("-- sandbox", encoding="utf-8")
        if with_spawn:
            (tmp_path / "Server" / f"{server_prefix}_spawnregions.lua").write_text("-- spawn", encoding="utf-8")
        if with_db:
            (tmp_path / "db" / f"{server_prefix}.db").write_bytes(b"SQLite-fake")

        if align_mtimes:
            now = time.time()
            os.utime(save_dir, (now, now))
            for p in (tmp_path / "Server").iterdir():
                if p.stem.startswith(server_prefix):
                    os.utime(p, (now, now))
            if with_db:
                os.utime(tmp_path / "db" / f"{server_prefix}.db", (now, now))

    return save_dir


def test_discover_exact_match(tmp_path):
    """Cas standard : Server name == World name == save_name."""
    _make_layout(tmp_path, "MaSave", server_prefix="MaSave")
    cf = bundle_mod.discover_companion_files("MaSave", root=tmp_path)
    assert cf.exact_match is True
    assert cf.server_prefix == "MaSave"
    assert cf.db is not None and cf.db.name == "MaSave.db"
    assert cf.ini is not None and cf.ini.name == "MaSave.ini"
    assert cf.sandbox is not None and cf.sandbox.name == "MaSave_SandboxVars.lua"
    assert cf.spawn is not None and cf.spawn.name == "MaSave_spawnregions.lua"


def test_discover_inferred_when_server_name_differs(tmp_path):
    """Server name = "servertest" (défaut PZ), World name = "MaSave" → inférence."""
    _make_layout(tmp_path, "MaSave", server_prefix="servertest")
    cf = bundle_mod.discover_companion_files("MaSave", root=tmp_path)
    assert cf.exact_match is False
    assert cf.server_prefix == "servertest"
    assert cf.db is not None and cf.db.name == "servertest.db"
    assert cf.ini is not None and cf.ini.name == "servertest.ini"
    assert cf.sandbox is not None and cf.sandbox.name == "servertest_SandboxVars.lua"
    assert cf.spawn is not None and cf.spawn.name == "servertest_spawnregions.lua"


def test_discover_no_companions_when_only_client_cache(tmp_path):
    """Save Multiplayer sans fichier Server/DB (client cache pur) → rien inféré."""
    _make_layout(tmp_path, "MaSave", server_prefix=None)
    cf = bundle_mod.discover_companion_files("MaSave", root=tmp_path)
    assert cf.db is None
    assert cf.ini is None
    assert cf.sandbox is None
    assert cf.spawn is None
    # exact_match reste True quand on n'a rien trouvé (rien à inférer)
    assert cf.exact_match is True


def test_discover_prefers_complete_set_over_orphan_ini(tmp_path):
    """Quand plusieurs .ini sont candidats, on préfère celui qui a son
    _SandboxVars + _spawnregions à un .ini orphelin, même si le delta mtime
    est légèrement moins bon."""
    # Set complet
    _make_layout(tmp_path, "MaSave", server_prefix="servertest")
    # .ini orphelin créé un poil plus tard (mtime plus proche du save_dir si
    # on ne fait que la corrélation pure → on prendrait celui-ci à tort)
    orphan = tmp_path / "Server" / "abandoned.ini"
    orphan.write_text("PVP=false\n", encoding="utf-8")
    # Mtime de l'orphan = exactement celle du save_dir (corrélation parfaite)
    save_dir = tmp_path / "Saves" / "Multiplayer" / "MaSave"
    os.utime(orphan, (save_dir.stat().st_mtime, save_dir.stat().st_mtime))

    cf = bundle_mod.discover_companion_files("MaSave", root=tmp_path)
    # Doit avoir choisi servertest (set complet) malgré la mtime équivalente
    assert cf.server_prefix == "servertest"
    assert cf.sandbox is not None
    assert cf.spawn is not None


def test_discover_picks_most_correlated_when_multiple_complete_sets(tmp_path):
    """Plusieurs sets Server complets → on prend celui avec la mtime la plus
    proche de save_dir."""
    _make_layout(tmp_path, "MaSave", server_prefix="servertest")
    # Set complet "old" datant d'il y a longtemps
    long_ago = time.time() - 365 * 24 * 3600
    for suffix in (".ini", "_SandboxVars.lua", "_spawnregions.lua"):
        f = tmp_path / "Server" / f"old{suffix}"
        f.write_text("-- old", encoding="utf-8")
        os.utime(f, (long_ago, long_ago))
    old_db = tmp_path / "db" / "old.db"
    old_db.write_bytes(b"old")
    os.utime(old_db, (long_ago, long_ago))

    cf = bundle_mod.discover_companion_files("MaSave", root=tmp_path)
    assert cf.server_prefix == "servertest"


def test_discover_rejects_inference_when_mtime_delta_too_large(tmp_path):
    """Si même le meilleur candidat date d'il y a > 90 jours, on n'infère pas :
    mieux vaut un bundle sans config qu'un mauvais .ini."""
    # Save récente
    _make_layout(tmp_path, "MaSave", server_prefix="staleserver")
    # On vieillit artificiellement TOUS les fichiers serveur de >90 jours
    very_old = time.time() - 100 * 24 * 3600
    for p in (tmp_path / "Server").iterdir():
        os.utime(p, (very_old, very_old))
    for p in (tmp_path / "db").iterdir():
        os.utime(p, (very_old, very_old))

    cf = bundle_mod.discover_companion_files("MaSave", root=tmp_path)
    assert cf.ini is None
    assert cf.db is None
    assert cf.exact_match is True  # rien d'inféré → on reste sur le state initial


def test_discover_cross_verifies_db_against_server_prefix(tmp_path):
    """Si on a inféré un server_prefix=X, on doit prendre db/X.db même si
    mtime correlation pointerait vers une autre .db plus récente."""
    _make_layout(tmp_path, "MaSave", server_prefix="servertest")
    # On crée une autre .db, plus récente que servertest.db, sous un nom orphelin
    intruder = tmp_path / "db" / "intruder.db"
    intruder.write_bytes(b"intruder")
    save_mtime = (tmp_path / "Saves" / "Multiplayer" / "MaSave").stat().st_mtime
    os.utime(intruder, (save_mtime + 1, save_mtime + 1))  # 1s plus récent que save

    cf = bundle_mod.discover_companion_files("MaSave", root=tmp_path)
    # Doit avoir pris servertest.db (cross-vérification), pas intruder.db
    assert cf.db is not None and cf.db.name == "servertest.db"


def test_build_bundle_renames_inferred_files(tmp_path):
    """Quand on bundle avec server_prefix différent, les fichiers serveur
    apparaissent dans le zip sous {save_name}.ext."""
    _make_layout(tmp_path, "MaSave", server_prefix="servertest")
    out = tmp_path / "bundle.zip"
    m = bundle_mod.build_bundle(
        save_name="MaSave", out_zip=out, created_by="alice", root=tmp_path,
    )
    assert m.has_db is True
    assert m.inferred_server_prefix == "servertest"
    assert set(m.server_files) == {
        "MaSave.ini",
        "MaSave_SandboxVars.lua",
        "MaSave_spawnregions.lua",
    }
    with zipfile.ZipFile(out, "r") as zf:
        names = set(zf.namelist())
    assert "db/MaSave.db" in names
    assert "server/MaSave.ini" in names
    assert "server/MaSave_SandboxVars.lua" in names
    assert "server/MaSave_spawnregions.lua" in names
    # L'ancien nom n'apparaît PAS
    assert "server/servertest.ini" not in names
    assert "db/servertest.db" not in names


def test_build_bundle_exact_match_no_inference_recorded(tmp_path):
    """Match exact : inferred_server_prefix reste vide dans le manifest."""
    _make_layout(tmp_path, "MaSave", server_prefix="MaSave")
    out = tmp_path / "bundle.zip"
    m = bundle_mod.build_bundle("MaSave", out, "alice", root=tmp_path)
    assert m.inferred_server_prefix == ""


def test_extract_bundle_with_renamed_files_works_end_to_end(tmp_path):
    """Build avec servertest.* → extract dans une autre root → fichiers sous
    le bon nom côté destinataire."""
    src_root = tmp_path / "src_root"
    src_root.mkdir()
    _make_layout(src_root, "MaSave", server_prefix="servertest")
    out = tmp_path / "bundle.zip"
    bundle_mod.build_bundle("MaSave", out, "alice", root=src_root)

    dest_root = tmp_path / "dest_root"
    dest_root.mkdir()
    report = bundle_mod.extract_bundle(
        out, root=dest_root, verify_hash=True, allow_no_backup=True,
    )
    assert report.save_name == "MaSave"
    assert (dest_root / "Saves" / "Multiplayer" / "MaSave" / "map_0_0.bin").exists()
    assert (dest_root / "db" / "MaSave.db").exists()
    assert (dest_root / "Server" / "MaSave.ini").exists()
    assert (dest_root / "Server" / "MaSave_SandboxVars.lua").exists()
    assert (dest_root / "Server" / "MaSave_spawnregions.lua").exists()


def test_find_companions_exposes_inferred_files(tmp_path):
    """find_companions (wrapper rétro-compat utilisé par la GUI) voit les
    fichiers inférés pour que la liste des saves marque la save comme
    transférable même quand server_prefix diffère."""
    _make_layout(tmp_path, "MaSave", server_prefix="servertest")
    found = bundle_mod.find_companions("MaSave", root=tmp_path)
    assert "save_dir" in found
    assert "db" in found
    assert "server_ini" in found
    assert "server_SandboxVars.lua" in found
    assert "server_spawnregions.lua" in found

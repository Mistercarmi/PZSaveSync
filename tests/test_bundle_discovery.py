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


def test_build_bundle_preserves_server_prefix_in_filenames(tmp_path):
    """v0.4.0 fix bug map M : les fichiers server gardent leur nom d'origine
    dans le zip (plus de renommage sous save_name).

    Raison : PZ indexe le dossier `<steamid>_<Server name>_player/` (qui
    contient la mini-map M révélée) par le Server name lu dans le .ini.
    Si on renomme `servertest.ini` → `MaSave.ini`, le destinataire lance PZ
    avec Server name = "MaSave" → son fog of war (sous "servertest") devient
    orphelin → map perdue après un round-trip push/pull.

    La DB reste renommée sous save_name (cache local destinataire, sans
    impact sur le fog of war côté PZ).
    """
    _make_layout(tmp_path, "MaSave", server_prefix="servertest")
    out = tmp_path / "bundle.zip"
    m = bundle_mod.build_bundle(
        save_name="MaSave", out_zip=out, created_by="alice", root=tmp_path,
    )
    assert m.has_db is True
    assert m.inferred_server_prefix == "servertest"
    # server_files = noms ORIGINAUX (pas renommés)
    assert set(m.server_files) == {
        "servertest.ini",
        "servertest_SandboxVars.lua",
        "servertest_spawnregions.lua",
    }
    with zipfile.ZipFile(out, "r") as zf:
        names = set(zf.namelist())
    # DB toujours renommée sous save_name (logique cache client)
    assert "db/MaSave.db" in names
    # Server files sous nom d'origine
    assert "server/servertest.ini" in names
    assert "server/servertest_SandboxVars.lua" in names
    assert "server/servertest_spawnregions.lua" in names
    # Le nom save_name n'apparaît PAS dans server/
    assert "server/MaSave.ini" not in names


def test_build_bundle_exact_match_no_inference_recorded(tmp_path):
    """Match exact : inferred_server_prefix reste vide dans le manifest."""
    _make_layout(tmp_path, "MaSave", server_prefix="MaSave")
    out = tmp_path / "bundle.zip"
    m = bundle_mod.build_bundle("MaSave", out, "alice", root=tmp_path)
    assert m.inferred_server_prefix == ""


def test_build_bundle_preserves_server_name_with_spaces(tmp_path):
    """Cas réel du bug map M perdue : Server name avec ESPACES "Gitano Z"
    + World name avec underscores "Gitano_Z".

    Avant fix (v0.3.x) : le bundle renommait "Gitano Z.ini" → "Gitano_Z.ini"
    à l'embarquement, écrasant le Server name au destinataire. Au reload PZ,
    le dossier `<steamid>_Gitano Z_player/` (qui contient le fog of war) devenait
    orphelin car PZ cherchait maintenant `<steamid>_Gitano_Z_player/`.

    Après fix (v0.4.0) : le Server name "Gitano Z" est préservé, le destinataire
    le restaure tel quel, son fog of war reste accessible.
    """
    _make_layout(tmp_path, "Gitano_Z", server_prefix="Gitano Z")
    out = tmp_path / "bundle.zip"
    m = bundle_mod.build_bundle("Gitano_Z", out, "patito", root=tmp_path)

    # Le manifest pointe vers le prefix réel
    assert m.inferred_server_prefix == "Gitano Z"
    # Les server_files conservent les espaces
    assert "Gitano Z.ini" in m.server_files
    assert "Gitano Z_SandboxVars.lua" in m.server_files

    with zipfile.ZipFile(out, "r") as zf:
        names = set(zf.namelist())
    assert "server/Gitano Z.ini" in names
    assert "server/Gitano_Z.ini" not in names  # PAS de underscore


def test_extract_bundle_with_spaces_roundtrip(tmp_path):
    """Roundtrip complet : Patito (espaces) push → Isaac extract → Isaac play
    → Isaac push → Patito extract → le Server name "Gitano Z" est préservé
    des deux côtés, donc les fog of war restent valides.
    """
    # Patito : Server name = "Gitano Z" (espaces), World = "Gitano_Z"
    patito_root = tmp_path / "patito"
    patito_root.mkdir()
    _make_layout(patito_root, "Gitano_Z", server_prefix="Gitano Z")
    seed_zip = tmp_path / "seed.zip"
    bundle_mod.build_bundle("Gitano_Z", seed_zip, "patito", root=patito_root)

    # Isaac : extract → reçoit Server/Gitano Z.ini (espaces conservés)
    isaac_root = tmp_path / "isaac"
    isaac_root.mkdir()
    bundle_mod.extract_bundle(
        seed_zip, root=isaac_root, verify_hash=True, allow_no_backup=True,
    )
    assert (isaac_root / "Server" / "Gitano Z.ini").exists()
    assert not (isaac_root / "Server" / "Gitano_Z.ini").exists()

    # Isaac joue, push retour → bundle d'Isaac
    (isaac_root / "Saves" / "Multiplayer" / "Gitano_Z" / "new_chunk.bin").write_bytes(b"explored")
    isaac_zip = tmp_path / "isaac.zip"
    bundle_mod.build_bundle("Gitano_Z", isaac_zip, "isaac", root=isaac_root)

    # Patito pull bundle d'Isaac → Server/Gitano Z.ini intact
    bundle_mod.extract_bundle(
        isaac_zip, root=patito_root, verify_hash=True, allow_no_backup=True,
    )
    assert (patito_root / "Server" / "Gitano Z.ini").exists()
    assert not (patito_root / "Server" / "Gitano_Z.ini").exists()


def test_extract_bundle_preserves_server_prefix_end_to_end(tmp_path):
    """v0.4.0 : Build avec servertest.* → extract dans une autre root → les
    fichiers server sont restaurés sous leur nom d'origine (servertest.*),
    pour préserver le fog of war côté destinataire.
    """
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
    # save_dir restaurée sous save_name
    assert (dest_root / "Saves" / "Multiplayer" / "MaSave" / "map_0_0.bin").exists()
    # DB sous save_name (cache local)
    assert (dest_root / "db" / "MaSave.db").exists()
    # Server files sous nom d'origine (préservation Server name)
    assert (dest_root / "Server" / "servertest.ini").exists()
    assert (dest_root / "Server" / "servertest_SandboxVars.lua").exists()
    assert (dest_root / "Server" / "servertest_spawnregions.lua").exists()
    # NE PAS avoir renommé sous save_name
    assert not (dest_root / "Server" / "MaSave.ini").exists()


def test_discover_underscore_to_space_variant(tmp_path):
    """Cas réel rencontré sur le dump d'un hôte avec 3 serveurs : un World name
    "Pitrou_newbies" provient d'un Server name "Pitrou newbies" (espaces). Le
    code doit choisir ce set même si un autre set (Gitano Z) a une mtime plus
    proche de la save_dir (situation typique après extraction zip qui touche
    toutes les save_dir à la même heure).
    """
    # Set "Pitrou newbies" : le BON match pour Pitrou_newbies, mais mtime ancien
    long_ago = time.time() - 3 * 24 * 3600  # 3 jours avant
    for suffix in (".ini", "_SandboxVars.lua", "_spawnregions.lua"):
        f = tmp_path / "Server" / f"Pitrou newbies{suffix}"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("PVP=true\n", encoding="utf-8")
        os.utime(f, (long_ago, long_ago))
    db_p = tmp_path / "db" / "Pitrou newbies.db"
    db_p.parent.mkdir(parents=True, exist_ok=True)
    db_p.write_bytes(b"SQLite-pitrou")
    os.utime(db_p, (long_ago, long_ago))

    # Save_dir Pitrou_newbies : mtime "maintenant"
    save_dir = tmp_path / "Saves" / "Multiplayer" / "Pitrou_newbies"
    save_dir.mkdir(parents=True)
    (save_dir / "map_0_0.bin").write_bytes(b"chunk")

    # Set distracteur "Gitano Z" : mtime "maintenant" (piège pour inférence mtime)
    now = time.time()
    for suffix in (".ini", "_SandboxVars.lua", "_spawnregions.lua"):
        f = tmp_path / "Server" / f"Gitano Z{suffix}"
        f.write_text("PVP=true\n", encoding="utf-8")
        os.utime(f, (now, now))
    gitano_db = tmp_path / "db" / "Gitano Z.db"
    gitano_db.write_bytes(b"SQLite-gitano")
    os.utime(gitano_db, (now, now))
    os.utime(save_dir, (now, now))

    cf = bundle_mod.discover_companion_files("Pitrou_newbies", root=tmp_path)
    assert cf.exact_match is False
    assert cf.server_prefix == "Pitrou newbies", (
        "Le variant '_' -> ' ' doit être tenté AVANT l'inférence mtime, qui "
        f"sinon choisirait 'Gitano Z' (plus récent). Obtenu: {cf.server_prefix!r}"
    )
    assert cf.ini is not None and cf.ini.name == "Pitrou newbies.ini"
    assert cf.db is not None and cf.db.name == "Pitrou newbies.db"
    assert cf.sandbox is not None and cf.sandbox.name == "Pitrou newbies_SandboxVars.lua"
    assert cf.spawn is not None and cf.spawn.name == "Pitrou newbies_spawnregions.lua"


def test_discover_underscore_variant_only_when_no_exact_match(tmp_path):
    """Si un .ini avec underscore EXISTE (ex: "My_Save.ini"), on doit le
    prendre — pas chercher "My Save.ini" qui pourrait être un autre serveur."""
    save_dir = tmp_path / "Saves" / "Multiplayer" / "My_Save"
    save_dir.mkdir(parents=True)
    (save_dir / "map_0_0.bin").write_bytes(b"chunk")

    (tmp_path / "Server").mkdir()
    (tmp_path / "db").mkdir()
    # Match exact disponible
    (tmp_path / "Server" / "My_Save.ini").write_text("PVP=true\n")
    (tmp_path / "db" / "My_Save.db").write_bytes(b"exact")
    # Variant qui existe AUSSI (piège : un autre serveur du même hôte)
    (tmp_path / "Server" / "My Save.ini").write_text("PVP=false\n")
    (tmp_path / "db" / "My Save.db").write_bytes(b"variant")

    cf = bundle_mod.discover_companion_files("My_Save", root=tmp_path)
    assert cf.exact_match is True
    assert cf.server_prefix == "My_Save"
    assert cf.ini.name == "My_Save.ini"
    assert cf.db.name == "My_Save.db"


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

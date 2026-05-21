"""Pytest config + helpers communs.

Ajoute src/ au sys.path pour que `from pzsavesync import ...` fonctionne
sans installation.
"""
import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest


def make_fake_zomboid(root: Path, save_name: str = "testsave",
                     extra_ini: str = "") -> None:
    """Construit un faux dossier Zomboid auto-suffisant (utilisé par plusieurs tests)."""
    save_dir = root / "Saves" / "Multiplayer" / save_name
    save_dir.mkdir(parents=True)
    (save_dir / "map.bin").write_bytes(b"fake-map")
    (save_dir / "map_825_1155.bin").write_bytes(b"chunk1")
    (save_dir / "chunkdata_27_38.bin").write_bytes(b"cd1")
    (save_dir / "gos_campfire.bin").write_bytes(b"camp")

    db_dir = root / "db"
    db_dir.mkdir(parents=True)
    db = db_dir / f"{save_name}.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE whitelist(username TEXT)")
    con.executemany("INSERT INTO whitelist(username) VALUES (?)", [("Alice",), ("Bob",)])
    con.commit()
    con.close()

    srv = root / "Server"
    srv.mkdir(parents=True)
    (srv / f"{save_name}.ini").write_text(
        "Public=false\nMods=mod_a;mod_b\nWorkshopItems=12345;67890\n" + extra_ini,
        encoding="utf-8",
    )
    (srv / f"{save_name}_SandboxVars.lua").write_text("SandboxVars={}", encoding="utf-8")
    (srv / f"{save_name}_spawnregions.lua").write_text("function SpawnRegions() end", encoding="utf-8")


@pytest.fixture
def fake_zomboid(tmp_path):
    """Renvoie le chemin d'un faux Zomboid prêt à l'emploi."""
    root = tmp_path / "Zomboid"
    root.mkdir()
    make_fake_zomboid(root)
    return root

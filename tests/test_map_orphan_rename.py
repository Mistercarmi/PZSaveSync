"""Tests du fix bug map M (v0.4.0) — détection + renommage des dossiers
`<steamid>_<OLD>_player/` orphelins après changement de Server name.

Contexte : PZ stocke la mini-map M (touche M) de chaque joueur dans
`Saves/Multiplayer/<steamid>_<Server name>_player/`. Si le Server name change
(typiquement espaces ↔ underscores), PZ crée un nouveau dossier vide et le
joueur perd sa carte explorée. Le fix v0.4.0 :
1. Préserve le Server name d'origine dans le bundle (pas de renommage)
2. À l'import, détecte les `<steamid>_<OLD>_player/` qui correspondent à l'ancien
   Server name et propose le renommage.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pzsavesync import bundle as bundle_mod
from pzsavesync.bundle import (
    apply_map_orphan_rename,
    detect_orphan_player_map_dirs,
)


def _make_player_dir(root: Path, steamid: str, server_name: str) -> Path:
    """Crée un dossier `<steamid>_<server_name>_player/` factice avec contenu."""
    d = root / "Saves" / "Multiplayer" / f"{steamid}_{server_name}_player"
    d.mkdir(parents=True, exist_ok=True)
    (d / "map.bin").write_bytes(b"fog-of-war-data")
    return d


# --------- detect_orphan_player_map_dirs ---------

def test_detect_finds_underscore_variant_when_new_uses_spaces(tmp_path):
    """L'user avait joué avec underscore (v0.3.x), maintenant le nouveau Server
    name a des espaces (v0.4.0) — le dossier underscore est orphelin."""
    _make_player_dir(tmp_path, "76561198000001", "Gitano_Z")

    candidates = detect_orphan_player_map_dirs("Gitano Z", root=tmp_path)
    assert len(candidates) == 1
    src, dst = candidates[0]
    assert src.name == "76561198000001_Gitano_Z_player"
    assert dst.name == "76561198000001_Gitano Z_player"


def test_detect_finds_space_variant_when_new_uses_underscores(tmp_path):
    """Cas inverse : ancien dossier avec espaces, nouveau avec underscores."""
    _make_player_dir(tmp_path, "76561198000001", "Gitano Z")
    candidates = detect_orphan_player_map_dirs("Gitano_Z", root=tmp_path)
    assert len(candidates) == 1
    assert candidates[0][0].name == "76561198000001_Gitano Z_player"
    assert candidates[0][1].name == "76561198000001_Gitano_Z_player"


def test_detect_returns_empty_when_already_correct_name(tmp_path):
    """Pas de candidate si le dossier est déjà sous le bon Server name."""
    _make_player_dir(tmp_path, "76561198000001", "Gitano Z")
    candidates = detect_orphan_player_map_dirs("Gitano Z", root=tmp_path)
    assert candidates == []


def test_detect_skips_unrelated_player_dirs(tmp_path):
    """Les dossiers de joueurs pour d'AUTRES saves ne sont pas affectés."""
    _make_player_dir(tmp_path, "76561198000001", "Other_World")
    _make_player_dir(tmp_path, "76561198000001", "Yet_Another")
    candidates = detect_orphan_player_map_dirs("Gitano Z", root=tmp_path)
    assert candidates == []


def test_detect_does_not_overwrite_existing_target(tmp_path):
    """Si la cible existe déjà (autre map du même joueur), on ne propose pas
    le renommage pour éviter d'écraser."""
    _make_player_dir(tmp_path, "76561198000001", "Gitano_Z")
    _make_player_dir(tmp_path, "76561198000001", "Gitano Z")  # cible déjà là
    candidates = detect_orphan_player_map_dirs("Gitano Z", root=tmp_path)
    assert candidates == []


def test_detect_handles_multiple_steamids(tmp_path):
    """Plusieurs joueurs sur la même save → autant de candidates."""
    _make_player_dir(tmp_path, "76561198000001", "Gitano_Z")
    _make_player_dir(tmp_path, "76561198000002", "Gitano_Z")
    _make_player_dir(tmp_path, "76561198000003", "Gitano_Z")
    candidates = detect_orphan_player_map_dirs("Gitano Z", root=tmp_path)
    assert len(candidates) == 3
    steamids_found = {c[0].name.split("_")[0] for c in candidates}
    assert steamids_found == {"76561198000001", "76561198000002", "76561198000003"}


def test_detect_handles_missing_multiplayer_dir(tmp_path):
    """Si le dossier Saves/Multiplayer n'existe pas, retourne liste vide."""
    candidates = detect_orphan_player_map_dirs("AnyName", root=tmp_path)
    assert candidates == []


def test_detect_ignores_non_player_dirs(tmp_path):
    """Les dossiers de save (`<save_name>/`) sans suffix `_player` sont ignorés."""
    (tmp_path / "Saves" / "Multiplayer" / "Gitano_Z").mkdir(parents=True)
    candidates = detect_orphan_player_map_dirs("Gitano Z", root=tmp_path)
    assert candidates == []


# --------- apply_map_orphan_rename ---------

def test_apply_rename_moves_dir_and_preserves_content(tmp_path):
    src = _make_player_dir(tmp_path, "76561198000001", "Gitano_Z")
    target = tmp_path / "Saves" / "Multiplayer" / "76561198000001_Gitano Z_player"

    ok = apply_map_orphan_rename(src, target)
    assert ok is True
    assert not src.exists()
    assert target.exists()
    # Le contenu est préservé
    assert (target / "map.bin").read_bytes() == b"fog-of-war-data"


def test_apply_rename_refuses_if_target_exists(tmp_path):
    src = _make_player_dir(tmp_path, "76561198000001", "Gitano_Z")
    target = _make_player_dir(tmp_path, "76561198000001", "Gitano Z")

    ok = apply_map_orphan_rename(src, target)
    assert ok is False
    # Les 2 dossiers existent toujours
    assert src.exists()
    assert target.exists()


def test_apply_rename_returns_false_if_source_missing(tmp_path):
    src = tmp_path / "Saves" / "Multiplayer" / "ghost_player"
    target = tmp_path / "Saves" / "Multiplayer" / "new_player"
    ok = apply_map_orphan_rename(src, target)
    assert ok is False


# --------- Intégration avec extract_bundle ---------

def test_extract_bundle_fills_map_orphan_candidates(tmp_path):
    """Après extract d'un bundle où le Server name = "Gitano Z" (espaces) et
    qu'il existe déjà localement un `<steamid>_Gitano_Z_player/` (underscore),
    le report doit lister ce dossier comme candidate."""
    # Setup source : Patito a la save avec Server name "Gitano Z" (espaces)
    src_root = tmp_path / "src"
    src_save = src_root / "Saves" / "Multiplayer" / "Gitano_Z"
    src_save.mkdir(parents=True)
    (src_save / "map_0_0.bin").write_bytes(b"chunk")
    (src_root / "db").mkdir()
    (src_root / "db" / "Gitano Z.db").write_bytes(b"db")
    (src_root / "Server").mkdir()
    (src_root / "Server" / "Gitano Z.ini").write_text(
        "Mods=\nWorkshopItems=\n", encoding="utf-8",
    )
    (src_root / "Server" / "Gitano Z_SandboxVars.lua").write_text("x", encoding="utf-8")
    (src_root / "Server" / "Gitano Z_spawnregions.lua").write_text("y", encoding="utf-8")

    out = tmp_path / "bundle.zip"
    bundle_mod.build_bundle("Gitano_Z", out, "patito", root=src_root)

    # Destinataire (Isaac) : a déjà joué avec l'ancien v0.3.x → fog sous underscore
    dst_root = tmp_path / "dst"
    dst_root.mkdir()
    _make_player_dir(dst_root, "76561198000099", "Gitano_Z")  # underscore (orphan)

    report = bundle_mod.extract_bundle(
        out, root=dst_root, verify_hash=True, allow_no_backup=True,
    )

    # Le report propose le renommage vers "Gitano Z" (espace)
    assert len(report.map_orphan_candidates) == 1
    src, dst = report.map_orphan_candidates[0]
    assert "Gitano_Z" in src.name  # ancien underscore
    assert "Gitano Z" in dst.name  # nouveau espace
    assert "Gitano_Z_player" not in dst.name  # bien le NOUVEAU nom


def test_extract_bundle_no_orphan_when_no_local_player_dir(tmp_path):
    """Un user qui importe pour la 1ère fois (pas de player_dir local) →
    pas de candidates, donc pas de prompt."""
    src_root = tmp_path / "src"
    src_save = src_root / "Saves" / "Multiplayer" / "Gitano_Z"
    src_save.mkdir(parents=True)
    (src_save / "map_0_0.bin").write_bytes(b"chunk")
    (src_root / "db").mkdir()
    (src_root / "Server").mkdir()

    out = tmp_path / "bundle.zip"
    bundle_mod.build_bundle("Gitano_Z", out, "anon", root=src_root)

    dst_root = tmp_path / "dst"
    dst_root.mkdir()

    report = bundle_mod.extract_bundle(
        out, root=dst_root, verify_hash=True, allow_no_backup=True,
    )
    assert report.map_orphan_candidates == []

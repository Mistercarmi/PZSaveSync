"""Tests de la migration de config v0.2 (flat) → v0.3 (avec profils)."""
import json

from pzsavesync import config


def test_migrate_v02_flat_to_profiles():
    """Une config v0.2 flat doit être encapsulée dans un profil 'default'."""
    v02 = {
        "player_name": "Alice",
        "shared_folder": "D:\\PZ",
        "save_name": "Muldraugh_Coop",
        "save_type": "Multiplayer",
        "auto_release_lock": True,
        "discord_webhook": "https://discord.com/api/webhooks/foo",
        "watch_pz_process": False,
        "onboarding_done": True,
    }
    migrated = config._migrate_from_v02(v02)
    assert "profiles" in migrated
    assert migrated["active_profile"] == "default"
    default = migrated["profiles"]["default"]
    assert default["player_name"] == "Alice"
    assert default["shared_folder"] == "D:\\PZ"
    assert default["save_name"] == "Muldraugh_Coop"
    assert default["discord_webhook"] == "https://discord.com/api/webhooks/foo"
    # Les flags globaux sont préservés
    assert migrated["watch_pz_process"] is False
    assert migrated["onboarding_done"] is True


def test_migrate_v03_passthrough():
    """Une config v0.3 (déjà avec profiles) doit passer sans modif."""
    v03 = {
        "active_profile": "grp_a",
        "profiles": {"grp_a": {"name": "Groupe A", "player_name": "Alice"}},
        "auto_release_lock": True,
    }
    out = config._migrate_from_v02(v03)
    assert out is v03  # pas de copie inutile


def test_config_load_creates_default_profile_when_missing(tmp_path, monkeypatch):
    """Si le fichier de config existe mais est cassé, on retombe sur un Config vierge."""
    bad_config = tmp_path / "config.json"
    bad_config.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", bad_config)
    cfg = config.load()
    assert "default" in cfg.profiles
    assert cfg.active_profile == "default"


def test_config_properties_proxy_to_current_profile():
    """Les @property player_name/shared_folder doivent r/w le profil actif."""
    cfg = config.Config()
    cfg.player_name = "TestUser"
    assert cfg.current.player_name == "TestUser"
    assert cfg.player_name == "TestUser"


def test_config_add_profile():
    cfg = config.Config()
    p = cfg.add_profile("grp_b", "Groupe B")
    assert "grp_b" in cfg.profiles
    assert p.name == "Groupe B"


def test_config_remove_last_profile_raises():
    cfg = config.Config()
    # Un seul profil 'default'
    import pytest
    with pytest.raises(ValueError):
        cfg.remove_profile("default")

"""Configuration de l'app : profils multi-groupes + préférences globales.

Schéma stocké dans %APPDATA%\\PZSaveSync\\config.json :

    {
      "active_profile": "default",
      "profiles": {
        "default": {
          "name": "Default",
          "player_name": "Survivor42",
          "shared_folder": "D:\\\\PZ_avec_potes",
          "save_name": "Muldraugh_Coop",
          "save_type": "Multiplayer",
          "discord_webhook": ""
        },
        "groupe-b": { ... }
      },
      "auto_release_lock": true,
      "keep_last_n_versions": 0,
      "watch_pz_process": true,
      "onboarding_done": false,
      "auto_check_updates": true,
      "last_update_check": "2026-05-21T12:00:00"
    }

Rétro-compat avec le schéma v0.2 (Config flat sans profils) : la migration
est faite au load() — on encapsule l'ancien dans un profil "default".
"""
from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _app_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "PZSaveSync"
    return Path.home() / ".config" / "pzsavesync"


APP_DIR = _app_data_dir()
CONFIG_PATH = APP_DIR / "config.json"


@dataclass
class Profile:
    """Un profil = un groupe d'amis. Plusieurs profils peuvent coexister."""
    name: str = "Default"
    player_name: str = ""
    shared_folder: str = ""
    save_name: str = ""
    save_type: str = "Multiplayer"
    discord_webhook: str = ""
    # v0.5.0 — Google Drive direct
    provider: str = "local"          # "local" | "gdrive"
    gdrive_folder_id: str = ""       # ID extrait de l'URL Drive partagée
    gdrive_folder_name: str = ""     # nom affiché (mis en cache après connexion)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Config:
    """Config globale + ensemble de profils."""
    # Profils
    active_profile: str = "default"
    profiles: dict[str, Profile] = field(default_factory=lambda: {"default": Profile()})

    # Préférences globales (pas par profil)
    auto_release_lock: bool = True
    keep_last_n_versions: int = 0
    watch_pz_process: bool = True
    onboarding_done: bool = False
    auto_check_updates: bool = True
    last_update_check: str = ""
    hide_help_banner: bool = False  # mémorise si l'user a fermé la bannière d'aide
    # v0.4.0 — bundle différentiel
    diff_mode_default: bool = True  # toggle "Envoi optimisé" coché par défaut
    diff_keep_snapshots: int = 5  # nb de snapshots gardés par save lors du GC

    # ---- Accès au profil actif (compat API v0.2) ----
    @property
    def current(self) -> Profile:
        if self.active_profile not in self.profiles:
            # Fallback : on prend n'importe quel profil ou on en crée un
            if self.profiles:
                self.active_profile = next(iter(self.profiles.keys()))
            else:
                self.profiles["default"] = Profile()
                self.active_profile = "default"
        return self.profiles[self.active_profile]

    @property
    def player_name(self) -> str:
        return self.current.player_name

    @player_name.setter
    def player_name(self, v: str):
        self.current.player_name = v

    @property
    def shared_folder(self) -> str:
        return self.current.shared_folder

    @shared_folder.setter
    def shared_folder(self, v: str):
        self.current.shared_folder = v

    @property
    def save_name(self) -> str:
        return self.current.save_name

    @save_name.setter
    def save_name(self, v: str):
        self.current.save_name = v

    @property
    def save_type(self) -> str:
        return self.current.save_type

    @save_type.setter
    def save_type(self, v: str):
        self.current.save_type = v

    @property
    def discord_webhook(self) -> str:
        return self.current.discord_webhook

    @discord_webhook.setter
    def discord_webhook(self, v: str):
        self.current.discord_webhook = v

    # ---- Helpers profils ----
    def profile_labels(self) -> list[str]:
        return [p.name or key for key, p in self.profiles.items()]

    def profile_keys(self) -> list[str]:
        return list(self.profiles.keys())

    def set_active(self, key: str) -> None:
        if key in self.profiles:
            self.active_profile = key

    def add_profile(self, key: str, name: str) -> Profile:
        if key in self.profiles:
            raise ValueError(f"Le profil '{key}' existe déjà.")
        p = Profile(name=name)
        self.profiles[key] = p
        return p

    def remove_profile(self, key: str) -> None:
        if key not in self.profiles:
            return
        if len(self.profiles) <= 1:
            raise ValueError("Impossible de supprimer le dernier profil.")
        del self.profiles[key]
        if self.active_profile == key:
            self.active_profile = next(iter(self.profiles.keys()))

    # ---- Property compat ----
    @property
    def zomboid_root(self) -> Path:
        override = os.environ.get("PZ_ZOMBOID_ROOT")
        if override:
            return Path(override)
        return Path.home() / "Zomboid"

    @property
    def save_path(self) -> Path:
        if self.save_type == "Server":
            return self.zomboid_root / "Server"
        return self.zomboid_root / "Saves" / "Multiplayer" / self.save_name

    def touch_update_check(self):
        self.last_update_check = dt.datetime.now().isoformat(timespec="seconds")


def _migrate_from_v02(data: dict) -> dict:
    """Migre un config.json v0.2 (sans profiles) vers v0.3 (avec profiles)."""
    if "profiles" in data:
        return data  # déjà v0.3+
    # v0.2 → v0.3 : on encapsule les champs flat dans un profil "default"
    profile = {
        "name": "Default",
        "player_name": data.get("player_name", ""),
        "shared_folder": data.get("shared_folder", ""),
        "save_name": data.get("save_name", ""),
        "save_type": data.get("save_type", "Multiplayer"),
        "discord_webhook": data.get("discord_webhook", ""),
    }
    migrated = {
        "active_profile": "default",
        "profiles": {"default": profile},
        "auto_release_lock": data.get("auto_release_lock", True),
        "keep_last_n_versions": data.get("keep_last_n_versions", 0),
        "watch_pz_process": data.get("watch_pz_process", True),
        "onboarding_done": data.get("onboarding_done", False),
        "auto_check_updates": True,
        "last_update_check": "",
    }
    return migrated


def load() -> Config:
    if not CONFIG_PATH.exists():
        return Config()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return Config()

    data = _migrate_from_v02(data)

    # Reconstruction des profils
    profiles_raw = data.get("profiles", {}) or {}
    profiles: dict[str, Profile] = {}
    known_profile_fields = set(Profile.__dataclass_fields__.keys())
    for key, p in profiles_raw.items():
        if not isinstance(p, dict):
            continue
        filtered = {k: v for k, v in p.items() if k in known_profile_fields}
        profiles[key] = Profile(**filtered)
    if not profiles:
        profiles["default"] = Profile()

    # Champs globaux
    known = set(Config.__dataclass_fields__.keys())
    flat = {k: v for k, v in data.items() if k in known and k not in ("profiles",)}
    cfg = Config(**flat)
    cfg.profiles = profiles
    if cfg.active_profile not in cfg.profiles:
        cfg.active_profile = next(iter(cfg.profiles.keys()))
    return cfg


def save(cfg: Config) -> None:
    """Sérialise la config sur disque en ÉCRITURE ATOMIQUE.

    Écrit dans `config.json.tmp` puis `os.replace()`. Sans ça, un crash ou
    coupure de courant pendant l'écriture laisserait un `config.json` tronqué
    et `load()` retomberait sur une Config() vide → l'user perdrait ses
    profils, son pseudo, son dossier partagé et son webhook.
    """
    APP_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "active_profile": cfg.active_profile,
        "profiles": {k: p.to_dict() for k, p in cfg.profiles.items()},
        "auto_release_lock": cfg.auto_release_lock,
        "keep_last_n_versions": cfg.keep_last_n_versions,
        "watch_pz_process": cfg.watch_pz_process,
        "onboarding_done": cfg.onboarding_done,
        "auto_check_updates": cfg.auto_check_updates,
        "last_update_check": cfg.last_update_check,
        "hide_help_banner": cfg.hide_help_banner,
        "diff_mode_default": cfg.diff_mode_default,
        "diff_keep_snapshots": cfg.diff_keep_snapshots,
    }
    payload = json.dumps(data, indent=2)
    tmp = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, CONFIG_PATH)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise

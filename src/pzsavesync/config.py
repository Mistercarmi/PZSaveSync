import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


def _app_data_dir() -> Path:
    """Dossier de config app, cross-platform."""
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "PZSaveSync"
    return Path.home() / ".config" / "pzsavesync"


APP_DIR = _app_data_dir()
CONFIG_PATH = APP_DIR / "config.json"


@dataclass
class Config:
    player_name: str = ""
    shared_folder: str = ""
    save_name: str = ""
    save_type: str = "Multiplayer"  # "Multiplayer" or "Server"

    @property
    def zomboid_root(self) -> Path:
        return Path.home() / "Zomboid"

    @property
    def save_path(self) -> Path:
        if self.save_type == "Server":
            return self.zomboid_root / "Server"
        return self.zomboid_root / "Saves" / "Multiplayer" / self.save_name


def load() -> Config:
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return Config(**data)
    return Config()


def save(cfg: Config) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")

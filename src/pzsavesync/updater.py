"""Check des mises à jour via l'API GitHub Releases.

Stdlib pure (urllib). Async-friendly via threading.
"""
from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable


REPO_OWNER = "Mistercarmi"
REPO_NAME = "PZSaveSync"
LATEST_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases"


@dataclass
class UpdateInfo:
    available: bool
    current: str
    latest: str
    download_url: str = ""
    body: str = ""
    error: str = ""


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse une version 'v0.2.0' ou '0.2.0' → (0, 2, 0). Renvoie (0,) si parsing échoue."""
    if not v:
        return (0,)
    v = v.strip().lstrip("vV")
    parts = re.split(r"[.\-+]", v)
    out: list[int] = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            break
    return tuple(out) if out else (0,)


def is_newer(latest: str, current: str) -> bool:
    """True si `latest` est strictement plus récent que `current`."""
    return _parse_version(latest) > _parse_version(current)


def check_latest(current_version: str, timeout: float = 4.0) -> UpdateInfo:
    """Interroge GitHub pour le dernier release publié. Synchrone, peut throw."""
    info = UpdateInfo(available=False, current=current_version, latest="")
    try:
        req = urllib.request.Request(
            LATEST_API_URL,
            headers={
                "User-Agent": f"PZSaveSync/{current_version}",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                info.error = f"HTTP {resp.status}"
                return info
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        info.error = f"HTTP {e.code} — {e.reason}"
        return info
    except urllib.error.URLError as e:
        info.error = f"Réseau : {e.reason}"
        return info
    except (json.JSONDecodeError, ValueError) as e:
        info.error = f"Parsing : {e}"
        return info
    except Exception as e:
        info.error = str(e)
        return info

    tag = (data.get("tag_name") or data.get("name") or "").strip()
    info.latest = tag
    info.body = data.get("body", "")
    # Cherche le .exe en asset
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.lower().endswith(".exe"):
            info.download_url = asset.get("browser_download_url", "")
            break
    if not info.download_url:
        info.download_url = data.get("html_url", RELEASES_URL)
    info.available = is_newer(tag, current_version)
    return info


def check_latest_async(
    current_version: str,
    on_done: Callable[[UpdateInfo], None],
    timeout: float = 4.0,
) -> None:
    """Lance `check_latest` dans un thread daemon ; appelle `on_done` à la fin."""
    def worker():
        info = check_latest(current_version, timeout=timeout)
        on_done(info)
    threading.Thread(target=worker, daemon=True).start()

"""Notifications Discord via webhook (optionnel).

Implémenté en stdlib pure (urllib) pour ne pas ajouter de dépendance.
Si l'URL est vide ou invalide, les fonctions retournent silencieusement False.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


# User-Agent unique : on n'importe pas APP_VERSION depuis gui.py pour éviter
# un cycle d'import (gui → discord_webhook). On synchronise manuellement.
USER_AGENT = "PZSaveSync/0.3.6"

PZ_COLOR_GREEN = 0x2e8b57   # même teinte que notre action "push" dans la GUI
PZ_COLOR_BLUE = 0x2c7fb8
PZ_COLOR_RED = 0xb24545


def _is_valid_webhook_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    url = url.strip().lower()
    return (
        url.startswith("https://discord.com/api/webhooks/")
        or url.startswith("https://discordapp.com/api/webhooks/")
        or url.startswith("https://canary.discord.com/api/webhooks/")
        or url.startswith("https://ptb.discord.com/api/webhooks/")
    )


def post(url: str, payload: dict[str, Any], timeout: float = 5.0) -> tuple[bool, str]:
    """Envoie un payload JSON au webhook. Renvoie (ok, message)."""
    if not _is_valid_webhook_url(url):
        return False, "URL de webhook invalide (doit commencer par https://discord.com/api/webhooks/)."
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.status
            if 200 <= code < 300:
                return True, f"HTTP {code}"
            return False, f"HTTP {code}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code} — {e.reason}"
    except urllib.error.URLError as e:
        return False, f"Réseau : {e.reason}"
    except (json.JSONDecodeError, ValueError) as e:
        return False, f"Payload : {e}"
    except Exception as e:
        return False, f"Erreur : {e}"


def notify_push(
    url: str,
    *,
    player: str,
    save_name: str,
    size_mb: float,
    note: str = "",
    versions_count: int | None = None,
) -> tuple[bool, str]:
    """Notification quand quelqu'un push une nouvelle session."""
    fields = [
        {"name": "Partie", "value": f"`{save_name}`", "inline": True},
        {"name": "Taille", "value": f"{size_mb:.1f} MB", "inline": True},
    ]
    if versions_count is not None:
        fields.append({"name": "Versions au total", "value": str(versions_count), "inline": True})
    if note:
        fields.append({"name": "Note", "value": note[:1000]})
    embed = {
        "title": "⬆ Nouvelle session disponible",
        "description": f"**{player}** vient de push une session — n'importe qui peut la pull pour héberger la prochaine.",
        "color": PZ_COLOR_GREEN,
        "fields": fields,
        "footer": {"text": "PZ SaveSync"},
    }
    return post(url, {"embeds": [embed]})


def notify_test(url: str, player: str = "(test)") -> tuple[bool, str]:
    """Notif de test pour valider que le webhook fonctionne."""
    embed = {
        "title": "🧪 Test webhook PZ SaveSync",
        "description": (
            f"Si tu vois ce message, le webhook configuré par **{player}** "
            "fonctionne. À chaque push, le canal recevra une notif."
        ),
        "color": PZ_COLOR_BLUE,
        "footer": {"text": "PZ SaveSync"},
    }
    return post(url, {"embeds": [embed]})


def notify_lock_released(url: str, *, player: str, save_name: str = "") -> tuple[bool, str]:
    """Optionnel : signaler que le tour est libéré."""
    desc = f"**{player}** vient de libérer le tour."
    if save_name:
        desc += f" Partie : `{save_name}`."
    embed = {
        "title": "🔓 Tour libéré",
        "description": desc,
        "color": PZ_COLOR_BLUE,
        "footer": {"text": "PZ SaveSync"},
    }
    return post(url, {"embeds": [embed]})

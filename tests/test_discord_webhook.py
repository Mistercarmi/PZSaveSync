"""Tests du module discord_webhook (validation URL)."""
from pzsavesync import discord_webhook


def test_valid_discord_url():
    assert discord_webhook._is_valid_webhook_url(
        "https://discord.com/api/webhooks/123456/abcdef"
    )
    assert discord_webhook._is_valid_webhook_url(
        "https://discordapp.com/api/webhooks/123/abc"
    )
    assert discord_webhook._is_valid_webhook_url(
        "https://canary.discord.com/api/webhooks/123/abc"
    )


def test_invalid_url_rejected():
    assert not discord_webhook._is_valid_webhook_url("")
    assert not discord_webhook._is_valid_webhook_url("not a url")
    assert not discord_webhook._is_valid_webhook_url("http://evil.com/api/webhooks/foo")
    assert not discord_webhook._is_valid_webhook_url("https://slack.com/api/webhooks/foo")
    assert not discord_webhook._is_valid_webhook_url(None)


def test_post_to_invalid_url_returns_error_tuple():
    """post() doit toujours retourner (bool, str) — pas raise."""
    ok, msg = discord_webhook.post("not-an-url", {"content": "test"})
    assert ok is False
    assert isinstance(msg, str)
    assert "invalide" in msg.lower() or "URL" in msg

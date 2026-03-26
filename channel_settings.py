"""
channel_settings.py — Persistent channel routing settings for the bot.

Stored in channel_settings.json:
{
  "predictions_channel_id": 123456789,
  "alerts_channel_id": 123456789,
  "news_channel_id": 123456789
}

If a channel isn't configured, the getters return None and callers fall back
to the DISCORD_CHANNEL_ID environment variable.
"""

from __future__ import annotations

import json
import os

SETTINGS_FILE = "channel_settings.json"


def _load() -> dict:
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save(data: dict) -> None:
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Getters
# ---------------------------------------------------------------------------

def get_predictions_channel() -> int | None:
    """Return the configured predictions channel ID, or None."""
    return _load().get("predictions_channel_id")


def get_alerts_channel() -> int | None:
    """Return the configured alerts channel ID, or None."""
    return _load().get("alerts_channel_id")


def get_news_channel() -> int | None:
    """Return the configured news channel ID, or None."""
    return _load().get("news_channel_id")


# ---------------------------------------------------------------------------
# Setters
# ---------------------------------------------------------------------------

def set_predictions_channel(channel_id: int) -> None:
    """Set the channel for daily prediction digests."""
    data = _load()
    data["predictions_channel_id"] = channel_id
    _save(data)


def set_alerts_channel(channel_id: int) -> None:
    """Set the channel for big move price alerts."""
    data = _load()
    data["alerts_channel_id"] = channel_id
    _save(data)


def set_news_channel(channel_id: int) -> None:
    """Set the channel for breaking news alerts."""
    data = _load()
    data["news_channel_id"] = channel_id
    _save(data)


def set_all_channels(channel_id: int) -> None:
    """Set all three channel types to the same channel."""
    data = _load()
    data["predictions_channel_id"] = channel_id
    data["alerts_channel_id"] = channel_id
    data["news_channel_id"] = channel_id
    _save(data)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def get_all_settings() -> dict:
    """Return the full channel settings dict."""
    return _load()

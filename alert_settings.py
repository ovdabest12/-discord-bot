"""
alert_settings.py — Persistent settings for the real-time market alert system.

Stored in alert_settings.json:
{
  "enabled": false,
  "channel_id": null,
  "tickers": ["NQ=F", "ES=F", "SPY", "QQQ"]
}
"""

from __future__ import annotations

import json
import os

SETTINGS_FILE = "alert_settings.json"
DEFAULT_TICKERS = ["NQ=F", "ES=F", "SPY", "QQQ"]


def _load() -> dict:
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"enabled": False, "channel_id": None, "tickers": list(DEFAULT_TICKERS)}


def _save(data: dict) -> None:
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def is_enabled() -> bool:
    """Return True if the real-time alert system is currently enabled."""
    return bool(_load().get("enabled", False))


def get_channel_id() -> str | None:
    """Return the configured alert channel ID (string), or None."""
    return _load().get("channel_id")


def set_enabled(channel_id: str | None, enabled: bool) -> None:
    """Enable or disable alerts; optionally update the target channel."""
    data = _load()
    data["enabled"] = enabled
    if channel_id is not None:
        data["channel_id"] = channel_id
    _save(data)


def get_monitored_tickers() -> list[str]:
    """Return the list of tickers to actively monitor."""
    return list(_load().get("tickers", DEFAULT_TICKERS))


def add_ticker(ticker: str) -> bool:
    """Add a ticker to the monitor list. Returns True if added, False if already present."""
    data = _load()
    tickers = data.get("tickers", list(DEFAULT_TICKERS))
    if ticker in tickers:
        return False
    tickers.append(ticker)
    data["tickers"] = tickers
    _save(data)
    return True


def remove_ticker(ticker: str) -> bool:
    """Remove a ticker from the monitor list. Returns True if removed, False if not found."""
    data = _load()
    tickers = data.get("tickers", list(DEFAULT_TICKERS))
    if ticker not in tickers:
        return False
    tickers.remove(ticker)
    data["tickers"] = tickers
    _save(data)
    return True

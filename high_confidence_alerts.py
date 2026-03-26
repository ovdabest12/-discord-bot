"""
high_confidence_alerts.py — Auto-alert when a prediction confidence hits 75%+.

Whenever any prediction (from /predict, /quick, scheduled digests, or alert
monitors) returns a confidence of 75% or higher for a non-neutral direction,
this module sends a notification embed to the alerts/news channel.

Cooldown: one high-confidence alert per ticker per 30 minutes to avoid spam.
"""

from __future__ import annotations

import datetime
import os

import discord

import alert_settings as als
import watchlist as wl
from scoring import PredictionResult, quick_summary
import channel_settings as cs

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HIGH_CONF_THRESHOLD = 75          # percent
HIGH_CONF_COOLDOWN_MINUTES = 30

# ---------------------------------------------------------------------------
# In-memory cooldown state
# ---------------------------------------------------------------------------

# ticker -> UTC datetime of last high-confidence alert sent
_last_high_conf_alert: dict[str, datetime.datetime] = {}


def _is_on_cooldown(ticker: str) -> bool:
    if ticker not in _last_high_conf_alert:
        return False
    elapsed = (
        datetime.datetime.now(datetime.timezone.utc) - _last_high_conf_alert[ticker]
    ).total_seconds()
    return elapsed < HIGH_CONF_COOLDOWN_MINUTES * 60


def _set_cooldown(ticker: str) -> None:
    _last_high_conf_alert[ticker] = datetime.datetime.now(datetime.timezone.utc)


# ---------------------------------------------------------------------------
# Channel resolution
# ---------------------------------------------------------------------------

def _resolve_channel_id() -> str | None:
    """Return the alerts channel ID from settings, falling back to env var."""
    cid = cs.get_alerts_channel()
    if cid:
        return str(cid)
    return als.get_channel_id() or os.getenv("DISCORD_CHANNEL_ID")


# ---------------------------------------------------------------------------
# Alert embed builder
# ---------------------------------------------------------------------------

def _build_high_conf_embed(result: PredictionResult) -> discord.Embed:
    direction_word = "BULLISH" if result.direction == "UP" else "BEARISH"
    dir_emoji = "🟢" if result.direction == "UP" else "🔴"
    color = (
        discord.Color.green() if result.direction == "UP" else discord.Color.red()
    )

    summary = quick_summary(result)
    # quick_summary returns "BULLISH (72%) — reason text"; extract just the reason
    parts = summary.split(" — ", 1)
    why_text = parts[1].capitalize() if len(parts) > 1 else summary

    embed = discord.Embed(
        title=f"🔥 HIGH CONFIDENCE ALERT — {HIGH_CONF_THRESHOLD}%+",
        color=color,
    )
    embed.description = (
        f"{dir_emoji} **{result.ticker}** — {direction_word} ({int(result.confidence)}%)\n"
        f"💡 {why_text}\n"
        f"💰 Confidence is high — worth watching closely!"
    )
    embed.set_footer(text=f"⚡ Use /predict {result.ticker} for full breakdown")
    return embed


# ---------------------------------------------------------------------------
# Main helper — call this after every prediction
# ---------------------------------------------------------------------------

async def check_high_confidence_alert(
    result: PredictionResult, bot: discord.Client
) -> None:
    """
    Send a high-confidence alert embed to the alerts channel if:
      - result.confidence >= 75
      - result.direction is UP or DOWN (not NEUTRAL)
      - result.error is None
      - The ticker is on at least one user's watchlist
      - No alert was sent for this ticker in the last 30 minutes
    """
    try:
        if result.error:
            return
        if result.direction == "NEUTRAL":
            return
        if result.confidence < HIGH_CONF_THRESHOLD:
            return
        if result.ticker not in wl.get_all_tickers():
            return
        if _is_on_cooldown(result.ticker):
            return

        channel_id = _resolve_channel_id()
        if not channel_id:
            return
        channel = bot.get_channel(int(channel_id))
        if not channel:
            return

        embed = _build_high_conf_embed(result)
        await channel.send(embed=embed)
        _set_cooldown(result.ticker)
    except Exception:
        pass  # Never let an alert failure propagate to callers

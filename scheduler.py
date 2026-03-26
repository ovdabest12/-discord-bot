"""
scheduler.py — Scheduled digest tasks for the Stock Confidence Predictor bot.

Schedules:
  - London/NY Overlap: 8:00 AM EST (13:00 UTC)
  - Morning Digest:    9:00 AM EST (14:00 UTC)
  - US Market Open:    9:30 AM EST (14:30 UTC)
  - Afternoon Alert:   3:15 PM EST (20:15 UTC)
"""

from __future__ import annotations

import asyncio
import datetime
import os

import discord
from discord.ext import tasks

import watchlist as wl
from scoring import predict
from high_confidence_alerts import check_high_confidence_alert

# UTC times corresponding to EST (UTC-5) — no DST adjustment needed for a
# simple bot; adjust offsets manually for EDT (UTC-4) if desired.
LONDON_NY_UTC_HOUR = 13   # 8:00 AM EST = 13:00 UTC
LONDON_NY_UTC_MIN = 0

MORNING_UTC_HOUR = 14     # 9:00 AM EST = 14:00 UTC
MORNING_UTC_MIN = 0

US_OPEN_UTC_HOUR = 14     # 9:30 AM EST = 14:30 UTC
US_OPEN_UTC_MIN = 30

AFTERNOON_UTC_HOUR = 20   # 3:15 PM EST = 20:15 UTC
AFTERNOON_UTC_MIN = 15


def _direction_emoji(direction: str) -> str:
    return "⬆️" if direction == "UP" else ("⬇️" if direction == "DOWN" else "➡️")


def _build_prediction_embed(result) -> discord.Embed:
    color = discord.Color.green() if result.direction == "UP" else (
        discord.Color.red() if result.direction == "DOWN" else discord.Color.yellow()
    )
    embed = discord.Embed(
        title=f"📊 {result.ticker} — Prediction: {_direction_emoji(result.direction)} {result.direction}",
        color=color,
    )
    if result.error:
        embed.description = f"⚠️ {result.error}"
        return embed

    embed.add_field(
        name="📈 UP by 3 PM EST",
        value=f"{result.up_probability}%",
        inline=True,
    )
    embed.add_field(
        name="📉 DOWN by 3 PM EST",
        value=f"{result.down_probability}%",
        inline=True,
    )
    embed.add_field(
        name="🔒 Confidence",
        value=f"{result.confidence}% ({result.confidence_label})",
        inline=True,
    )
    embed.add_field(
        name="📅 Window",
        value="Until 3:00 PM EST",
        inline=True,
    )
    if result.reasons:
        reasons_text = "\n".join(f"{i+1}. {r}" for i, r in enumerate(result.reasons))
        embed.add_field(name="Reasons", value=reasons_text, inline=False)
    return embed


def _build_morning_embed(result) -> discord.Embed:
    color = discord.Color.green() if result.direction == "UP" else (
        discord.Color.red() if result.direction == "DOWN" else discord.Color.yellow()
    )
    embed = discord.Embed(
        title=f"🌅 {result.ticker} — Pre-Market Overview",
        color=color,
    )
    if result.error:
        embed.description = f"⚠️ {result.error}"
        return embed

    embed.description = (
        f"**Outlook:** {_direction_emoji(result.direction)} {result.direction} "
        f"| **Confidence:** {result.confidence}% ({result.confidence_label})"
    )
    embed.add_field(
        name="📈 UP by 3 PM EST",
        value=f"{result.up_probability}%",
        inline=True,
    )
    embed.add_field(
        name="📉 DOWN by 3 PM EST",
        value=f"{result.down_probability}%",
        inline=True,
    )
    embed.add_field(
        name="📅 Window",
        value="Until 3:00 PM EST",
        inline=True,
    )
    if result.reasons:
        reasons_text = "\n".join(f"• {r}" for r in result.reasons[:3])
        embed.add_field(name="Key Signals", value=reasons_text, inline=False)
    return embed


def _build_london_ny_embed(result) -> discord.Embed:
    color = discord.Color.green() if result.direction == "UP" else (
        discord.Color.red() if result.direction == "DOWN" else discord.Color.yellow()
    )
    embed = discord.Embed(
        title=f"🔥 {result.ticker} — London/NY Overlap",
        color=color,
    )
    if result.error:
        embed.description = f"⚠️ {result.error}"
        return embed

    embed.description = (
        f"**Outlook:** {_direction_emoji(result.direction)} {result.direction} "
        f"| **Confidence:** {result.confidence}% ({result.confidence_label})"
    )
    embed.add_field(
        name="📈 UP by 3 PM EST",
        value=f"{result.up_probability}%",
        inline=True,
    )
    embed.add_field(
        name="📉 DOWN by 3 PM EST",
        value=f"{result.down_probability}%",
        inline=True,
    )
    embed.add_field(
        name="📅 Window",
        value="Until 3:00 PM EST",
        inline=True,
    )
    if result.reasons:
        reasons_text = "\n".join(f"• {r}" for r in result.reasons[:3])
        embed.add_field(name="Key Signals", value=reasons_text, inline=False)
    return embed


def _build_us_open_embed(result) -> discord.Embed:
    color = discord.Color.green() if result.direction == "UP" else (
        discord.Color.red() if result.direction == "DOWN" else discord.Color.yellow()
    )
    embed = discord.Embed(
        title=f"🇺🇸 {result.ticker} — US Market Open",
        color=color,
    )
    if result.error:
        embed.description = f"⚠️ {result.error}"
        return embed

    embed.description = (
        f"**Outlook:** {_direction_emoji(result.direction)} {result.direction} "
        f"| **Confidence:** {result.confidence}% ({result.confidence_label})"
    )
    embed.add_field(
        name="📈 UP by 3 PM EST",
        value=f"{result.up_probability}%",
        inline=True,
    )
    embed.add_field(
        name="📉 DOWN by 3 PM EST",
        value=f"{result.down_probability}%",
        inline=True,
    )
    embed.add_field(
        name="📅 Window",
        value="Until 3:00 PM EST",
        inline=True,
    )
    if result.reasons:
        reasons_text = "\n".join(f"• {r}" for r in result.reasons[:3])
        embed.add_field(name="Key Signals", value=reasons_text, inline=False)
    return embed


async def _send_alert(
    bot: discord.Client,
    empty_msg: str,
    header: str,
    embed_fn,
) -> None:
    """Send a scheduled alert to the configured channel."""
    channel_id = os.getenv("DISCORD_CHANNEL_ID")
    if not channel_id:
        return
    channel = bot.get_channel(int(channel_id))
    if not channel:
        return

    tickers = wl.get_all_tickers()
    if not tickers:
        await channel.send(empty_msg)
        return

    await channel.send(header.format(count=len(tickers)))
    for ticker in tickers:
        result = await bot.loop.run_in_executor(None, predict, ticker)
        await channel.send(embed=embed_fn(result))
        await check_high_confidence_alert(result, bot)


async def _wait_until_utc(bot: discord.Client, utc_hour: int, utc_minute: int) -> None:
    """Sleep until the next occurrence of the given UTC time."""
    await bot.wait_until_ready()
    now = datetime.datetime.utcnow()
    target = now.replace(hour=utc_hour, minute=utc_minute, second=0, microsecond=0)
    if now >= target:
        target += datetime.timedelta(days=1)
    await asyncio.sleep((target - now).total_seconds())


def setup_scheduler(bot: discord.Client) -> None:
    """Register and start the scheduled digest tasks."""

    @tasks.loop(hours=24)
    async def london_ny_overlap() -> None:
        await _send_alert(
            bot,
            empty_msg="🔥 **London/NY Overlap (8:00 AM EST)** — No stocks on any watchlist yet.",
            header="🔥 **London/NY Overlap** — 8:00 AM EST predictions for {count} stock(s):",
            embed_fn=_build_london_ny_embed,
        )

    @tasks.loop(hours=24)
    async def morning_digest() -> None:
        await _send_alert(
            bot,
            empty_msg="☀️ **Morning Digest** — No stocks on any watchlist yet.",
            header="☀️ **Morning Digest** — Pre-market overview for {count} stock(s):",
            embed_fn=_build_morning_embed,
        )

    @tasks.loop(hours=24)
    async def us_market_open() -> None:
        await _send_alert(
            bot,
            empty_msg="🇺🇸 **US Market Open (9:30 AM EST)** — No stocks on any watchlist yet.",
            header="🇺🇸 **US Market Open** — 9:30 AM EST predictions for {count} stock(s):",
            embed_fn=_build_us_open_embed,
        )

    @tasks.loop(hours=24)
    async def afternoon_alert() -> None:
        await _send_alert(
            bot,
            empty_msg="📈 **Afternoon Alert (3:15 PM EST)** — No stocks on any watchlist yet.",
            header="📈 **Afternoon Alert** — 3:15 PM EST predictions for {count} stock(s):",
            embed_fn=_build_prediction_embed,
        )

    @london_ny_overlap.before_loop
    async def before_london_ny() -> None:
        await _wait_until_utc(bot, LONDON_NY_UTC_HOUR, LONDON_NY_UTC_MIN)

    @morning_digest.before_loop
    async def before_morning() -> None:
        await _wait_until_utc(bot, MORNING_UTC_HOUR, MORNING_UTC_MIN)

    @us_market_open.before_loop
    async def before_us_open() -> None:
        await _wait_until_utc(bot, US_OPEN_UTC_HOUR, US_OPEN_UTC_MIN)

    @afternoon_alert.before_loop
    async def before_afternoon() -> None:
        await _wait_until_utc(bot, AFTERNOON_UTC_HOUR, AFTERNOON_UTC_MIN)

    london_ny_overlap.start()
    morning_digest.start()
    us_market_open.start()
    afternoon_alert.start()

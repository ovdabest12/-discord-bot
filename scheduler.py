"""
scheduler.py — Scheduled digest tasks for the Stock Confidence Predictor bot.

Schedules:
  - Morning Digest: 9:00 AM EST (14:00 UTC)
  - Afternoon Alert: 3:15 PM EST (20:15 UTC)
"""

from __future__ import annotations

import asyncio
import datetime
import os

import discord
from discord.ext import tasks

import watchlist as wl
from scoring import predict

# UTC times corresponding to EST (UTC-5) — no DST adjustment needed for a
# simple bot; adjust offsets manually for EDT (UTC-4) if desired.
MORNING_UTC_HOUR = 14   # 9:00 AM EST = 14:00 UTC
MORNING_UTC_MIN = 0

AFTERNOON_UTC_HOUR = 20  # 3:15 PM EST = 20:15 UTC
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
        name="🔒 Confidence",
        value=f"{result.confidence}% ({result.confidence_label})",
        inline=True,
    )
    embed.add_field(
        name="📅 Window",
        value="3:15 PM – 5:30 PM EST",
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
    if result.reasons:
        reasons_text = "\n".join(f"• {r}" for r in result.reasons[:3])
        embed.add_field(name="Key Signals", value=reasons_text, inline=False)
    return embed


def setup_scheduler(bot: discord.Client) -> None:
    """Register and start the scheduled digest tasks."""

    @tasks.loop(hours=24)
    async def morning_digest() -> None:
        channel_id = os.getenv("DISCORD_CHANNEL_ID")
        if not channel_id:
            return
        channel = bot.get_channel(int(channel_id))
        if not channel:
            return

        tickers = wl.get_all_tickers()
        if not tickers:
            await channel.send("☀️ **Morning Digest** — No stocks on any watchlist yet.")
            return

        await channel.send(
            f"☀️ **Morning Digest** — Pre-market overview for {len(tickers)} stock(s):"
        )
        for ticker in tickers:
            result = await bot.loop.run_in_executor(None, predict, ticker)
            embed = _build_morning_embed(result)
            await channel.send(embed=embed)

    @tasks.loop(hours=24)
    async def afternoon_alert() -> None:
        channel_id = os.getenv("DISCORD_CHANNEL_ID")
        if not channel_id:
            return
        channel = bot.get_channel(int(channel_id))
        if not channel:
            return

        tickers = wl.get_all_tickers()
        if not tickers:
            await channel.send(
                "📈 **Afternoon Alert (3:15 PM EST)** — No stocks on any watchlist yet."
            )
            return

        await channel.send(
            f"📈 **Afternoon Alert** — 3:15 PM EST predictions for {len(tickers)} stock(s):"
        )
        for ticker in tickers:
            result = await bot.loop.run_in_executor(None, predict, ticker)
            embed = _build_prediction_embed(result)
            await channel.send(embed=embed)

    @morning_digest.before_loop
    async def before_morning() -> None:
        await bot.wait_until_ready()
        now = datetime.datetime.utcnow()
        target = now.replace(
            hour=MORNING_UTC_HOUR, minute=MORNING_UTC_MIN, second=0, microsecond=0
        )
        if now >= target:
            target += datetime.timedelta(days=1)
        delta = (target - now).total_seconds()
        await asyncio.sleep(delta)

    @afternoon_alert.before_loop
    async def before_afternoon() -> None:
        await bot.wait_until_ready()
        now = datetime.datetime.utcnow()
        target = now.replace(
            hour=AFTERNOON_UTC_HOUR, minute=AFTERNOON_UTC_MIN, second=0, microsecond=0
        )
        if now >= target:
            target += datetime.timedelta(days=1)
        delta = (target - now).total_seconds()
        await asyncio.sleep(delta)

    morning_digest.start()
    afternoon_alert.start()

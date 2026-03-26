"""
alerts.py — Real-time market alert system.

Features:
  - Big move detection: monitors tickers every 60 seconds, alerts on
    ±0.5% / ±1.0% / ±2.0% moves measured over a 5-minute window.
  - News sentiment monitor: checks yfinance headlines every 5 minutes
    and alerts when strongly bullish or bearish language is detected.

Call setup_alerts(bot) once the Discord client is ready.
"""

from __future__ import annotations

import datetime
import os
from collections import defaultdict, deque

import discord
import yfinance as yf
from discord.ext import tasks

import alert_settings as als
import watchlist as wl

# EST is UTC-5 (standard time); adjust to -4 for EDT if desired.
_EST_OFFSET = datetime.timezone(datetime.timedelta(hours=-5))

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------

# ticker -> deque of (utc_datetime, price) — keeps ~10 min of readings
_price_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=10))

# (ticker, direction) -> utc datetime of last alert sent
_last_alert: dict[tuple[str, str], datetime.datetime] = {}
# UUIDs / IDs of news articles already seen
_seen_news: set[str] = set()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COOLDOWN_MINUTES = 15
PRICE_WINDOW_MINUTES = 5

NOTABLE_THRESHOLD = 0.5   # ⚠️
BIG_THRESHOLD = 1.0        # 🚨
EXTREME_THRESHOLD = 2.0    # 🔴

VERY_STRONG_KEYWORDS: set[str] = {
    "crash", "surge", "war", "recession", "rally", "bankruptcy",
}
BEARISH_KEYWORDS: set[str] = {
    "crash", "plunge", "recession", "layoffs", "downgrade", "sell-off",
    "crisis", "bankruptcy", "default", "war", "tariff", "ban",
    "investigation", "fraud", "miss", "cut", "warning",
}
BULLISH_KEYWORDS: set[str] = {
    "surge", "rally", "breakthrough", "upgrade", "beat", "record", "soar",
    "approval", "deal", "partnership", "acquisition", "buyback", "dividend",
    "boom", "bullish",
}


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _get_monitored_tickers() -> list[str]:
    """Combine settings tickers and all watchlist tickers (deduplicated)."""
    seen: set[str] = set()
    result: list[str] = []
    for t in als.get_monitored_tickers() + wl.get_all_tickers():
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


def _fetch_price(ticker: str) -> float | None:
    try:
        return yf.Ticker(ticker).fast_info.last_price
    except Exception:
        return None


def _fetch_volume_info(ticker: str) -> tuple[float | None, float | None]:
    """Return (today_total_volume, three_month_avg_volume)."""
    try:
        info = yf.Ticker(ticker).fast_info
        avg_vol = getattr(info, "three_month_average_volume", None)
        hist = yf.Ticker(ticker).history(period="1d", interval="1m")
        curr_vol = float(hist["Volume"].sum()) if not hist.empty else None
        return curr_vol, avg_vol
    except Exception:
        return None, None


def _fetch_news(ticker: str) -> list[dict]:
    try:
        return yf.Ticker(ticker).news or []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Cooldown helpers
# ---------------------------------------------------------------------------

def _is_on_cooldown(ticker: str, direction: str) -> bool:
    key = (ticker, direction)
    if key not in _last_alert:
        return False
    elapsed = (datetime.datetime.now(datetime.timezone.utc) - _last_alert[key]).total_seconds()
    return elapsed < COOLDOWN_MINUTES * 60


def _set_cooldown(ticker: str, direction: str) -> None:
    _last_alert[(ticker, direction)] = datetime.datetime.now(datetime.timezone.utc)


# ---------------------------------------------------------------------------
# Embed builders
# ---------------------------------------------------------------------------

def _build_move_embed(
    ticker: str,
    direction: str,
    pct_change: float,
    current_price: float,
    price_change: float,
    volume_spike: float | None,
) -> discord.Embed:
    abs_pct = abs(pct_change)
    if abs_pct >= EXTREME_THRESHOLD:
        color = discord.Color.red()
        title_prefix = "🔴 EXTREME MOVE DETECTED"
    elif abs_pct >= BIG_THRESHOLD:
        color = discord.Color.from_rgb(255, 100, 0)
        title_prefix = "🚨 BIG MOVE DETECTED"
    else:
        color = discord.Color.yellow()
        title_prefix = "⚠️ NOTABLE MOVE DETECTED"

    dir_emoji = "⬆️ UP" if direction == "UP" else "⬇️ DOWN"
    now_est = datetime.datetime.now(_EST_OFFSET)
    time_str = now_est.strftime("%I:%M %p") + " EST"

    embed = discord.Embed(title=f"{title_prefix} — {ticker}", color=color)
    embed.add_field(
        name="Direction",
        value=f"{dir_emoji} {pct_change:+.2f}% in 5 min",
        inline=False,
    )
    embed.add_field(name="Current Price", value=f"${current_price:,.2f}", inline=True)
    embed.add_field(name="5-Min Change", value=f"${price_change:+,.2f}", inline=True)
    if volume_spike is not None:
        embed.add_field(
            name="Volume Spike", value=f"{volume_spike:.1f}x normal", inline=True
        )
    embed.add_field(name="⏰ Detected at", value=time_str, inline=False)
    embed.set_footer(text=f"💡 Tip: Check /predict {ticker} for full analysis")
    return embed


def _analyze_sentiment(headline: str) -> tuple[str, list[str]]:
    """
    Analyze a news headline for market-moving language.

    Returns (sentiment_label, matched_keywords).
    sentiment_label is one of: 'strongly_bearish', 'bearish',
    'strongly_bullish', 'bullish', 'mixed', 'neutral'.
    An alert is sent only when sentiment_label is not 'neutral'.
    """
    lower = headline.lower()
    matched_bearish = [kw for kw in BEARISH_KEYWORDS if kw in lower]
    matched_bullish = [kw for kw in BULLISH_KEYWORDS if kw in lower]
    very_strong = [kw for kw in VERY_STRONG_KEYWORDS if kw in lower]

    total = len(matched_bearish) + len(matched_bullish)
    if total < 2 and not very_strong:
        return "neutral", []

    all_matched = matched_bearish + matched_bullish
    b = len(matched_bearish)
    u = len(matched_bullish)
    vs_bearish = any(k in VERY_STRONG_KEYWORDS for k in matched_bearish)
    vs_bullish = any(k in VERY_STRONG_KEYWORDS for k in matched_bullish)

    if b > u or vs_bearish:
        sentiment = "strongly_bearish" if (b >= 2 or vs_bearish) else "bearish"
    elif u > b or vs_bullish:
        sentiment = "strongly_bullish" if (u >= 2 or vs_bullish) else "bullish"
    else:
        sentiment = "mixed"

    return sentiment, all_matched


def _sentiment_display(sentiment: str) -> str:
    return {
        "strongly_bearish": "🔴 Strongly Bearish",
        "bearish": "🟠 Bearish",
        "bullish": "🟢 Bullish",
        "strongly_bullish": "🟢 Strongly Bullish",
        "mixed": "🟡 Mixed",
    }.get(sentiment, "⬜ Neutral")


def _build_news_embed(
    headline: str,
    tickers: list[str],
    sentiment: str,
) -> discord.Embed:
    now_est = datetime.datetime.now(_EST_OFFSET)
    time_str = now_est.strftime("%I:%M %p") + " EST"

    if "bearish" in sentiment:
        color = discord.Color.red()
    elif "bullish" in sentiment:
        color = discord.Color.green()
    else:
        color = discord.Color.yellow()

    embed = discord.Embed(
        title="📰 BREAKING NEWS ALERT — Could Move Markets", color=color
    )
    embed.add_field(name="📌 Headline", value=f'"{headline}"', inline=False)
    if tickers:
        embed.add_field(name="🏷️ Related", value=", ".join(tickers), inline=True)
    embed.add_field(
        name="📊 Sentiment", value=_sentiment_display(sentiment), inline=True
    )
    embed.add_field(name="⏰ Time", value=time_str, inline=True)
    embed.set_footer(text="💡 React fast — use /predict to check current signals")
    return embed


# ---------------------------------------------------------------------------
# Alert channel resolution
# ---------------------------------------------------------------------------

def _resolve_channel_id() -> str | None:
    """Return the alert channel ID from settings, falling back to env var."""
    return als.get_channel_id() or os.getenv("DISCORD_CHANNEL_ID")


# ---------------------------------------------------------------------------
# Task setup
# ---------------------------------------------------------------------------

def setup_alerts(bot: discord.Client) -> None:
    """Register and start the real-time alert monitoring loops."""

    @tasks.loop(seconds=60)
    async def price_monitor() -> None:
        """Detect significant price moves and send Discord alerts."""
        if not als.is_enabled():
            return
        channel_id = _resolve_channel_id()
        if not channel_id:
            return
        channel = bot.get_channel(int(channel_id))
        if not channel:
            return

        now = datetime.datetime.now(datetime.timezone.utc)
        for ticker in _get_monitored_tickers():
            try:
                current_price = await bot.loop.run_in_executor(
                    None, _fetch_price, ticker
                )
                if current_price is None:
                    continue

                history = _price_history[ticker]
                history.append((now, current_price))

                # Find the oldest reading that is at least PRICE_WINDOW_MINUTES old
                window_start = now - datetime.timedelta(minutes=PRICE_WINDOW_MINUTES)
                baseline: tuple[datetime.datetime, float] | None = None
                for ts, price in history:
                    if ts <= window_start:
                        baseline = (ts, price)

                if baseline is None:
                    continue  # Not enough history yet

                old_price = baseline[1]
                price_change = current_price - old_price
                pct_change = (price_change / old_price) * 100

                if abs(pct_change) < NOTABLE_THRESHOLD:
                    continue

                direction = "UP" if pct_change > 0 else "DOWN"
                if _is_on_cooldown(ticker, direction):
                    continue

                curr_vol, avg_vol = await bot.loop.run_in_executor(
                    None, _fetch_volume_info, ticker
                )
                volume_spike = (
                    curr_vol / avg_vol
                    if curr_vol and avg_vol and avg_vol > 0
                    else None
                )

                embed = _build_move_embed(
                    ticker=ticker,
                    direction=direction,
                    pct_change=pct_change,
                    current_price=current_price,
                    price_change=price_change,
                    volume_spike=volume_spike,
                )
                await channel.send(embed=embed)
                _set_cooldown(ticker, direction)
            except Exception:
                pass  # Never let one ticker failure abort the whole loop

    @price_monitor.before_loop
    async def before_price_monitor() -> None:
        await bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def news_monitor() -> None:
        """Scan headlines for market-moving news and send Discord alerts."""
        if not als.is_enabled():
            return
        channel_id = _resolve_channel_id()
        if not channel_id:
            return
        channel = bot.get_channel(int(channel_id))
        if not channel:
            return

        for ticker in _get_monitored_tickers():
            try:
                news_items = await bot.loop.run_in_executor(
                    None, _fetch_news, ticker
                )
                for item in news_items:
                    article_id = (
                        item.get("id")
                        or item.get("uuid")
                        or item.get("link", "")
                    )
                    if not article_id or article_id in _seen_news:
                        continue
                    _seen_news.add(article_id)

                    headline = item.get("title") or item.get("headline", "")
                    if not headline:
                        continue

                    sentiment, _matched = _analyze_sentiment(headline)
                    if sentiment == "neutral":
                        continue

                    related = [ticker]
                    for rt in item.get("relatedTickers", []):
                        if rt not in related:
                            related.append(rt)

                    embed = _build_news_embed(
                        headline=headline,
                        tickers=related[:5],
                        sentiment=sentiment,
                    )
                    await channel.send(embed=embed)
                    break  # One news alert per ticker per poll cycle
            except Exception:
                pass
    @price_monitor.before_loop
    async def before_price_monitor() -> None:
        await bot.wait_until_ready()

    @news_monitor.before_loop
    async def before_news_monitor() -> None:
        await bot.wait_until_ready()

    price_monitor.start()
    news_monitor.start()

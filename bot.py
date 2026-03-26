"""
bot.py — Main entry point for the Stock Confidence Predictor Discord Bot.

Commands:
  /predict [TICKER]                   — Analyze a stock and return a prediction
  /quick [TICKER]                     — Quick one-liner prediction
  /watchlist add [TICKER]             — Add a stock to your watchlist
  /watchlist remove [TICKER]          — Remove a stock from your watchlist
  /watchlist show                     — Show all stocks on your watchlist
  /digest                             — Trigger predictions for all watchlist stocks
  /alerts on                          — Enable real-time market alerts in this channel
  /alerts off                         — Disable real-time market alerts
  /alerts status                      — Show current alert settings and monitored tickers
  /alerts add [TICKER]                — Add a ticker to the alert monitor list
  /alerts remove [TICKER]             — Remove a ticker from the alert monitor list
  /setchannel predictions #channel    — Set channel for daily prediction digests
  /setchannel alerts #channel         — Set channel for big move price alerts
  /setchannel news #channel           — Set channel for breaking news alerts
  /setchannel all #channel            — Set ALL alert types to one channel
  /channels                           — Show current channel configuration
"""

from __future__ import annotations

import os

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

import watchlist as wl
from scoring import predict, quick_summary
from scheduler import setup_scheduler
from alerts import setup_alerts
import alert_settings as als
import channel_settings as cs
from high_confidence_alerts import check_high_confidence_alert

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")

# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _direction_emoji(direction: str) -> str:
    return "⬆️" if direction == "UP" else ("⬇️" if direction == "DOWN" else "➡️")


def _build_prediction_embed(result) -> discord.Embed:
    color = (
        discord.Color.green()
        if result.direction == "UP"
        else (
            discord.Color.red()
            if result.direction == "DOWN"
            else discord.Color.yellow()
        )
    )
    embed = discord.Embed(
        title=(
            f"📊 {result.ticker} — Prediction: "
            f"{_direction_emoji(result.direction)} {result.direction}"
        ),
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
        reasons_text = "\n".join(
            f"{i+1}. {r}" for i, r in enumerate(result.reasons)
        )
        embed.add_field(name="Reasons", value=reasons_text, inline=False)
    return embed


# ---------------------------------------------------------------------------
# /predict command
# ---------------------------------------------------------------------------
@tree.command(name="predict", description="Predict short-term stock movement with confidence score")
@app_commands.describe(ticker="Stock ticker symbol (e.g. AAPL, TSLA)")
async def predict_cmd(interaction: discord.Interaction, ticker: str) -> None:
    await interaction.response.defer(thinking=True)
    result = await bot.loop.run_in_executor(None, predict, ticker)
    embed = _build_prediction_embed(result)
    await interaction.followup.send(embed=embed)
    bot.loop.create_task(check_high_confidence_alert(result, bot))


# ---------------------------------------------------------------------------
# /quick command
# ---------------------------------------------------------------------------
@tree.command(name="quick", description="Quick one-liner bullish/bearish prediction")
@app_commands.describe(ticker="Stock ticker symbol (e.g. AAPL, TSLA, NQ=F)")
async def quick_cmd(interaction: discord.Interaction, ticker: str) -> None:
    await interaction.response.defer(thinking=True)
    result = await bot.loop.run_in_executor(None, predict, ticker.upper())
    emoji = "🟢" if result.direction == "UP" else ("🔴" if result.direction == "DOWN" else "🟡")
    summary = quick_summary(result)
    await interaction.followup.send(f"{emoji} **{result.ticker}** — {summary}")
    bot.loop.create_task(check_high_confidence_alert(result, bot))


# ---------------------------------------------------------------------------
# /watchlist command group
# ---------------------------------------------------------------------------
watchlist_group = app_commands.Group(
    name="watchlist", description="Manage your personal stock watchlist"
)


@watchlist_group.command(name="add", description="Add a stock to your watchlist")
@app_commands.describe(ticker="Stock ticker symbol (e.g. AAPL, TSLA)")
async def watchlist_add(interaction: discord.Interaction, ticker: str) -> None:
    ticker = ticker.upper()
    added = wl.add_ticker(interaction.user.id, ticker)
    if added:
        await interaction.response.send_message(
            f"✅ **{ticker}** has been added to your watchlist.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"ℹ️ **{ticker}** is already on your watchlist.", ephemeral=True
        )


@watchlist_group.command(name="remove", description="Remove a stock from your watchlist")
@app_commands.describe(ticker="Stock ticker symbol (e.g. AAPL, TSLA)")
async def watchlist_remove(interaction: discord.Interaction, ticker: str) -> None:
    ticker = ticker.upper()
    removed = wl.remove_ticker(interaction.user.id, ticker)
    if removed:
        await interaction.response.send_message(
            f"🗑️ **{ticker}** has been removed from your watchlist.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"⚠️ **{ticker}** was not found on your watchlist.", ephemeral=True
        )


@watchlist_group.command(name="show", description="Show all stocks on your watchlist")
async def watchlist_show(interaction: discord.Interaction) -> None:
    tickers = wl.get_watchlist(interaction.user.id)
    if not tickers:
        await interaction.response.send_message(
            "📋 Your watchlist is empty. Use `/watchlist add [TICKER]` to add stocks.",
            ephemeral=True,
        )
        return

    ticker_list = "\n".join(f"• {t}" for t in tickers)
    embed = discord.Embed(
        title=f"📋 {interaction.user.display_name}'s Watchlist",
        description=ticker_list,
        color=discord.Color.blue(),
    )
    embed.set_footer(text=f"{len(tickers)} stock(s) on your watchlist")
    await interaction.response.send_message(embed=embed, ephemeral=True)


tree.add_command(watchlist_group)


# ---------------------------------------------------------------------------
# /alerts command group
# ---------------------------------------------------------------------------
alerts_group = app_commands.Group(
    name="alerts", description="Manage real-time market alerts for big moves and news"
)


@alerts_group.command(
    name="on", description="Enable big move alerts in the current channel"
)
async def alerts_on(interaction: discord.Interaction) -> None:
    als.set_enabled(str(interaction.channel_id), True)
    await interaction.response.send_message(
        "✅ Real-time market alerts **enabled** in this channel!\n"
        "You'll be pinged for significant price moves and breaking news.\n"
        "Use `/alerts status` to see what's being monitored.",
        ephemeral=True,
    )


@alerts_group.command(name="off", description="Disable real-time market alerts")
async def alerts_off(interaction: discord.Interaction) -> None:
    als.set_enabled(None, False)
    await interaction.response.send_message(
        "🔕 Real-time market alerts **disabled**.", ephemeral=True
    )


@alerts_group.command(
    name="status",
    description="Show current alert settings and monitored tickers",
)
async def alerts_status(interaction: discord.Interaction) -> None:
    enabled = als.is_enabled()
    channel_id = als.get_channel_id()
    tickers = als.get_monitored_tickers()

    status_emoji = "✅" if enabled else "❌"
    channel_str = f"<#{channel_id}>" if channel_id else "Not set"
    ticker_list = ", ".join(f"`{t}`" for t in tickers) if tickers else "None"

    embed = discord.Embed(
        title="🔔 Alert System Status",
        color=discord.Color.green() if enabled else discord.Color.red(),
    )
    embed.add_field(
        name="Status",
        value=f"{status_emoji} {'Enabled' if enabled else 'Disabled'}",
        inline=True,
    )
    embed.add_field(name="Alert Channel", value=channel_str, inline=True)
    embed.add_field(name="Monitored Tickers", value=ticker_list, inline=False)
    embed.add_field(
        name="Alert Thresholds",
        value=(
            "⚠️ Notable: ±0.5% in 5 min\n"
            "🚨 Big: ±1.0% in 5 min\n"
            "🔴 Extreme: ±2.0% in 5 min"
        ),
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@alerts_group.command(
    name="add", description="Add a ticker to the alert monitor list"
)
@app_commands.describe(ticker="Stock or futures ticker to monitor (e.g. AAPL, NQ=F)")
async def alerts_add(interaction: discord.Interaction, ticker: str) -> None:
    ticker = ticker.upper()
    added = als.add_ticker(ticker)
    if added:
        await interaction.response.send_message(
            f"✅ **{ticker}** added to the alert monitor list.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"ℹ️ **{ticker}** is already being monitored.", ephemeral=True
        )


@alerts_group.command(
    name="remove", description="Remove a ticker from the alert monitor list"
)
@app_commands.describe(ticker="Ticker to stop monitoring")
async def alerts_remove(interaction: discord.Interaction, ticker: str) -> None:
    ticker = ticker.upper()
    removed = als.remove_ticker(ticker)
    if removed:
        await interaction.response.send_message(
            f"🗑️ **{ticker}** removed from the alert monitor list.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"⚠️ **{ticker}** was not found in the monitor list.", ephemeral=True
        )


tree.add_command(alerts_group)


# ---------------------------------------------------------------------------
# /setchannel command group
# ---------------------------------------------------------------------------
setchannel_group = app_commands.Group(
    name="setchannel", description="Configure which channels receive bot updates"
)


@setchannel_group.command(
    name="predictions", description="Set the channel for daily prediction digests"
)
@app_commands.describe(channel="The channel to send daily prediction digests to")
@app_commands.checks.has_permissions(manage_channels=True)
async def setchannel_predictions(
    interaction: discord.Interaction, channel: discord.TextChannel
) -> None:
    cs.set_predictions_channel(channel.id)
    await interaction.response.send_message(
        f"✅ Daily predictions will now be sent to {channel.mention}",
        ephemeral=True,
    )


@setchannel_group.command(
    name="alerts", description="Set the channel for big move price alerts"
)
@app_commands.describe(channel="The channel to send big move price alerts to")
@app_commands.checks.has_permissions(manage_channels=True)
async def setchannel_alerts(
    interaction: discord.Interaction, channel: discord.TextChannel
) -> None:
    cs.set_alerts_channel(channel.id)
    await interaction.response.send_message(
        f"✅ Big move alerts will now be sent to {channel.mention}",
        ephemeral=True,
    )


@setchannel_group.command(
    name="news", description="Set the channel for breaking news alerts"
)
@app_commands.describe(channel="The channel to send breaking news alerts to")
@app_commands.checks.has_permissions(manage_channels=True)
async def setchannel_news(
    interaction: discord.Interaction, channel: discord.TextChannel
) -> None:
    cs.set_news_channel(channel.id)
    await interaction.response.send_message(
        f"✅ Breaking news alerts will now be sent to {channel.mention}",
        ephemeral=True,
    )


@setchannel_group.command(
    name="all", description="Set ALL alert types to one channel"
)
@app_commands.describe(channel="The channel to send all bot updates to")
@app_commands.checks.has_permissions(manage_channels=True)
async def setchannel_all(
    interaction: discord.Interaction, channel: discord.TextChannel
) -> None:
    cs.set_all_channels(channel.id)
    await interaction.response.send_message(
        f"✅ All bot updates (predictions, alerts, news) will now be sent to {channel.mention}",
        ephemeral=True,
    )


tree.add_command(setchannel_group)


# ---------------------------------------------------------------------------
# /channels command
# ---------------------------------------------------------------------------
@tree.command(name="channels", description="Show current channel configuration")
async def channels_cmd(interaction: discord.Interaction) -> None:
    settings = cs.get_all_settings()
    fallback = "Not configured (using default)"

    def _channel_str(channel_id: int | None) -> str:
        return f"<#{channel_id}>" if channel_id else fallback

    predictions_str = _channel_str(settings.get("predictions_channel_id"))
    alerts_str = _channel_str(settings.get("alerts_channel_id"))
    news_str = _channel_str(settings.get("news_channel_id"))

    embed = discord.Embed(title="📺 Channel Configuration", color=discord.Color.blue())
    embed.add_field(name="📊 Daily Predictions", value=predictions_str, inline=False)
    embed.add_field(name="🚨 Big Move Alerts", value=alerts_str, inline=False)
    embed.add_field(name="📰 Breaking News", value=news_str, inline=False)
    embed.add_field(
        name="💡 Quick checks",
        value="Just use `/quick` or `/predict` in any channel!",
        inline=False,
    )
    embed.set_footer(text="Use /setchannel to change these settings.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------------------------
# /digest command
# ---------------------------------------------------------------------------
@tree.command(
    name="digest",
    description="Get predictions for all stocks on your watchlist",
)
async def digest_cmd(interaction: discord.Interaction) -> None:
    tickers = wl.get_watchlist(interaction.user.id)
    if not tickers:
        await interaction.response.send_message(
            "📋 Your watchlist is empty. Use `/watchlist add [TICKER]` to add stocks first.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(thinking=True)
    embeds = []
    for ticker in tickers:
        result = await bot.loop.run_in_executor(None, predict, ticker)
        embeds.append(_build_prediction_embed(result))
        bot.loop.create_task(check_high_confidence_alert(result, bot))

    # Discord allows up to 10 embeds per message; send in batches if needed
    batch_size = 10
    first = True
    for i in range(0, len(embeds), batch_size):
        batch = embeds[i : i + batch_size]
        if first:
            await interaction.followup.send(
                f"📈 **Digest** — Predictions for your {len(tickers)} watchlist stock(s):",
                embeds=batch,
            )
            first = False
        else:
            await interaction.followup.send(embeds=batch)


# ---------------------------------------------------------------------------
# Bot events
# ---------------------------------------------------------------------------
@bot.event
async def on_ready() -> None:
    await tree.sync()
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"   Slash commands synced globally.")
    setup_scheduler(bot)
    setup_alerts(bot)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN is not set. Create a .env file based on .env.example."
        )
    bot.run(DISCORD_TOKEN)

# 📊 Stock Confidence Predictor Discord Bot

A Discord bot that predicts short-term stock movement (up/down) with a confidence score for the **3:15 PM – 5:30 PM EST** trading window.

---

## Features

- **`/predict [TICKER]`** — Instant prediction with confidence score and detailed reasons
- **`/watchlist add/remove/show`** — Manage your personal stock watchlist
- **`/digest`** — Manually trigger predictions for all your watchlist stocks
- **Morning Digest (9:00 AM EST)** — Daily pre-market overview sent to your channel
- **Afternoon Alert (3:15 PM EST)** — Full predictions for the afternoon trading window
- Weighted scoring engine: momentum, moving averages, volatility, and news sentiment
- No paid API keys required — uses `yfinance` for free stock data

---

## Setup

### 1. Create a Discord Bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Click **New Application** → give it a name → click **Create**
3. Click the **Bot** tab in the left sidebar
4. Click **Reset Token** → copy the token (keep it secret!)
5. Under **Privileged Gateway Intents**, enable:
   - ✅ Message Content Intent

### 2. Invite the Bot to Your Server

1. In your application, click **OAuth2** → **URL Generator**
2. Under **Scopes**, check: `bot` and `applications.commands`
3. Under **Bot Permissions**, check: `Send Messages`, `Embed Links`
4. Copy the generated URL, paste it in your browser, select your server, and click **Authorize**

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

Requires **Python 3.10+**.

### 4. Configure the `.env` File

```bash
cp .env.example .env
```

Edit `.env` and fill in your values:

```env
DISCORD_TOKEN=your_bot_token_here
DISCORD_CHANNEL_ID=your_channel_id_here
```

To get your **Channel ID**:
1. In Discord, go to **User Settings → Advanced → enable Developer Mode**
2. Right-click the channel where you want daily digests
3. Click **Copy Channel ID**

### 5. Run the Bot

```bash
python bot.py
```

The bot will log in, sync slash commands globally, and start the scheduler. You should see:

```
✅ Logged in as YourBot#1234 (ID: 123456789)
   Slash commands synced globally.
```

---

## Commands

| Command | Description | Example |
|---|---|---|
| `/predict TICKER` | Predict stock movement with confidence score | `/predict AAPL` |
| `/watchlist add TICKER` | Add a stock to your watchlist | `/watchlist add TSLA` |
| `/watchlist remove TICKER` | Remove a stock from your watchlist | `/watchlist remove TSLA` |
| `/watchlist show` | Display all stocks on your watchlist | `/watchlist show` |
| `/digest` | Get predictions for all watchlist stocks | `/digest` |

---

## Prediction Output

Each prediction is a rich embed like this:

```
📊 AAPL — Prediction: ⬆️ UP
🔒 Confidence: 72% (Moderate-High)
📅 Window: 3:15 PM – 5:30 PM EST

Reasons:
1. 1-day momentum: +1.2% (bullish)
2. 5-day trend: +3.1% (bullish)
3. Price vs 20-day MA: +2.3% (above MA at $178.40) — bullish
4. Volatility (ATR): 1.4% of price — moderate-low
5. News sentiment: neutral-positive
```

### Confidence Levels

| Range | Label |
|---|---|
| 0–30% | Low |
| 31–50% | Moderate-Low |
| 51–70% | Moderate |
| 71–85% | Moderate-High |
| 86–100% | High |

---

## How the Scoring Engine Works

The prediction uses a **weighted composite score** (0 = fully bearish, 1 = fully bullish):

| Factor | Weight | Logic |
|---|---|---|
| **1-Day Momentum** | 25% | % price change last trading day |
| **5-Day Momentum** | 20% | % price change over 5 trading days |
| **20-Day Momentum** | 15% | Longer-term trend direction |
| **Price vs 20-Day MA** | 20% | Above MA = bullish (0.7), below = bearish (0.3) |
| **Volatility (ATR)** | 10% | Low ATR = higher confidence; high ATR = lower |
| **News Sentiment** | 10% | Keyword analysis of recent news headlines |

**Final score interpretation:**
- Score > 0.52 → **UP** prediction, confidence = score × 100%
- Score < 0.48 → **DOWN** prediction, confidence = (1 − score) × 100%
- 0.48–0.52 → **NEUTRAL** with low confidence

---

## File Structure

```
bot.py            # Main bot — slash commands, startup, scheduler setup
scoring.py        # Weighted scoring engine
scheduler.py      # Automatic daily digests
watchlist.py      # JSON-based per-user watchlist management
requirements.txt  # Python dependencies
.env.example      # Environment variable template
.gitignore        # Ignores .env, __pycache__, watchlists.json
README.md         # This file
```

---

## Notes

- Watchlists are stored locally in `watchlists.json` (auto-created on first use)
- The scheduler fires once per day at the configured times; if the bot restarts, it will wait until the next scheduled time
- Slash commands may take up to 1 hour to appear globally after the first sync
- For faster command registration during development, use guild-specific sync (see Discord docs)
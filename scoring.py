"""
scoring.py — Weighted scoring engine for stock movement prediction.

Factors and weights:
  - 1-day momentum      25%
  - 5-day momentum      20%
  - 20-day momentum     15%
  - Price vs 20-day MA  20%
  - Volatility (ATR)    10%
  - News sentiment      10%
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yfinance as yf

# ---------------------------------------------------------------------------
# Sentiment word lists
# ---------------------------------------------------------------------------
POSITIVE_WORDS = {
    "surge", "surges", "surging", "jump", "jumps", "jumping", "gain", "gains",
    "rally", "rallies", "rallying", "rise", "rises", "rising", "beat", "beats",
    "record", "high", "upgrade", "upgraded", "buy", "bullish", "profit",
    "growth", "outperform", "strong", "strength", "positive", "boost", "boosted",
    "exceeds", "exceed", "exceeded", "top", "tops", "soar", "soars", "soaring",
    "revenue", "earnings", "up", "advances", "advance", "higher",
}

NEGATIVE_WORDS = {
    "fall", "falls", "falling", "drop", "drops", "dropping", "decline",
    "declines", "declining", "plunge", "plunges", "plunging", "loss", "losses",
    "miss", "misses", "missed", "downgrade", "downgraded", "sell", "bearish",
    "weak", "weakness", "negative", "cut", "cuts", "lower", "below",
    "concern", "concerns", "risk", "risks", "warning", "warn", "warns",
    "down", "retreats", "retreat", "slump", "slumps", "slumping", "crash",
    "shrink", "shrinks", "shrinking",
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------
@dataclass
class PredictionResult:
    ticker: str
    direction: str          # "UP", "DOWN", or "NEUTRAL"
    confidence: float       # 0–100
    confidence_label: str   # "Low", "Moderate-Low", etc.
    up_probability: float = 0.0    # 0–100, probability of moving UP by 3 PM EST
    down_probability: float = 0.0  # 0–100, probability of moving DOWN by 3 PM EST
    reasons: list[str] = field(default_factory=list)
    error: str | None = None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def _confidence_label(confidence: float) -> str:
    if confidence <= 30:
        return "Low"
    elif confidence <= 50:
        return "Moderate-Low"
    elif confidence <= 70:
        return "Moderate"
    elif confidence <= 85:
        return "Moderate-High"
    else:
        return "High"


def _momentum_score(pct_change: float) -> float:
    """Map % change to a 0–1 score. ±5% maps to roughly 0/1."""
    clamped = max(-5.0, min(5.0, pct_change))
    return (clamped + 5.0) / 10.0


def _volatility_score(atr: float, price: float) -> float:
    """
    ATR as % of price: low ATR → high score (more predictable).
    <1% → ~0.8, >4% → ~0.2
    """
    if price == 0:
        return 0.5
    atr_pct = (atr / price) * 100
    if atr_pct < 1:
        return 0.8
    elif atr_pct < 2:
        return 0.65
    elif atr_pct < 3:
        return 0.5
    elif atr_pct < 4:
        return 0.35
    else:
        return 0.2


def _sentiment_score(ticker: str) -> tuple[float, str]:
    """
    Fetch news from yfinance and do keyword-based sentiment.
    Returns (score 0–1, description string).
    """
    try:
        stock = yf.Ticker(ticker)
        news = stock.news or []
        if not news:
            return 0.5, "neutral (no recent news)"

        pos = 0
        neg = 0
        for item in news[:10]:
            title = item.get("title", "") or ""
            words = set(re.findall(r"[a-zA-Z]+", title.lower()))
            pos += len(words & POSITIVE_WORDS)
            neg += len(words & NEGATIVE_WORDS)

        total = pos + neg
        if total == 0:
            return 0.5, "neutral (no sentiment signals)"

        ratio = pos / total  # 0 = all negative, 1 = all positive
        if ratio >= 0.7:
            label = "positive"
        elif ratio >= 0.55:
            label = "neutral-positive"
        elif ratio >= 0.45:
            label = "neutral"
        elif ratio >= 0.3:
            label = "neutral-negative"
        else:
            label = "negative"

        return ratio, label
    except Exception:
        return 0.5, "neutral (data unavailable)"


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------
def predict(ticker: str) -> PredictionResult:
    ticker = ticker.upper()
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="30d")

        if hist.empty or len(hist) < 6:
            return PredictionResult(
                ticker=ticker,
                direction="NEUTRAL",
                confidence=0.0,
                confidence_label="Low",
                error="Insufficient historical data. Check the ticker symbol.",
            )

        closes = hist["Close"].values
        highs = hist["High"].values
        lows = hist["Low"].values

        current_price = float(closes[-1])

        # ---- 1-day momentum -----------------------------------------------
        day1_pct = ((closes[-1] - closes[-2]) / closes[-2]) * 100
        s1 = _momentum_score(day1_pct)
        direction_1d = "bullish" if day1_pct > 0 else "bearish"
        reasons_1d = f"1-day momentum: {day1_pct:+.2f}% ({direction_1d})"

        # ---- 5-day momentum -----------------------------------------------
        if len(closes) >= 6:
            day5_pct = ((closes[-1] - closes[-6]) / closes[-6]) * 100
        else:
            day5_pct = day1_pct
        s5 = _momentum_score(day5_pct)
        direction_5d = "bullish" if day5_pct > 0 else "bearish"
        reasons_5d = f"5-day trend: {day5_pct:+.2f}% ({direction_5d})"

        # ---- 20-day momentum ----------------------------------------------
        if len(closes) >= 21:
            day20_pct = ((closes[-1] - closes[-21]) / closes[-21]) * 100
        elif len(closes) >= 2:
            day20_pct = ((closes[-1] - closes[0]) / closes[0]) * 100
        else:
            day20_pct = 0.0
        s20 = _momentum_score(day20_pct)
        direction_20d = "bullish" if day20_pct > 0 else "bearish"
        reasons_20d = f"20-day momentum: {day20_pct:+.2f}% ({direction_20d})"

        # ---- Price vs 20-day MA -------------------------------------------
        ma20 = float(closes[-20:].mean()) if len(closes) >= 20 else float(closes.mean())
        above_ma = current_price > ma20
        s_ma = 0.7 if above_ma else 0.3
        ma_pct_diff = ((current_price - ma20) / ma20) * 100
        ma_label = "above" if above_ma else "below"
        reasons_ma = (
            f"Price vs 20-day MA: {ma_pct_diff:+.1f}% "
            f"({ma_label} MA at ${ma20:.2f}) — {'bullish' if above_ma else 'bearish'}"
        )

        # ---- ATR volatility -----------------------------------------------
        n = min(14, len(closes) - 1)
        true_ranges = []
        for i in range(-n, 0):
            high = float(highs[i])
            low = float(lows[i])
            prev_close = float(closes[i - 1])
            true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        atr = sum(true_ranges) / len(true_ranges) if true_ranges else 0.0
        s_vol = _volatility_score(atr, current_price)
        atr_pct = (atr / current_price * 100) if current_price else 0
        if atr_pct < 1:
            vol_label = "low (stable, supports trend continuation)"
        elif atr_pct < 2:
            vol_label = "moderate-low"
        elif atr_pct < 3:
            vol_label = "moderate (some uncertainty)"
        else:
            vol_label = "high (less predictable)"
        reasons_vol = f"Volatility (ATR): {atr_pct:.1f}% of price — {vol_label}"

        # ---- News sentiment -----------------------------------------------
        s_news, news_label = _sentiment_score(ticker)
        reasons_news = f"News sentiment: {news_label}"

        # ---- Weighted composite score -------------------------------------
        weights = {
            "1d": 0.25,
            "5d": 0.20,
            "20d": 0.15,
            "ma": 0.20,
            "vol": 0.10,
            "news": 0.10,
        }
        composite = (
            s1 * weights["1d"]
            + s5 * weights["5d"]
            + s20 * weights["20d"]
            + s_ma * weights["ma"]
            + s_vol * weights["vol"]
            + s_news * weights["news"]
        )

        # ---- Direction and confidence -------------------------------------
        if composite > 0.52:
            direction = "UP"
            confidence = round(composite * 100, 1)
        elif composite < 0.48:
            direction = "DOWN"
            confidence = round((1.0 - composite) * 100, 1)
        else:
            direction = "NEUTRAL"
            confidence = round(abs(composite - 0.5) * 200, 1)

        confidence = max(0.0, min(100.0, confidence))
        label = _confidence_label(confidence)

        # ---- UP / DOWN probabilities -------------------------------------
        up_probability = round(composite * 100, 1)
        down_probability = round((1.0 - composite) * 100, 1)

        return PredictionResult(
            ticker=ticker,
            direction=direction,
            confidence=confidence,
            confidence_label=label,
            up_probability=up_probability,
            down_probability=down_probability,
            reasons=[reasons_1d, reasons_5d, reasons_20d, reasons_ma, reasons_vol, reasons_news],
        )

    except Exception as exc:
        return PredictionResult(
            ticker=ticker,
            direction="NEUTRAL",
            confidence=0.0,
            confidence_label="Low",
            error=f"Error fetching data: {exc}",
        )


# ---------------------------------------------------------------------------
# Quick summary helper
# ---------------------------------------------------------------------------
def quick_summary(result: PredictionResult) -> str:
    """
    Generate a short one-liner summary from a PredictionResult.

    Returns something like:
      "BULLISH (72%) — up +1.2% today, riding above its average, good news"
    The language is intentionally simple and casual so anyone can understand.
    """
    if result.error:
        return "N/A — data unavailable"

    direction_word = {
        "UP": "BULLISH",
        "DOWN": "BEARISH",
        "NEUTRAL": "NEUTRAL",
    }.get(result.direction, "NEUTRAL")

    snippets: list[str] = []
    reasons = result.reasons  # 6 elements when no error

    # ---- 1-day momentum (reasons[0]): "1-day momentum: +1.2% (bullish)" ----
    if len(reasons) > 0:
        m = re.search(r"([+-]\d+\.\d+)%", reasons[0])
        if m:
            pct = float(m.group(1))
            if abs(pct) >= 0.3:
                if pct > 0:
                    snippets.append(f"up {abs(pct):.1f}% today")
                else:
                    snippets.append(f"down {abs(pct):.1f}% today")

    # ---- 5-day trend (reasons[1]): "5-day trend: +3.4% (bullish)" ----------
    if len(reasons) > 1:
        m = re.search(r"([+-]\d+\.\d+)%", reasons[1])
        if m:
            pct = float(m.group(1))
            if abs(pct) >= 1.0:
                if pct > 0:
                    snippets.append(f"been climbing {abs(pct):.1f}% this week")
                else:
                    snippets.append(f"been dropping {abs(pct):.1f}% this week")

    # ---- MA position (reasons[3]): "Price vs 20-day MA: ... above/below MA" -
    if len(reasons) > 3:
        if "above" in reasons[3]:
            snippets.append("riding above its average price")
        elif "below" in reasons[3]:
            snippets.append("sitting below its average price")

    # ---- Volatility (reasons[4]): only flag if notably high ----------------
    if len(reasons) > 4:
        if "high" in reasons[4]:
            snippets.append("very choppy right now")

    # ---- News sentiment (reasons[5]): "News sentiment: positive/negative" --
    if len(reasons) > 5:
        news_r = reasons[5]
        if "positive" in news_r and "neutral" not in news_r:
            snippets.append("good news out there")
        elif "negative" in news_r and "neutral" not in news_r:
            snippets.append("bad news just dropped")

    top_snippets = snippets[:3]
    reason_str = ", ".join(top_snippets) if top_snippets else "mixed signals, unclear direction"

    return f"{direction_word} ({int(result.confidence)}%) — {reason_str}"

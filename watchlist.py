import json
import os

WATCHLIST_FILE = "watchlists.json"


def _load() -> dict:
    if not os.path.exists(WATCHLIST_FILE):
        return {}
    try:
        with open(WATCHLIST_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(data, f, indent=2)


def add_ticker(user_id: int, ticker: str) -> bool:
    """Add a ticker to a user's watchlist. Returns True if added, False if already present."""
    data = _load()
    key = str(user_id)
    ticker = ticker.upper()
    if key not in data:
        data[key] = []
    if ticker in data[key]:
        return False
    data[key].append(ticker)
    _save(data)
    return True


def remove_ticker(user_id: int, ticker: str) -> bool:
    """Remove a ticker from a user's watchlist. Returns True if removed, False if not found."""
    data = _load()
    key = str(user_id)
    ticker = ticker.upper()
    if key not in data or ticker not in data[key]:
        return False
    data[key].remove(ticker)
    _save(data)
    return True


def get_watchlist(user_id: int) -> list[str]:
    """Return the list of tickers for a user."""
    data = _load()
    return data.get(str(user_id), [])


def get_all_tickers() -> list[str]:
    """Return a deduplicated list of all tickers across all users."""
    data = _load()
    all_tickers: set[str] = set()
    for tickers in data.values():
        all_tickers.update(tickers)
    return sorted(all_tickers)

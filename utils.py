"""
utils.py — Shared utilities for all portfolio bots
====================================================
Market check, Finnhub helpers, Telegram sender.
"""

import os
import json
import requests
from datetime import datetime, timedelta
import pytz

ET = pytz.timezone("America/New_York")

FINNHUB_API_KEY   = os.environ.get("FINNHUB_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "")
ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"  # Paper only — never Live

# ── Market day check ────────────────────────────────────────────────────────
def is_market_day() -> bool:
    """Returns True if NYSE is open today (not weekend, not full holiday)."""
    today   = datetime.now(ET).date().isoformat()
    weekday = datetime.now(ET).weekday()
    if weekday >= 5:
        print(f"Weekend — skipping.")
        return False
    try:
        url = f"https://finnhub.io/api/v1/stock/market-holiday?exchange=US&token={FINNHUB_API_KEY}"
        r   = requests.get(url, timeout=10)
        r.raise_for_status()
        for h in r.json().get("data", []):
            if h.get("atDate") == today and h.get("tradingHour", "") == "":
                print(f"NYSE holiday ({h.get('eventName')}) — skipping.")
                return False
    except Exception as e:
        print(f"Holiday check failed ({e}) — assuming open.")
    return True

# ── Finnhub ─────────────────────────────────────────────────────────────────
def get_quote(ticker: str) -> dict:
    url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_API_KEY}"
    r   = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()

def get_news(ticker: str, days: int = 1) -> list:
    today     = datetime.now(ET).date()
    from_date = (today - timedelta(days=days)).isoformat()
    to_date   = today.isoformat()
    url = (
        f"https://finnhub.io/api/v1/company-news?symbol={ticker}"
        f"&from={from_date}&to={to_date}&token={FINNHUB_API_KEY}"
    )
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return [
        {"headline": i.get("headline", ""), "source": i.get("source", "")}
        for i in r.json()[:3]
    ]

def fetch_all_quotes(portfolio: list, entry_prices: dict) -> list:
    results = []
    for pos in portfolio:
        ticker = pos["ticker"]
        try:
            q       = get_quote(ticker)
            price   = q.get("c", 0)
            prev    = q.get("pc", 0)
            chg_pct = ((price - prev) / prev * 100) if prev else 0
            entry   = entry_prices.get(ticker)
            stop_alert = False
            if entry:
                stop_alert = ((price - entry) / entry) <= -pos["stop_loss_pct"]
            results.append({
                "ticker":     ticker,
                "sector":     pos["sector"],
                "weight_pct": round(pos["weight"] * 100),
                "price":      round(price, 2),
                "chg_pct":    round(chg_pct, 2),
                "high":       round(q.get("h", 0), 2),
                "low":        round(q.get("l", 0), 2),
                "stop_alert": stop_alert,
                "entry":      entry,
                "stop_level": round(entry * (1 - pos["stop_loss_pct"]), 2) if entry else None,
            })
        except Exception as e:
            results.append({"ticker": ticker, "error": str(e), "alert_reasons": ["API_ERROR"]})
    return results

# ── Alpaca Paper ────────────────────────────────────────────────────────────
def _alpaca_headers() -> dict:
    return {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }

def fetch_alpaca_account() -> dict:
    """Return paper account summary: equity, cash, P&L today, portfolio value."""
    r = requests.get(
        f"{ALPACA_BASE_URL}/v2/account",
        headers=_alpaca_headers(),
        timeout=10,
    )
    r.raise_for_status()
    a = r.json()
    equity       = float(a.get("equity", 0))
    last_eq      = float(a.get("last_equity", 0))
    pl_today     = equity - last_eq
    pl_today_pct = (pl_today / last_eq * 100) if last_eq else 0
    return {
        "equity":          round(equity, 2),
        "cash":            round(float(a.get("cash", 0)), 2),
        "portfolio_value": round(float(a.get("portfolio_value", equity)), 2),
        "pl_today":        round(pl_today, 2),
        "pl_today_pct":    round(pl_today_pct, 2),
        "buying_power":    round(float(a.get("buying_power", 0)), 2),
    }

def fetch_alpaca_positions() -> list:
    """Return open positions with P&L per position."""
    r = requests.get(
        f"{ALPACA_BASE_URL}/v2/positions",
        headers=_alpaca_headers(),
        timeout=10,
    )
    r.raise_for_status()
    positions = []
    for p in r.json():
        positions.append({
            "ticker":        p.get("symbol", ""),
            "qty":           float(p.get("qty", 0)),
            "avg_entry":     round(float(p.get("avg_entry_price", 0)), 2),
            "current_price": round(float(p.get("current_price", 0)), 2),
            "market_value":  round(float(p.get("market_value", 0)), 2),
            "pl_total":      round(float(p.get("unrealized_pl", 0)), 2),
            "pl_total_pct":  round(float(p.get("unrealized_plpc", 0)) * 100, 2),
            "pl_today":      round(float(p.get("unrealized_intraday_pl", 0)), 2),
            "pl_today_pct":  round(float(p.get("unrealized_intraday_plpc", 0)) * 100, 2),
        })
    return positions

def place_market_order(ticker: str, qty: float, side: str) -> dict:
    """
    Place a paper market order.
    side: 'buy' or 'sell' — qty: shares (fractional supported)
    """
    r = requests.post(
        f"{ALPACA_BASE_URL}/v2/orders",
        headers=_alpaca_headers(),
        json={
            "symbol":        ticker,
            "qty":           str(qty),
            "side":          side,
            "type":          "market",
            "time_in_force": "day",
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json()

# ── Claude ──────────────────────────────────────────────────────────────────
def call_claude(system_prompt: str, user_content: str, max_tokens: int = 500) -> str:
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key":         ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
        },
        json={
            "model":    "claude-sonnet-4-6",
            "max_tokens": max_tokens,
            "system":   system_prompt,
            "messages": [{"role": "user", "content": user_content}],
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["content"][0]["text"]

# ── Telegram ─────────────────────────────────────────────────────────────────
def send_telegram(text: str, reply_markup: dict = None):
    """Send a plain message, optionally with inline keyboard."""
    payload = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       text,
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    r = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json=payload,
        timeout=10,
    )
    r.raise_for_status()

def answer_callback(callback_query_id: str, text: str = ""):
    """Acknowledge a button press so the loading spinner disappears."""
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
        json={"callback_query_id": callback_query_id, "text": text},
        timeout=10,
    )

def edit_message(chat_id: str, message_id: str, new_text: str):
    """Edit an existing message (used to update after button press)."""
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText",
        json={
            "chat_id":    chat_id,
            "message_id": message_id,
            "text":       new_text,
            "parse_mode": "HTML",
        },
        timeout=10,
    )

# ── Session label ────────────────────────────────────────────────────────────
def session_label() -> str:
    h = datetime.now(ET).hour
    if h < 10:   return "PRE-MARKET"
    elif h < 13: return "MID-SESSION"
    else:        return "PRE-CLOSE"

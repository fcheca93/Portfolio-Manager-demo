"""
alpaca_client.py — Alpaca Paper Trading client
================================================
Provides a single REST client instance used by all bots.
Paper trading endpoint — safe for testing, no real money.
"""

import os
import alpaca_trade_api as tradeapi

ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"  # Paper, nunca Live

def get_client() -> tradeapi.REST:
    """Return an authenticated Alpaca REST client."""
    return tradeapi.REST(
        key_id     = ALPACA_API_KEY,
        secret_key = ALPACA_SECRET_KEY,
        base_url   = ALPACA_BASE_URL,
    )

def get_account():
    """Return account info — útil para verificar conexión."""
    return get_client().get_account()

def get_positions():
    """Return all open positions in the paper account."""
    return get_client().list_positions()

def get_position(ticker: str):
    """Return position for a single ticker, or None if not held."""
    try:
        return get_client().get_position(ticker)
    except Exception:
        return None

def place_market_order(ticker: str, qty: float, side: str) -> dict:
    """
    Place a market order.
    side: 'buy' or 'sell'
    qty: number of shares (fractional supported)
    Returns order dict or raises on error.
    """
    api = get_client()
    order = api.submit_order(
        symbol        = ticker,
        qty           = qty,
        side          = side,
        type          = "market",
        time_in_force = "day",
    )
    return order._raw

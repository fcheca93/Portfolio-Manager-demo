"""
sync_positions.py — One-time position sync for Frontier5 v2.0
==============================================================
Run ONCE to open all 5 positions in Alpaca paper at current market prices.
P&L will be tracked from today forward.

Usage:
  ALPACA_API_KEY=... ALPACA_SECRET_KEY=... python sync_positions.py

Or just run it from GitHub Actions / Render shell with env vars already set.

Safety checks:
  - Confirms paper endpoint (never Live)
  - Checks for existing positions to avoid doubles
  - Prints a summary before placing orders (dry-run first)
  - Asks for confirmation before executing
"""

import os
import sys
import requests

# ── Config ────────────────────────────────────────────────────────────────────
ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"  # PAPER ONLY

INITIAL_CAPITAL = 10_000.00

PORTFOLIO = [
    {"ticker": "NVDA", "weight": 0.25},
    {"ticker": "PLTR", "weight": 0.25},
    {"ticker": "RTX",  "weight": 0.22},
    {"ticker": "META", "weight": 0.18},
    {"ticker": "XOM",  "weight": 0.10},
]

def headers():
    return {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }

def get_account():
    r = requests.get(f"{ALPACA_BASE_URL}/v2/account", headers=headers(), timeout=10)
    r.raise_for_status()
    return r.json()

def get_existing_positions():
    r = requests.get(f"{ALPACA_BASE_URL}/v2/positions", headers=headers(), timeout=10)
    r.raise_for_status()
    return {p["symbol"]: p for p in r.json()}

def get_latest_price(ticker: str) -> float:
    """Get latest trade price from Alpaca."""
    r = requests.get(
        f"https://data.alpaca.markets/v2/stocks/{ticker}/trades/latest",
        headers=headers(),
        timeout=10,
    )
    r.raise_for_status()
    return float(r.json()["trade"]["p"])

def place_order(ticker: str, notional: float) -> dict:
    """Place a market order using notional (dollar amount) instead of shares."""
    r = requests.post(
        f"{ALPACA_BASE_URL}/v2/orders",
        headers=headers(),
        json={
            "symbol":        ticker,
            "notional":      str(round(notional, 2)),  # dollar amount
            "side":          "buy",
            "type":          "market",
            "time_in_force": "day",
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json()

def main():
    # ── Safety checks ─────────────────────────────────────────────────────────
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        print("ERROR: ALPACA_API_KEY and ALPACA_SECRET_KEY must be set as env vars.")
        sys.exit(1)

    print("=" * 55)
    print("  Frontier5 v2.0 — Alpaca Paper Position Sync")
    print("=" * 55)
    print(f"  Endpoint: {ALPACA_BASE_URL}")
    print(f"  Capital:  ${INITIAL_CAPITAL:,.2f}")
    print()

    # Verify account
    try:
        account = get_account()
        equity  = float(account["equity"])
        status  = account["status"]
        print(f"  Account status : {status}")
        print(f"  Current equity : ${equity:,.2f}")
        print(f"  Buying power   : ${float(account['buying_power']):,.2f}")
    except Exception as e:
        print(f"ERROR connecting to Alpaca: {e}")
        sys.exit(1)

    if status != "ACTIVE":
        print(f"ERROR: Account status is '{status}', expected ACTIVE.")
        sys.exit(1)

    # Check for existing positions
    existing = get_existing_positions()
    if existing:
        print()
        print("  ⚠️  Existing positions detected:")
        for sym, p in existing.items():
            print(f"     {sym}: {p['qty']} shares @ ${float(p['avg_entry_price']):.2f}")
        print()
        overlap = [p["ticker"] for p in PORTFOLIO if p["ticker"] in existing]
        if overlap:
            print(f"  ⚠️  Overlap with Frontier5: {overlap}")
            print("  Skipping those tickers to avoid doubling up.")
            print()

    # ── Dry run — show what will be ordered ──────────────────────────────────
    print("  Orders to be placed:")
    print(f"  {'Ticker':<6} {'Weight':>6}  {'Notional':>10}")
    print("  " + "-" * 28)

    to_order = []
    for pos in PORTFOLIO:
        ticker   = pos["ticker"]
        notional = INITIAL_CAPITAL * pos["weight"]
        if ticker in existing:
            print(f"  {ticker:<6} {pos['weight']*100:>5.0f}%  {'SKIP (exists)':>10}")
        else:
            print(f"  {ticker:<6} {pos['weight']*100:>5.0f}%  ${notional:>9,.2f}")
            to_order.append({"ticker": ticker, "notional": notional})

    if not to_order:
        print()
        print("  All positions already exist — nothing to do.")
        sys.exit(0)

    print()
    print(f"  Total to invest: ${sum(o['notional'] for o in to_order):,.2f}")
    print()

    # ── Confirmation ──────────────────────────────────────────────────────────
    confirm = input("  Confirm placing these orders? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("  Aborted — no orders placed.")
        sys.exit(0)

    # ── Place orders ──────────────────────────────────────────────────────────
    print()
    print("  Placing orders...")
    results = []
    for o in to_order:
        try:
            order = place_order(o["ticker"], o["notional"])
            order_id = order.get("id", "?")[:8]
            print(f"  ✅ {o['ticker']:<6} — order {order_id}... submitted")
            results.append({"ticker": o["ticker"], "status": "ok", "order_id": order_id})
        except Exception as e:
            print(f"  ❌ {o['ticker']:<6} — ERROR: {e}")
            results.append({"ticker": o["ticker"], "status": "error", "error": str(e)})

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    ok  = [r for r in results if r["status"] == "ok"]
    err = [r for r in results if r["status"] == "error"]
    print(f"  Done — {len(ok)}/{len(results)} orders placed successfully.")
    if err:
        print(f"  Failed: {[r['ticker'] for r in err]}")
    print()
    print("  Next: check /api/positions on your Render app to confirm sync.")
    print("=" * 55)

if __name__ == "__main__":
    main()

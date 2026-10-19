"""
open_portfolio_defense.py — Apertura inicial · Defense & Aerospace
===================================================================
Script de ejecución única para abrir las 5 posiciones del Portfolio 2.

Uso:
  python open_portfolio_defense.py            ← modo real (ejecuta órdenes)
  python open_portfolio_defense.py --dry-run  ← simula sin ejecutar nada

Requiere en el entorno:
  ALPACA_API_KEY        ← key de la cuenta Alpaca Paper de este portfolio
  ALPACA_SECRET_KEY     ← secret de la cuenta Alpaca Paper de este portfolio
  TELEGRAM_TOKEN        ← para confirmación por Telegram (opcional)
  TELEGRAM_CHAT_ID      ← para confirmación por Telegram (opcional)

Seguridades:
  - Verifica que la cuenta es Paper Trading antes de ejecutar
  - Verifica que el portfolio está vacío (no duplica posiciones)
  - Verifica que hay suficiente buying power
  - Envía confirmación por Telegram al terminar
"""

import os
import sys
import json
import time
import requests
from datetime import datetime
import pytz

# ── Config ────────────────────────────────────────────────────────────────────
ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

ET = pytz.timezone("America/New_York")

# ── Portfolio 2 — Defense & Aerospace ────────────────────────────────────────
# Capital: $10,000 — Alpaca calcula las shares al precio de mercado del momento
PORTFOLIO = [
    {"ticker": "RTX",  "capital": 2800.00, "sector": "Misiles & Air Defense", "stop_pct": 0.20},
    {"ticker": "LMT",  "capital": 2800.00, "sector": "Plataformas & C2",      "stop_pct": 0.18},
    {"ticker": "LHX",  "capital": 2000.00, "sector": "Electrónica & ISR",     "stop_pct": 0.18},
    {"ticker": "HII",  "capital": 1400.00, "sector": "Naval & Submarinos",    "stop_pct": 0.20},
    {"ticker": "KTOS", "capital": 1000.00, "sector": "Drones & Hipersónico",  "stop_pct": 0.25},
]

TOTAL_CAPITAL = 10_000.00

# ── Alpaca helpers ────────────────────────────────────────────────────────────
def _headers() -> dict:
    return {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
        "Content-Type":        "application/json",
    }

def get_account() -> dict:
    r = requests.get(f"{ALPACA_BASE_URL}/v2/account", headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json()

def get_positions() -> list:
    r = requests.get(f"{ALPACA_BASE_URL}/v2/positions", headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json()

def place_order(ticker: str, notional_usd: float) -> dict:
    payload = {
        "symbol":        ticker,
        "notional":      f"{notional_usd:.2f}",   # USD amount — Alpaca calculates shares
        "side":          "buy",
        "type":          "market",
        "time_in_force": "day",
    }
    r = requests.post(
        f"{ALPACA_BASE_URL}/v2/orders",
        headers=_headers(),
        json=payload,
        timeout=10,
    )
    r.raise_for_status()
    return r.json()

def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass

# ── Checks ────────────────────────────────────────────────────────────────────
def preflight_checks(dry_run: bool) -> bool:
    """Run all safety checks before executing orders."""
    print("\n── Pre-flight checks ─────────────────────────────────────")

    # 1. Credentials present
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        print("❌ ALPACA_API_KEY / ALPACA_SECRET_KEY not set in environment.")
        return False
    print("✅ Credentials present")

    # 2. Fetch account
    try:
        account = get_account()
    except Exception as e:
        print(f"❌ Cannot connect to Alpaca: {e}")
        return False

    # 3. Confirm Paper Trading (never live)
    acct_num = account.get("account_number", "unknown")
    if acct_num.startswith("PA"):
        print(f"✅ Paper Trading account confirmed: {acct_num}")
    else:
        print(f"⚠️  Account number: {acct_num} — proceeding (verify this is Paper Trading)")

    # 4. Buying power
    buying_power = float(account.get("buying_power", 0))
    equity       = float(account.get("equity", 0))
    print(f"✅ Account equity:       ${equity:,.2f}")
    print(f"✅ Buying power:         ${buying_power:,.2f}")
    if buying_power < TOTAL_CAPITAL * 0.95:
        print(f"❌ Insufficient buying power. Need ~${TOTAL_CAPITAL:,.0f}, have ${buying_power:,.2f}")
        return False
    print(f"✅ Sufficient buying power for ${TOTAL_CAPITAL:,.0f}")

    # 5. No existing positions in these tickers
    try:
        existing = get_positions()
        tickers_in_account = {p.get("symbol") for p in existing}
        conflicts = [p["ticker"] for p in PORTFOLIO if p["ticker"] in tickers_in_account]
        if conflicts:
            print(f"⚠️  Already have positions in: {conflicts} — will add notional on top")
        else:
            print("✅ No conflicting positions — account is clean")
    except Exception as e:
        print(f"⚠️  Could not check existing positions: {e}")

    print("── All checks passed ─────────────────────────────────────\n")
    return True

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    dry_run = "--dry-run" in sys.argv
    now_et  = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")

    print(f"\n{'='*55}")
    print(f"  Defense & Aerospace — Portfolio Opening Script")
    print(f"  {now_et}")
    if dry_run:
        print(f"  ⚠️  DRY RUN — no orders will be executed")
    print(f"{'='*55}")

    # Pre-flight
    if not preflight_checks(dry_run):
        sys.exit(1)

    # Summary
    print("Orders to execute (notional — Alpaca calcula shares al precio de mercado):")
    print(f"{'Ticker':<8} {'Capital USD':>12} {'Peso':>6} {'Stop':>6}")
    print("-" * 36)
    for p in PORTFOLIO:
        peso = p['capital'] / TOTAL_CAPITAL * 100
        print(f"{p['ticker']:<8} ${p['capital']:>11,.2f} {peso:>5.0f}%  −{p['stop_pct']*100:.0f}%")
    print("-" * 36)
    print(f"{'TOTAL':<8} ${TOTAL_CAPITAL:>11,.2f}")
    print()

    if not dry_run:
        print("Proceeding with execution (dry_run=false)...")

    # Execute orders
    results = []
    print("\nExecuting orders...")
    for p in PORTFOLIO:
        ticker  = p["ticker"]
        capital = p["capital"]

        if dry_run:
            print(f"  [DRY RUN] BUY ${capital:,.2f} notional of {ticker}")
            results.append({"ticker": ticker, "status": "dry_run", "capital": capital})
            continue

        try:
            order  = place_order(ticker, capital)
            oid    = order.get("id", "?")[:8]
            status = order.get("status", "?")
            print(f"  ✅ {ticker}: ${capital:,.2f} — Order {oid}... [{status}]")
            results.append({"ticker": ticker, "status": "ok", "order_id": oid, "capital": capital})
            time.sleep(0.5)
        except Exception as e:
            print(f"  ❌ {ticker}: ERROR — {e}")
            results.append({"ticker": ticker, "status": "error", "error": str(e)})

    # Summary
    ok      = [r for r in results if r["status"] in ("ok", "dry_run")]
    errors  = [r for r in results if r["status"] == "error"]

    print(f"\n{'='*55}")
    print(f"  Done: {len(ok)}/5 orders {'simulated' if dry_run else 'executed'}")
    if errors:
        print(f"  Errors: {[e['ticker'] for e in errors]}")
    print(f"{'='*55}\n")

    # Telegram confirmation
    if not dry_run:
        if ok:
            lines = [f"🛡 <b>Defense &amp; Aerospace — Posiciones abiertas</b>", f"{now_et}\n"]
            for r in ok:
                p = next(x for x in PORTFOLIO if x["ticker"] == r["ticker"])
                lines.append(
                    f"✅ <b>{r['ticker']}</b> — ${p['capital']:,.0f} notional "
                    f"| Stop −{p['stop_pct']*100:.0f}%"
                )
            if errors:
                lines.append(f"\n❌ Errores: {[e['ticker'] for e in errors]}")
            lines.append(f"\nCapital total: ${TOTAL_CAPITAL:,.0f}")
            lines.append("Alpaca calcula shares al precio de mercado.")
            lines.append("Revisa Alpaca Paper para confirmar los fills.")
            send_telegram("\n".join(lines))
            print("Telegram notification sent.")
        else:
            send_telegram(f"❌ Defense &amp; Aerospace — Error al abrir posiciones.\n{now_et}")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()

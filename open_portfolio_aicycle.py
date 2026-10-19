"""
open_portfolio_aicycle.py — Apertura inicial · Frontier5 AI Cycle · Portfolio 1
=================================================================================
Script de ejecución única para abrir las 5 posiciones del Portfolio 1.
Usa órdenes notional (USD) — Alpaca calcula las shares al precio de mercado.

Requiere en el entorno:
  ALPACA_API_KEY        ← key cuenta Portfolio 1 (AI Cycle)
  ALPACA_SECRET_KEY     ← secret cuenta Portfolio 1 (AI Cycle)
  FINNHUB_API_KEY       ← para precio de fallback si notional falla
  TELEGRAM_TOKEN        ← confirmación por Telegram
  TELEGRAM_CHAT_ID      ← chat destino
"""

import os
import sys
import time
import requests
from datetime import datetime
import pytz

ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"
FINNHUB_API_KEY   = os.environ.get("FINNHUB_API_KEY", "")
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "")
ET = pytz.timezone("America/New_York")

# ── Portfolio 1 — AI Cycle ────────────────────────────────────────────────────
PORTFOLIO = [
    {"ticker": "NVDA", "capital": 3000.00, "sector": "GPU & Compute"},
    {"ticker": "TSM",  "capital": 2500.00, "sector": "Fabricación Semis"},
    {"ticker": "ANET", "capital": 2000.00, "sector": "Redes & Data Centers"},
    {"ticker": "PLTR", "capital": 1500.00, "sector": "Software IA & Datos"},
    {"ticker": "MRVL", "capital": 1000.00, "sector": "Silicon Fotónico & ASIC"},
]
TOTAL_CAPITAL = 10_000.00

# Tickers que no soportan notional en Alpaca — usar qty entera
QTY_ONLY_TICKERS = set()  # añadir ticker aquí si da 403

def _headers():
    return {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
        "Content-Type":        "application/json",
    }

def get_price(ticker: str) -> float:
    r = requests.get(
        f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_API_KEY}",
        timeout=8
    )
    return float(r.json().get("c", 0))

def place_order(ticker: str, capital: float) -> dict:
    if ticker in QTY_ONLY_TICKERS:
        price = get_price(ticker)
        if price <= 0:
            raise ValueError(f"No price for {ticker}")
        qty = int(capital / price)
        print(f"  [{ticker}] qty mode: {qty} shares @ ~${price:.2f}")
        payload = {"symbol": ticker, "qty": str(qty), "side": "buy",
                   "type": "market", "time_in_force": "day"}
    else:
        payload = {"symbol": ticker, "notional": f"{capital:.2f}", "side": "buy",
                   "type": "market", "time_in_force": "day"}
    r = requests.post(f"{ALPACA_BASE_URL}/v2/orders",
                      headers=_headers(), json=payload, timeout=10)
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

def main():
    dry_run = "--dry-run" in sys.argv
    now_et  = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")

    print(f"\n{'='*55}")
    print(f"  Frontier5 AI Cycle — Portfolio Opening Script")
    print(f"  {now_et}")
    if dry_run:
        print(f"  ⚠️  DRY RUN — no orders will be executed")
    print(f"{'='*55}")

    # Preflight
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        print("❌ ALPACA_API_KEY / ALPACA_SECRET_KEY not set")
        sys.exit(1)

    try:
        account = requests.get(f"{ALPACA_BASE_URL}/v2/account",
                               headers=_headers(), timeout=10).json()
    except Exception as e:
        print(f"❌ Cannot connect to Alpaca: {e}")
        sys.exit(1)

    acct_num     = account.get("account_number", "?")
    buying_power = float(account.get("buying_power", 0))
    equity       = float(account.get("equity", 0))

    print(f"\n── Pre-flight checks ─────────────────────────────────────")
    print(f"✅ Account: {acct_num}")
    print(f"✅ Equity:  ${equity:,.2f}")
    print(f"✅ Buying power: ${buying_power:,.2f}")

    if buying_power < TOTAL_CAPITAL * 0.95:
        print(f"❌ Insufficient buying power. Need ${TOTAL_CAPITAL:,.0f}")
        sys.exit(1)
    print(f"✅ Sufficient buying power for ${TOTAL_CAPITAL:,.0f}")
    print(f"── All checks passed ─────────────────────────────────────\n")

    # Summary
    print("Orders to execute (notional — Alpaca calcula shares al precio de mercado):")
    print(f"{'Ticker':<8} {'Capital':>12} {'Peso':>6}")
    print("-" * 30)
    for p in PORTFOLIO:
        peso = p['capital'] / TOTAL_CAPITAL * 100
        print(f"{p['ticker']:<8} ${p['capital']:>11,.2f} {peso:>5.0f}%")
    print("-" * 30)
    print(f"{'TOTAL':<8} ${TOTAL_CAPITAL:>11,.2f}")
    print()

    if dry_run:
        for p in PORTFOLIO:
            print(f"  [DRY RUN] BUY ${p['capital']:,.2f} of {p['ticker']}")
        sys.exit(0)

    print("Proceeding with execution...")
    print("Executing orders...")

    results = []
    for p in PORTFOLIO:
        ticker  = p["ticker"]
        capital = p["capital"]
        try:
            order  = place_order(ticker, capital)
            oid    = order.get("id", "?")[:8]
            status = order.get("status", "?")
            print(f"  ✅ {ticker}: ${capital:,.2f} — Order {oid}... [{status}]")
            results.append({"ticker": ticker, "status": "ok", "capital": capital, "order_id": oid})
        except Exception as e:
            print(f"  ❌ {ticker}: ERROR — {e}")
            results.append({"ticker": ticker, "status": "error", "error": str(e)})
        time.sleep(0.5)

    ok     = [r for r in results if r["status"] == "ok"]
    errors = [r for r in results if r["status"] == "error"]

    print(f"\n{'='*55}")
    print(f"  Done: {len(ok)}/5 orders executed")
    if errors:
        print(f"  Errors: {[e['ticker'] for e in errors]}")
    print(f"{'='*55}\n")

    if ok:
        lines = ["🧠 <b>Frontier5 AI Cycle — Posiciones abiertas</b>", f"{now_et}\n"]
        for r in ok:
            p = next(x for x in PORTFOLIO if x["ticker"] == r["ticker"])
            lines.append(f"✅ <b>{r['ticker']}</b> — ${p['capital']:,.0f} | {p['sector']}")
        if errors:
            lines.append(f"\n❌ Errores: {[e['ticker'] for e in errors]}")
        lines.append(f"\nCapital total: ${TOTAL_CAPITAL:,.0f}")
        lines.append("Revisa Alpaca Paper para confirmar los fills.")
        send_telegram("\n".join(lines))
        print("Telegram notification sent.")

    if errors:
        sys.exit(1)

if __name__ == "__main__":
    main()

"""
dca_bot.py — Cash Redeployment Bot · Frontier5 v2.0
=====================================================
Runs daily via GitHub Actions (09:15 ET, Mon-Fri).
Monitors Alpaca cash balance. Only speaks when cash > $100 is detected
(after a stop-loss exit or position trim).

What it does:
  1. Checks Alpaca for available cash
  2. If cash > $100: analyzes remaining positions using RSI + EMA-20
  3. Identifies best redeployment candidate — existing position or new ticker
  4. Sends Telegram alert with YES/NO buttons
  5. Silence = no cash to deploy

Rules:
  - Never adds to a position within 5% of its stop-loss
  - Prefers RSI < 45 over RSI > 60
  - If no clear signal → recommends holding cash
  - Never forces a trade — always defers to human confirmation
"""

import sys
import os
import json
import requests
from datetime import datetime, timedelta

import pytz

from config import (
    PORTFOLIO, ENTRY_PRICES, TICKER_MAP,
    PORTFOLIO_CONTEXT, DCA_RULES,
)
from utils import (
    call_claude, send_telegram, is_market_day,
    fetch_alpaca_account, fetch_alpaca_positions,
    ET, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
    ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL,
)

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
MIN_CASH        = 100.0   # minimum cash to trigger analysis

# ── Claude system prompt ──────────────────────────────────────────────────────
SYSTEM_PROMPT = f"""You are an expert portfolio analyst for Frontier5 v2.0.

{PORTFOLIO_CONTEXT}

Cash has been detected in the portfolio — likely from a stop-loss exit or trim.
Your job is to recommend the best redeployment of this cash.

Analyze each remaining position and produce EXACTLY this format:

CASH REDEPLOYMENT ANALYSIS — $[AMOUNT] available

MARKET CONDITIONS
[1 line on current market context relevant to Frontier5]

POSITION SIGNALS
[For each active position, one line:]
TICKER  RSI:[X]  EMA20:[above/below/at]  Stop dist:[X%]  Signal:[BUY/WAIT/AVOID]

RECOMMENDATION
Action: [REDEPLOY INTO TICKER / HOLD CASH / SPLIT BETWEEN TICKER1 AND TICKER2]
Amount: $[X] into [TICKER] ([X]% of available cash)
Reasoning: [2-3 sentences — why this position, why now, RSI/EMA context]

RISK CHECK
- Stop-loss distance after add: [X%] (minimum 5% required)
- Position concentration after add: [X%] of portfolio
- Thesis still intact: YES / REVIEW NEEDED

HOLD CASH IF:
[Only include if recommending to hold — specific conditions to watch for before deploying]

Under 180 words. Direct and actionable. No fluff.
Remember: never recommend adding to a position within 5% of its stop-loss."""


# ── Finnhub RSI + EMA fetcher ─────────────────────────────────────────────────
def fetch_technical_indicators(ticker: str) -> dict:
    """
    Fetch RSI (14) and EMA-20 from Finnhub technical indicators.
    Uses weekly candles for RSI as per Frontier5 strategy.
    """
    try:
        # RSI weekly
        r_rsi = requests.get(
            "https://finnhub.io/api/v1/indicator",
            params={
                "symbol":     ticker,
                "resolution": "W",       # weekly
                "from":       int((datetime.now() - timedelta(days=365)).timestamp()),
                "to":         int(datetime.now().timestamp()),
                "indicator":  "rsi",
                "timeperiod": 14,
                "token":      FINNHUB_API_KEY,
            },
            timeout=10,
        )
        rsi_data = r_rsi.json()
        rsi_values = rsi_data.get("rsi", [])
        rsi = round(rsi_values[-1], 1) if rsi_values else None

        # EMA-20 daily
        r_ema = requests.get(
            "https://finnhub.io/api/v1/indicator",
            params={
                "symbol":     ticker,
                "resolution": "D",       # daily
                "from":       int((datetime.now() - timedelta(days=60)).timestamp()),
                "to":         int(datetime.now().timestamp()),
                "indicator":  "ema",
                "timeperiod": 20,
                "token":      FINNHUB_API_KEY,
            },
            timeout=10,
        )
        ema_data = r_ema.json()
        ema_values = ema_data.get("ema", [])
        ema20 = round(ema_values[-1], 2) if ema_values else None

        return {"rsi": rsi, "ema20": ema20}

    except Exception as e:
        print(f"  Could not fetch indicators for {ticker}: {e}")
        return {"rsi": None, "ema20": None}


def fetch_current_price(ticker: str) -> float:
    """Fetch current price from Finnhub."""
    try:
        r = requests.get(
            f"https://finnhub.io/api/v1/quote",
            params={"symbol": ticker, "token": FINNHUB_API_KEY},
            timeout=8,
        )
        return float(r.json().get("c", 0))
    except Exception:
        return 0.0


# ── Position analyzer ─────────────────────────────────────────────────────────
def analyze_positions(alpaca_positions: list, cash: float) -> list:
    """
    Analyze all active Frontier5 positions for redeployment suitability.
    Returns list of dicts with technical signals and risk metrics.
    """
    # Build map of active positions from Alpaca
    active = {p["ticker"]: p for p in alpaca_positions}
    total_portfolio = sum(p["market_value"] for p in alpaca_positions) + cash

    results = []
    for pos in PORTFOLIO:
        ticker   = pos["ticker"]
        pos_cfg  = TICKER_MAP.get(ticker, {})
        entry    = ENTRY_PRICES.get(ticker)
        stop_pct = pos_cfg.get("stop_loss_pct", 0.10)

        # Skip if position was fully exited (not in Alpaca)
        if ticker not in active:
            print(f"  {ticker}: not in portfolio — skipped")
            continue

        alpaca_pos = active[ticker]
        price      = alpaca_pos["current_price"]
        stop_lvl   = round(entry * (1 - stop_pct), 2) if entry else None
        dist_stop  = ((price - stop_lvl) / price * 100) if stop_lvl else None
        pnl_pct    = alpaca_pos["pl_total_pct"]
        mkt_val    = alpaca_pos["market_value"]
        weight     = mkt_val / total_portfolio * 100 if total_portfolio else 0

        print(f"  Fetching indicators for {ticker}...")
        indicators = fetch_technical_indicators(ticker)
        rsi   = indicators["rsi"]
        ema20 = indicators["ema20"]

        # EMA position
        if ema20 and price:
            ema_dist_pct = ((price - ema20) / ema20 * 100)
            if price > ema20 * 1.02:
                ema_signal = "above"
            elif price < ema20 * 0.98:
                ema_signal = "below"
            else:
                ema_signal = "at"
        else:
            ema_dist_pct = None
            ema_signal   = "unknown"

        # Buy signal logic
        stop_too_close = dist_stop is not None and dist_stop < 5.0
        if stop_too_close:
            signal = "AVOID"      # never add near stop
        elif rsi and rsi < 45 and ema_signal in ("below", "at"):
            signal = "BUY"        # oversold + near/below EMA — strong entry
        elif rsi and rsi < 50 and ema_signal == "at":
            signal = "BUY"        # mild oversold at EMA — decent entry
        elif rsi and rsi > 65:
            signal = "WAIT"       # overbought — wait for pullback
        else:
            signal = "WAIT"       # neutral — no clear signal

        # Concentration after hypothetical add
        add_amount      = cash * 0.8   # conservative — don't deploy 100%
        new_val         = mkt_val + add_amount
        new_weight      = new_val / (total_portfolio + add_amount) * 100

        results.append({
            "ticker":        ticker,
            "sector":        pos_cfg.get("sector", ""),
            "weight":        pos_cfg.get("weight", 0),
            "price":         price,
            "entry":         entry,
            "stop":          stop_lvl,
            "dist_stop":     dist_stop,
            "pnl_pct":       pnl_pct,
            "market_value":  mkt_val,
            "current_weight_pct": round(weight, 1),
            "rsi":           rsi,
            "ema20":         ema20,
            "ema_signal":    ema_signal,
            "ema_dist_pct":  ema_dist_pct,
            "signal":        signal,
            "stop_too_close": stop_too_close,
            "new_weight_if_added": round(new_weight, 1),
        })

    return results


# ── Telegram YES/NO buttons ───────────────────────────────────────────────────
def send_redeployment_alert(analysis_text: str, recommendation: dict, cash: float):
    """Send analysis with YES/NO confirmation buttons."""
    ticker = recommendation.get("ticker", "HOLD")
    amount = recommendation.get("amount", cash)

    header = (
        f"💰 <b>CASH REDEPLOYMENT ALERT</b>\n"
        f"Available: <b>${cash:,.2f}</b>\n\n"
    )
    full_message = header + analysis_text

    # Send full analysis
    send_telegram(full_message)

    # If there's a specific ticker recommendation, send YES/NO
    if ticker != "HOLD":
        keyboard = {
            "inline_keyboard": [[
                {"text": f"✅ Deployar ${amount:,.0f} en {ticker}",
                 "callback_data": f"DCA_YES|{ticker}|{amount:.2f}"},
                {"text": "❌ Mantener cash",
                 "callback_data": f"DCA_NO|{ticker}|{amount:.2f}"},
            ]]
        }
        payload = {
            "chat_id":      TELEGRAM_CHAT_ID,
            "text":         f"⚠️ ¿Deployar <b>${amount:,.0f}</b> en <b>{ticker}</b>?",
            "parse_mode":   "HTML",
            "reply_markup": json.dumps(keyboard),
        }
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json=payload,
            timeout=10,
        )
        r.raise_for_status()


def extract_recommendation(analysis: str, positions: list) -> dict:
    """
    Parse Claude's recommendation to extract ticker and amount.
    Returns dict with ticker and amount for the YES/NO button.
    """
    # Look for "REDEPLOY INTO TICKER" pattern
    for pos in positions:
        ticker = pos["ticker"]
        if f"REDEPLOY INTO {ticker}" in analysis.upper():
            # Try to extract dollar amount
            import re
            amounts = re.findall(r'\$(\d+(?:,\d+)?(?:\.\d+)?)', analysis)
            amount  = float(amounts[0].replace(",", "")) if amounts else 0
            return {"ticker": ticker, "amount": amount}

    return {"ticker": "HOLD", "amount": 0}


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    now_et = datetime.now(ET)
    print(f"Frontier5 Cash Redeployment Bot — {now_et.strftime('%Y-%m-%d %H:%M ET')}")

    # Gate 1: market day
    if not is_market_day():
        print("Market closed — skipping.")
        sys.exit(0)

    # Gate 2: check Alpaca cash balance
    print("Checking Alpaca cash balance...")
    try:
        account = fetch_alpaca_account()
        cash    = account.get("cash", 0.0)
        equity  = account.get("equity", 0.0)
        print(f"  Cash: ${cash:,.2f} | Equity: ${equity:,.2f}")
    except Exception as e:
        print(f"  Could not fetch Alpaca account: {e}")
        sys.exit(0)

    if cash < MIN_CASH:
        print(f"  Cash ${cash:.2f} below threshold ${MIN_CASH} — staying silent.")
        sys.exit(0)

    print(f"  💰 Cash detected: ${cash:,.2f} — proceeding with analysis")

    # Gate 3: fetch active positions
    print("Fetching active positions from Alpaca...")
    try:
        alpaca_positions = fetch_alpaca_positions()
        active_tickers   = [p["ticker"] for p in alpaca_positions]
        print(f"  Active positions: {active_tickers}")
    except Exception as e:
        print(f"  Could not fetch positions: {e}")
        sys.exit(0)

    if not alpaca_positions:
        print("  No active positions — cash sitting idle, no analysis needed.")
        sys.exit(0)

    # Analyze all active positions
    print("Analyzing positions for redeployment suitability...")
    positions = analyze_positions(alpaca_positions, cash)

    if not positions:
        print("  No positions to analyze.")
        sys.exit(0)

    # Call Claude for recommendation
    print("Calling Claude for redeployment recommendation...")
    now_str = now_et.strftime("%Y-%m-%d %H:%M")

    user_content = (
        f"Time ET: {now_str}\n"
        f"Available cash: ${cash:,.2f}\n"
        f"Total portfolio equity: ${equity:,.2f}\n"
        f"Active positions: {active_tickers}\n\n"
        f"POSITION ANALYSIS:\n{json.dumps(positions, indent=2, default=str)}\n\n"
        f"DCA Rules from config:\n{json.dumps(DCA_RULES, indent=2)}\n\n"
        "Generate the cash redeployment analysis now."
    )

    try:
        analysis = call_claude(SYSTEM_PROMPT, user_content, max_tokens=600)

        # Extract recommendation for YES/NO buttons
        recommendation = extract_recommendation(analysis, positions)

        # Send to Telegram
        send_redeployment_alert(analysis, recommendation, cash)
        print(f"✅ Redeployment alert sent. Recommendation: {recommendation}")

    except Exception as e:
        print(f"❌ Error calling Claude: {e}")
        # Send simple fallback
        send_telegram(
            f"💰 <b>CASH DETECTED — ${cash:,.2f}</b>\n"
            f"Error generando análisis automático: {str(e)[:100]}\n"
            f"Revisa posiciones manualmente en el dashboard."
        )
        sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    main()

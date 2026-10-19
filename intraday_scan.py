"""
intraday_scan.py — Critical Alert Scanner · Frontier5 v2.0
===========================================================
Runs 2x/day via GitHub Actions (09:15, 15:45 ET).
Sends Telegram alerts with YES/NO inline keyboards ONLY when
a critical condition is detected. Silence = all is fine.

DYNAMIC MODE: Reads positions directly from Alpaca — no hardcoded tickers.
Stop-loss: universal 20% from avg_entry for all positions.

Critical triggers:
  1. Position drops >5% on the day
  2. Position moves >7% in either direction (extreme move)
  3. Stop-loss breached (price < avg_entry * 0.80)
  4. Critical news keyword detected in any active position
"""

import os
import sys
import json
import requests
from datetime import datetime
import pytz

from config import (
    ALERT_DROP_PCT, ALERT_EXTREME_PCT,
    CRITICAL_NEWS_KEYWORDS, PORTFOLIO_CONTEXT,
    PORTFOLIO_NAME, PORTFOLIO_EMOJI,
)
from utils import (
    is_market_day, get_news, get_quote,
    call_claude, send_telegram, session_label,
    fetch_alpaca_positions,
    ET, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
)

# ── Universal stop-loss ───────────────────────────────────────────────────────
STOP_LOSS_PCT = 0.20  # 20% from avg_entry for all positions

# ── Claude system prompt ──────────────────────────────────────────────────────
SYSTEM_PROMPT = f"""You are an expert portfolio analyst for Frontier5.

{PORTFOLIO_CONTEXT}

You are called ONLY when a critical condition has been detected.
Write a concise urgent Telegram alert — plain text only, no markdown symbols.

For EACH triggered position produce EXACTLY this block:

TICKER — REASON
Price: $X.XX | Entry: $X.XX | Stop: $X.XX (−20%)
Thesis intact? YES / NO / REVIEW
Suggestion: [ONE specific action, e.g. "Hold — normal pullback"
             or "SELL ALL — stop-loss breached"
             or "REVIEW — critical news, verify thesis"]

Then end with:
BOTTOM LINE: [1 sentence portfolio impact]

Under 180 words total. Direct. No fluff.
"""


# ── Fetch positions from Alpaca ───────────────────────────────────────────────
def fetch_portfolio_from_alpaca() -> list:
    """
    Read current positions from Alpaca and build portfolio list.
    Returns list of dicts with ticker, shares, avg_entry, stop_level.
    """
    try:
        positions = fetch_alpaca_positions()
        portfolio = []
        for p in positions:
            avg_entry  = p["avg_entry"]
            stop_level = round(avg_entry * (1 - STOP_LOSS_PCT), 2)
            portfolio.append({
                "ticker":     p["ticker"],
                "weight":     0,           # calculated after if needed
                "sector":     "Portfolio", # no hardcoded sectors
                "stop_loss_pct": STOP_LOSS_PCT,
                "avg_entry":  avg_entry,
                "shares":     p["qty"],
                "stop_level": stop_level,
            })
        return portfolio
    except Exception as e:
        print(f"Error fetching Alpaca positions: {e}")
        return []


# ── Fetch quotes for current positions ───────────────────────────────────────
def fetch_quotes_for_portfolio(portfolio: list) -> list:
    """Fetch live Finnhub quotes for all tickers in portfolio."""
    results = []
    for pos in portfolio:
        ticker = pos["ticker"]
        try:
            q          = get_quote(ticker)
            price      = q.get("c", 0)
            prev       = q.get("pc", 0)
            chg_pct    = ((price - prev) / prev * 100) if prev else 0
            stop_alert = price > 0 and price <= pos["stop_level"]
            results.append({
                "ticker":     ticker,
                "sector":     pos["sector"],
                "price":      round(price, 2),
                "chg_pct":    round(chg_pct, 2),
                "high":       round(q.get("h", 0), 2),
                "low":        round(q.get("l", 0), 2),
                "avg_entry":  pos["avg_entry"],
                "stop_level": pos["stop_level"],
                "stop_alert": stop_alert,
            })
        except Exception as e:
            results.append({"ticker": ticker, "error": str(e), "alert_reasons": ["API_ERROR"]})
    return results


# ── Critical condition detectors ──────────────────────────────────────────────
def detect_price_alerts(quotes: list) -> list:
    critical = []
    for q in quotes:
        if "error" in q:
            q.setdefault("alert_reasons", ["API_ERROR"])
            critical.append(q)
            continue
        reasons = []
        chg = q.get("chg_pct", 0)
        if q.get("stop_alert"):
            reasons.append("STOP_LOSS_BREACHED")
        if chg <= ALERT_DROP_PCT:
            reasons.append(f"DOWN {abs(chg):.1f}%")
        if abs(chg) >= ALERT_EXTREME_PCT:
            reasons.append(f"EXTREME MOVE {chg:+.1f}%")
        if reasons:
            q["alert_reasons"] = reasons
            critical.append(q)
    return critical


def detect_news_alerts(tickers: list) -> list:
    alerts = []
    for ticker in tickers:
        try:
            for item in get_news(ticker):
                if any(kw in item.get("headline", "").lower() for kw in CRITICAL_NEWS_KEYWORDS):
                    alerts.append({
                        "ticker":        ticker,
                        "alert_reasons": ["CRITICAL_NEWS"],
                        "items":         [item],
                    })
                    break
        except Exception:
            pass
    return alerts


def fetch_news_for_tickers(tickers: list) -> list:
    news = []
    for ticker in tickers:
        try:
            items = get_news(ticker)
            if items:
                news.append({"ticker": ticker, "items": items})
        except Exception:
            pass
    return news


# ── Telegram inline keyboard ──────────────────────────────────────────────────
def send_alert_with_buttons(alert_text: str, ticker: str, order_type: str) -> str | None:
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Sí, ejecutar", "callback_data": f"YES|{ticker}|{order_type}"},
            {"text": "❌ No, mantener", "callback_data": f"NO|{ticker}|"},
        ]]
    }
    payload = {
        "chat_id":      TELEGRAM_CHAT_ID,
        "text":         alert_text,
        "parse_mode":   "HTML",
        "reply_markup": json.dumps(keyboard),
    }
    r = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json=payload,
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("ok"):
        return str(data["result"]["message_id"])
    return None


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    now_str = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    print(f"Intraday Scan — {PORTFOLIO_NAME} — {now_str}")

    if not is_market_day():
        print("Market closed — staying silent.")
        sys.exit(0)

    session = session_label()

    # Load positions from Alpaca (dynamic — no hardcoded tickers)
    portfolio = fetch_portfolio_from_alpaca()
    if not portfolio:
        print("No positions in Alpaca — nothing to scan.")
        sys.exit(0)

    tickers = [p["ticker"] for p in portfolio]
    print(f"Session: {session} — scanning {len(tickers)} positions: {tickers}")

    # Fetch quotes
    quotes = fetch_quotes_for_portfolio(portfolio)

    # Detect alerts
    price_alerts = detect_price_alerts(quotes)
    print(f"Scanning news for {len(tickers)} positions...")
    news_alerts  = detect_news_alerts(tickers)

    # Merge
    all_critical: dict = {q["ticker"]: q for q in price_alerts}
    for n in news_alerts:
        ticker = n["ticker"]
        if ticker in all_critical:
            all_critical[ticker].setdefault("alert_reasons", [])
            all_critical[ticker]["alert_reasons"] += n.get("alert_reasons", [])
        else:
            all_critical[ticker] = n

    if not all_critical:
        print("No critical conditions — staying silent. All is well.")
        sys.exit(0)

    triggered         = list(all_critical.values())
    triggered_tickers = [q["ticker"] for q in triggered]
    print(f"Critical conditions: {triggered_tickers}")

    # Fetch news for price-alert tickers
    news_ticker_set = {n["ticker"] for n in news_alerts}
    extra_news = fetch_news_for_tickers(
        [t for t in triggered_tickers if t not in news_ticker_set]
    )
    all_news = extra_news + [
        {"ticker": n["ticker"], "items": n.get("items", [])} for n in news_alerts
    ]

    # Build dynamic context for Claude
    pos_summary = "\n".join([
        f"  {q['ticker']}: ${q.get('price',0)} ({q.get('chg_pct',0):+.2f}%) | "
        f"Entry ${q.get('avg_entry',0)} | Stop ${q.get('stop_level',0)} (−20%)"
        for q in quotes
    ])
    dynamic_context = f"""
{PORTFOLIO_CONTEXT}

Current positions ({now_str}):
{pos_summary}

Stop-loss: universal −20% from avg_entry for all positions.
"""

    # Call Claude
    briefing = call_claude(
        SYSTEM_PROMPT.replace(PORTFOLIO_CONTEXT, dynamic_context),
        f"Session: {session}\nTime ET: {now_str}\n\n"
        f"CRITICAL CONDITIONS:\n{json.dumps(triggered, indent=2)}\n\n"
        f"NEWS:\n{json.dumps(all_news, indent=2)}\n\n"
        "Generate the critical alert now.",
        max_tokens=600,
    )

    # Send full alert
    emoji  = PORTFOLIO_EMOJI if hasattr(__import__('config'), 'PORTFOLIO_EMOJI') else "🚨"
    header = f"{emoji} {PORTFOLIO_NAME} — CRITICAL ALERT — {session} {now_str} ET\n\n"
    send_telegram(header + briefing)

    # Send YES/NO buttons per triggered ticker
    for q in triggered:
        ticker  = q.get("ticker", "")
        reasons = q.get("alert_reasons", [])
        chg     = q.get("chg_pct", 0)
        price   = q.get("price", 0)

        if price == 0 and "STOP_LOSS_BREACHED" not in reasons:
            print(f"Skipping {ticker} — price $0 (API issue)")
            continue

        order_type = "SELL_ALL" if "STOP_LOSS_BREACHED" in reasons else "SELL_ALL"
        reasons_str = ", ".join(reasons)

        confirm_text = (
            f"⚠️ <b>{ticker}</b> — {reasons_str}\n"
            f"Precio: ${price} ({chg:+.2f}%)\n"
            f"Stop: ${q.get('stop_level', 0)} (−20% de ${q.get('avg_entry', 0)})\n\n"
            f"¿Deseas actuar sobre esta posición?"
        )
        msg_id = send_alert_with_buttons(confirm_text, ticker, order_type)
        if msg_id:
            print(f"Sent confirmation for {ticker}, msg_id={msg_id}")

    print("Done.")


if __name__ == "__main__":
    main()
# tested

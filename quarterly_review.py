"""
quarterly_review.py — Quarterly Review Bot · Frontier5 v2.0
=============================================================
Runs manually OR via GitHub Actions after each earnings season.
Typical schedule: 1st Monday of Jan/Apr/Jul/Oct at 08:00 ET.

For each of the 5 Frontier5 positions, fetches from Finnhub:
  - TTM fundamentals: P/E, P/S, ROE, ROA, gross/operating/net margins
  - Revenue & EPS growth YoY
  - Analyst upgrades/downgrades (last 90 days)
  - Insider transactions (last 90 days)

Then calls Claude to produce:
  1. Per-position thesis validation (INTACT / REVIEW / BROKEN)
  2. Weight adjustment recommendation (+/- % or HOLD)
  3. Portfolio-level quarterly summary with war context
  4. Freibetrag harvest opportunity (December only)

Output: Telegram message + optional detailed report
"""

import sys
import os
import json
from datetime import datetime, timedelta, date

import pytz
import requests

from config import PORTFOLIO, ENTRY_PRICES, TICKER_MAP, PORTFOLIO_CONTEXT, PORTFOLIO_NAME, PORTFOLIO_EMOJI
from utils  import call_claude, send_telegram, ET

# ── Finnhub helpers ───────────────────────────────────────────────────────────
def get_finnhub(endpoint: str, params: dict) -> dict:
    key = os.environ.get("FINNHUB_API_KEY", "")
    url = f"https://finnhub.io/api/v1/{endpoint}"
    params["token"] = key
    r = requests.get(url, params=params, timeout=12)
    r.raise_for_status()
    return r.json()


def fetch_fundamentals(ticker: str) -> dict:
    """Fetch TTM fundamental metrics for a ticker."""
    data = get_finnhub("stock/metric", {"symbol": ticker, "metric": "all"})
    m = data.get("metric", {})
    return {
        "pe":             m.get("peBasicExclExtraTTM"),
        "ps":             m.get("psAnnual"),
        "pb":             m.get("pbAnnual"),
        "roe":            m.get("roeTTM"),
        "roa":            m.get("roaTTM"),
        "gross_margin":   m.get("grossMarginTTM"),
        "op_margin":      m.get("operatingMarginTTM"),
        "net_margin":     m.get("netProfitMarginTTM"),
        "rev_growth_yoy": m.get("revenueGrowthTTMYoy"),
        "eps_growth_yoy": m.get("epsGrowthTTMYoy"),
        "market_cap_m":   m.get("marketCapitalization"),
    }


def fetch_quote(ticker: str) -> dict:
    """Fetch current price and day change."""
    data = get_finnhub("quote", {"symbol": ticker})
    price = data.get("c", 0)
    prev  = data.get("pc", 0)
    chg   = ((price - prev) / prev * 100) if prev else 0
    return {"price": price, "chg_pct": chg}


def fetch_upgrades(ticker: str, days: int = 90) -> list:
    """Fetch analyst upgrades/downgrades in the last N days."""
    try:
        today     = date.today().isoformat()
        from_date = (date.today() - timedelta(days=days)).isoformat()
        data = get_finnhub("stock/upgrade-downgrade", {
            "symbol": ticker, "from": from_date, "to": today
        })
        # Return last 5 most recent
        return data[:5] if data else []
    except Exception:
        return []


def fetch_insider_transactions(ticker: str, days: int = 90) -> dict:
    """
    Fetch insider transactions and summarize buy/sell activity.
    Returns dict with buy_count, sell_count, net_shares.
    """
    try:
        today     = date.today().isoformat()
        from_date = (date.today() - timedelta(days=days)).isoformat()
        data = get_finnhub("stock/insider-transactions", {
            "symbol": ticker, "from": from_date, "to": today
        })
        transactions = data.get("data", [])
        buys  = [t for t in transactions if t.get("transactionType", "").upper() in ("P", "BUY", "PURCHASE")]
        sells = [t for t in transactions if t.get("transactionType", "").upper() in ("S", "SELL", "SALE")]
        net_shares = sum(t.get("share", 0) for t in buys) - sum(t.get("share", 0) for t in sells)
        return {
            "buy_count":  len(buys),
            "sell_count": len(sells),
            "net_shares": net_shares,
            "recent":     transactions[:5],
        }
    except Exception:
        return {"buy_count": 0, "sell_count": 0, "net_shares": 0, "recent": []}


# ── Data assembly ─────────────────────────────────────────────────────────────
def assemble_position_data(ticker: str) -> dict:
    """Fetch all data for one position and assemble into a single dict."""
    pos_cfg = TICKER_MAP.get(ticker, {})
    entry   = ENTRY_PRICES.get(ticker)

    print(f"  Fetching data for {ticker}...")

    quote        = fetch_quote(ticker)
    fundamentals = fetch_fundamentals(ticker)
    upgrades     = fetch_upgrades(ticker)
    insiders     = fetch_insider_transactions(ticker)

    price     = quote["price"]
    stop_lvl  = round(entry * (1 - pos_cfg.get("stop_loss_pct", 0.10)), 2) if entry else None
    pnl_pct   = ((price - entry) / entry * 100) if entry else None
    dist_stop = ((price - stop_lvl) / price * 100) if stop_lvl else None

    return {
        "ticker":    ticker,
        "sector":    pos_cfg.get("sector", ""),
        "weight":    pos_cfg.get("weight", 0),
        "price":     price,
        "entry":     entry,
        "stop":      stop_lvl,
        "pnl_pct":   pnl_pct,
        "dist_stop": dist_stop,
        "fundamentals": fundamentals,
        "upgrades":     upgrades,
        "insiders":     insiders,
    }


# ── Claude system prompt ───────────────────────────────────────────────────────
SYSTEM_PROMPT = f"""You are an expert portfolio analyst for {PORTFOLIO_NAME}.

{PORTFOLIO_CONTEXT}

You are producing the Quarterly Review. This runs after each earnings season
(Jan/Apr/Jul/Oct) to validate each position's thesis and recommend weight adjustments.

CRITICAL RULE: Only include per-position detail for positions where thesis is
REVIEW or BROKEN. Positions with INTACT thesis → list them in a single summary
line only. Do NOT write full blocks for intact positions.

SECTION 1 — POSITION REVIEW:

✅ INTACT — no action needed: [TICKER (weight%), TICKER (weight%), ...]

[Only for REVIEW or BROKEN positions:]

TICKER — THESIS: [REVIEW / BROKEN]
Current: $X.XX | Entry: $X.XX | P&L: +/-X% | Stop: $X.XX (X% away)
Weight: X% | Recommendation: [INCREASE X% / REDUCE X% / EXIT]

Fundamentals snapshot:
  P/E: X | P/S: X | ROE: X% | Gross margin: X% | Rev growth: +X% YoY

Analyst sentiment (last 90 days): [upgrade/downgrade count and direction]
Insider activity: [buy/sell summary — bullish/bearish/neutral]

Thesis validation: [2-3 sentences explaining WHY it needs review or is broken]
Weight rationale: [1-2 sentences on the recommendation]

---

SECTION 2 — PORTFOLIO SUMMARY:

QUARTERLY SUMMARY — {PORTFOLIO_NAME} — [QUARTER] [YEAR]

Overall portfolio health: [STRONG / STABLE / NEEDS ATTENTION]
Positions with intact thesis: X/N
Positions flagged for review: X/N

[If 0 flagged] → "All theses intact — no rebalance needed."

[Only if REVIEW/BROKEN positions exist:]
Top concern: [ticker] — [1 line reason]
Suggested rebalance: [specific % changes]

Total portfolio P&L since entry: +/-X% ($X)

FREIBETRAG OPPORTUNITY: [Only if month is November or December]

Under 200 words if all intact. Under 350 words if positions to review.
Direct. No fluff."""


# ── Build quarterly review ────────────────────────────────────────────────────
def build_quarterly_review(all_data: list) -> str:
    """Call Claude with all 5 positions' data to generate the quarterly review."""
    now_et   = datetime.now(ET).strftime("%Y-%m-%d %H:%M")
    quarter  = f"Q{(datetime.now().month - 1) // 3 + 1} {datetime.now().year}"
    month    = datetime.now().month

    # Calculate portfolio-level stats
    total_cost  = sum(
        ENTRY_PRICES.get(d["ticker"], 0) * (10000 * d["weight"] / ENTRY_PRICES.get(d["ticker"], 1))
        for d in all_data if ENTRY_PRICES.get(d["ticker"]) and d.get("price")
    )
    total_value = sum(
        d["price"] * (10000 * d["weight"] / ENTRY_PRICES.get(d["ticker"], d["price"]))
        for d in all_data if ENTRY_PRICES.get(d["ticker"]) and d.get("price")
    )
    portfolio_pnl = ((total_value - total_cost) / total_cost * 100) if total_cost else 0

    user_content = f"""
Quarter: {quarter}
Date: {now_et} ET
Month: {month} ({"include Freibetrag analysis" if month >= 11 else "skip Freibetrag"})
Portfolio P&L since entry: {portfolio_pnl:+.2f}%

POSITION DATA:
{json.dumps(all_data, indent=2, default=str)}

Generate the full quarterly review now.
"""

    return call_claude(SYSTEM_PROMPT, user_content, max_tokens=1200)


# ── Format and send ───────────────────────────────────────────────────────────
def send_quarterly_review(review: str):
    """Split long review into chunks if needed (Telegram 4096 char limit)."""
    quarter = f"Q{(datetime.now().month - 1) // 3 + 1} {datetime.now().year}"
    header = f"📊 {PORTFOLIO_EMOJI} <b>{PORTFOLIO_NAME.upper()} QUARTERLY REVIEW — {quarter}</b>\n\n"
    full    = header + review

    # Telegram max message length is 4096 chars
    if len(full) <= 4096:
        send_telegram(full)
    else:
        # Split at section boundary
        parts = full.split("---")
        chunk = ""
        for part in parts:
            if len(chunk) + len(part) < 3800:
                chunk += part + "\n---\n"
            else:
                send_telegram(chunk)
                chunk = part + "\n---\n"
        if chunk.strip():
            send_telegram(chunk)


# ── Main ──────────────────────────────────────────────────────────────────────
def fetch_earnings_dates() -> dict:
    """
    Fetch next earnings date for each Frontier5 ticker from Finnhub.
    Returns dict: {ticker: date_str or None}
    """
    key = os.environ.get("FINNHUB_API_KEY", "")
    dates = {}
    for pos in PORTFOLIO:
        ticker = pos["ticker"]
        try:
            r = requests.get(
                f"https://finnhub.io/api/v1/calendar/earnings",
                params={"symbol": ticker, "token": key},
                timeout=10,
            )
            data = r.json()
            earnings_list = data.get("earningsCalendar", [])
            # Find the most recent past or upcoming date within 90 days
            today = date.today()
            relevant = [
                e["date"] for e in earnings_list
                if e.get("date") and abs((date.fromisoformat(e["date"]) - today).days) <= 90
            ]
            dates[ticker] = max(relevant) if relevant else None
        except Exception as e:
            print(f"  Could not fetch earnings date for {ticker}: {e}")
            dates[ticker] = None
    return dates


def should_run_today() -> tuple[bool, str]:
    """
    Check if today is 2 business days after the last Frontier5 position reported.
    Returns (should_run, reason_string).
    """
    today = date.today()
    print("Checking earnings dates from Finnhub...")
    earnings_dates = fetch_earnings_dates()
    print(f"  Earnings dates found: {earnings_dates}")

    # Filter to dates that are in the past (already reported)
    past_dates = {
        ticker: date.fromisoformat(d)
        for ticker, d in earnings_dates.items()
        if d and date.fromisoformat(d) <= today
    }

    if not past_dates:
        return False, "No past earnings dates found — too early in the quarter"

    # Find the latest reporting date (last position to report)
    last_ticker  = max(past_dates, key=lambda t: past_dates[t])
    last_date    = past_dates[last_ticker]
    days_since   = (today - last_date).days

    print(f"  Last to report: {last_ticker} on {last_date} ({days_since} days ago)")

    # Check all 5 positions have reported within the last 45 days
    all_reported = all(
        ticker in past_dates and (today - past_dates[ticker]).days <= 45
        for ticker in [p["ticker"] for p in PORTFOLIO]
    )

    if not all_reported:
        missing = [p["ticker"] for p in PORTFOLIO if p["ticker"] not in past_dates or (today - past_dates[p["ticker"]]).days > 45]
        return False, f"Not all positions have reported yet. Missing/stale: {missing}"

    # Trigger exactly 2 days after the last report
    if days_since == 2:
        return True, f"All 5 positions reported. Last was {last_ticker} on {last_date}. Running review."

    return False, f"Last report was {days_since} days ago (need exactly 2). Skipping."


def main():
    now_et = datetime.now(ET)
    print(f"Frontier5 Quarterly Review — {now_et.strftime('%Y-%m-%d %H:%M ET')}")
    print(f"Quarter: Q{(now_et.month - 1) // 3 + 1} {now_et.year}")

    # ── Dynamic gate: only run 2 days after all 5 positions have reported ────
    # Skip gate if triggered manually via workflow_dispatch
    manual_trigger = os.environ.get("MANUAL_TRIGGER", "").lower() == "true"
    if not manual_trigger:
        should_run, reason = should_run_today()
        print(f"Gate check: {reason}")
        if not should_run:
            print("Staying silent — conditions not met.")
            sys.exit(0)
    else:
        print("Manual trigger detected — skipping gate check.")

    # Send start notification
    send_telegram(
        f"⏳ <b>Iniciando Quarterly Review — Frontier5 v2.0</b>\n"
        f"Fetching fundamentals, analyst ratings e insider activity\n"
        f"para las 5 posiciones. Tardará ~30 segundos..."
    )

    # Fetch data for all 5 positions
    all_data = []
    errors   = []

    for pos in PORTFOLIO:
        ticker = pos["ticker"]
        try:
            data = assemble_position_data(ticker)
            all_data.append(data)
            print(f"  ✅ {ticker} — OK")
        except Exception as e:
            print(f"  ❌ {ticker} — Error: {e}")
            errors.append(f"{ticker}: {str(e)[:80]}")
            # Add minimal data so Claude still sees the position
            all_data.append({
                "ticker":       ticker,
                "sector":       pos.get("sector", ""),
                "weight":       pos.get("weight", 0),
                "price":        None,
                "entry":        ENTRY_PRICES.get(ticker),
                "error":        str(e),
                "fundamentals": {},
                "upgrades":     [],
                "insiders":     {"buy_count": 0, "sell_count": 0, "net_shares": 0},
            })

    if errors:
        print(f"⚠️ Errors on: {', '.join(e.split(':')[0] for e in errors)}")

    # Build review via Claude
    print("Calling Claude for quarterly analysis...")
    try:
        review = build_quarterly_review(all_data)
        send_quarterly_review(review)
        print("✅ Quarterly review sent to Telegram.")
    except Exception as e:
        error_msg = f"❌ Error generando quarterly review: {e}"
        print(error_msg)
        send_telegram(error_msg)
        sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    main()

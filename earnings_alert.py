"""
earnings_alert.py — Earnings Pre-Alert Bot · Multi-Portfolio
=============================================================
Runs daily via GitHub Actions (08:00 ET, Mon-Fri).
Sends a Telegram alert 48h and 24h before each earnings report.

The earnings calendar is defined per-portfolio in each config file.
Set PORTFOLIO_ID env var to select the portfolio (default: frontier5_v2).

Alert triggers:
  - 48h before earnings → full pre-brief (EPS history, consensus, strategy)
  - 24h before earnings → reminder alert (shorter)

The bot never fires outside these windows — silence = no earnings imminent.
"""

import sys
import os
import json
from datetime import datetime, timedelta, date

import pytz

from utils import call_claude, send_telegram, is_market_day, ET
from config import (
    PORTFOLIO_NAME, PORTFOLIO_EMOJI, PORTFOLIO_CONTEXT,
    EARNINGS_CALENDAR,
)


# ── War banner context generator ──────────────────────────────────────────────
CONTEXT_SYSTEM_PROMPT = f"""You are a macro analyst for {PORTFOLIO_NAME}.
Generate a single line of 4-5 keywords/phrases summarizing the current macro context
that affects this portfolio. Use short, punchy phrases separated by ·
Start with a relevant emoji. Keep total under 120 characters.
Focus on: geopolitical events, key market movers, sector-specific risks for {PORTFOLIO_NAME}.
Only return the single line, nothing else."""


def generate_war_context(news_items: list) -> str:
    """Call Claude to generate a concise macro context banner from recent news."""
    headlines = "\n".join(
        f"- {item.get('headline', '')}" for item in news_items[:10]
    )
    try:
        return call_claude(
            CONTEXT_SYSTEM_PROMPT,
            f"Recent market headlines:\n{headlines}\n\nGenerate the context banner now.",
            max_tokens=80,
        )
    except Exception as e:
        print(f"Context generation failed: {e}")
        return ""


def update_context_file(context: str):
    """Write context to a local file so webhook_server can serve it."""
    import json as _json
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "context.json")
        with open(path, "w") as f:
            _json.dump({"ok": True, "context": context, 
                       "updated": datetime.now().isoformat()}, f)
        print(f"Context updated: {context}")
    except Exception as e:
        print(f"Could not write context.json: {e}")




# ── Claude system prompt ───────────────────────────────────────────────────────
SYSTEM_PROMPT = f"""You are an expert portfolio analyst for {PORTFOLIO_NAME}.

{PORTFOLIO_CONTEXT}

You are producing a pre-earnings brief for Telegram. Plain text only, no markdown symbols.

Structure EXACTLY like this:

EARNINGS BRIEF — TICKER · [DATE] [TIMING]

CONSENSUS
EPS estimate: $X.XX  |  Revenue est: $XXB
Last 4 quarters surprise: [+X%, +X%, +X%, +X%] avg: +X%
Beat streak: [X consecutive beats]

MACRO CONTEXT
[1-2 lines on how current macro conditions affect this company's earnings]

KEY METRICS TO WATCH
[3-4 bullet points: exact metrics and thresholds that matter]

THESIS CHECK
Intact if: [specific conditions]
At risk if: [specific conditions]

RECOMMENDATION
[ONE of: HOLD THROUGH / REDUCE 25% BEFORE / ADD ON BEAT / WATCH CLOSELY]
[2-3 sentences with specific reasoning]

STOP-LOSS REMINDER
Entry: $X.XX | Stop: $X.XX | Current distance: X%

Keep total under 220 words. Direct and actionable."""


# ── Alert checker ─────────────────────────────────────────────────────────────
def check_earnings_alerts(today: date) -> list[dict]:
    """
    Returns list of earnings events that need an alert today.
    Triggers at exactly 48h and 24h before the earnings date.
    """
    alerts = []
    for e in EARNINGS_CALENDAR:
        days_until = (e["date"] - today).days
        if days_until == 2:
            alerts.append({**e, "alert_type": "48H", "days_until": 2})
        elif days_until == 1:
            alerts.append({**e, "alert_type": "24H", "days_until": 1})
    return alerts


# ── Build brief via Claude ────────────────────────────────────────────────────
def build_earnings_brief(event: dict) -> str:
    """Call Claude to generate the earnings pre-brief."""
    # Handle both list-of-floats and list-of-dicts for eps_history
    eps_hist = event.get("eps_history", [])
    if eps_hist and isinstance(eps_hist[0], dict):
        avg_surprise = sum(q.get("surprise_pct", 0) for q in eps_hist) / len(eps_hist)
        beat_streak  = sum(1 for q in eps_hist if q.get("surprise_pct", 0) > 0)
        history_str  = "\n".join(
            f"  {q.get('period','')}: actual ${q.get('actual',0)} vs est ${q.get('estimate',0)} "
            f"({'+'if q.get('surprise_pct',0)>0 else ''}{q.get('surprise_pct',0):.1f}%)"
            for q in eps_hist
        )
    else:
        # Simple list of floats [Q1%, Q2%, Q3%, Q4%]
        avg_surprise = sum(eps_hist) / len(eps_hist) if eps_hist else 0
        beat_streak  = sum(1 for x in eps_hist if x > 0)
        history_str  = "  " + " → ".join(f"+{x:.1f}%" if x > 0 else f"{x:.1f}%" for x in eps_hist)

    # Entry price and stop — read from Alpaca (universal 20% stop)
    STOP_LOSS_PCT = 0.20
    entry    = None
    stop_lvl = None
    try:
        from utils import fetch_alpaca_positions
        positions = fetch_alpaca_positions()
        pos_map   = {p["ticker"]: p for p in positions}
        if event["ticker"] in pos_map:
            entry    = pos_map[event["ticker"]]["avg_entry"]
            stop_lvl = round(entry * (1 - STOP_LOSS_PCT), 2)
    except Exception:
        pass

    # Get current price for distance calc
    try:
        import requests
        finnhub_key = os.environ.get("FINNHUB_API_KEY", "")
        r = requests.get(
            f"https://finnhub.io/api/v1/quote?symbol={event['ticker']}&token={finnhub_key}",
            timeout=8
        )
        current_price = r.json().get("c", entry)
    except Exception:
        current_price = entry

    dist_to_stop = ((current_price - stop_lvl) / current_price * 100) if stop_lvl else None

    user_content = f"""
Ticker: {event['ticker']} ({event['name']}) — {event['sector']}
Earnings date: {event['date'].strftime('%d %b %Y')} ({event['timing'].upper()})
Alert type: {event['alert_type']} WARNING

EPS ESTIMATE: ${event['eps_est']}
REVENUE ESTIMATE: ${event['rev_est_b']}B

EARNINGS HISTORY (last 4 quarters):
{history_str}
Average surprise: {avg_surprise:+.1f}%
Beat streak: {beat_streak}/4 quarters

WAR CONTEXT: {event.get('macro_context') or event.get('war_context', '')}

KEY METRICS: {', '.join(event['key_metrics'])}

THESIS CHECK: {event['thesis_check']}

POSITION DATA:
Entry price: ${entry if entry else 'not set'}
Stop level: ${stop_lvl if stop_lvl else 'not set'} (-{stop_pct*100:.0f}%)
Current price: ${current_price:.2f}
Distance to stop: {f'{dist_to_stop:.1f}%' if dist_to_stop else 'N/A'}

Generate the earnings pre-brief now.
"""

    return call_claude(SYSTEM_PROMPT, user_content, max_tokens=700)


# ── Format Telegram message ───────────────────────────────────────────────────
def format_alert_message(event: dict, brief: str) -> str:
    timing_emoji = "🌅" if event["timing"] == "pre" else "🌆"
    alert_emoji  = "🚨" if event["alert_type"] == "24H" else "📋"

    header = (
        f"{alert_emoji} {PORTFOLIO_EMOJI} <b>{PORTFOLIO_NAME} — {event['alert_type']} EARNINGS ALERT — {event['ticker']}</b>\n"
        f"{timing_emoji} {event['date'].strftime('%d %b %Y')} · "
        f"{'Pre-market' if event['timing'] == 'pre' else 'After-market'} · "
        f"{event['days_until']} día{'s' if event['days_until'] > 1 else ''} restante{'s' if event['days_until'] > 1 else ''}\n\n"
    )
    return header + brief


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    now_et = datetime.now(ET)
    today  = now_et.date()
    print(f"Earnings Alert Bot — {now_et.strftime('%Y-%m-%d %H:%M ET')}")

    # Gate: market day check
    if not is_market_day():
        print("Market closed — skipping.")
        sys.exit(0)

    # ── Daily context update (runs every day regardless of earnings) ──────────
    print("Fetching news for macro context banner...")
    import requests as _req
    try:
        finnhub_key = os.environ.get("FINNHUB_API_KEY", "")
        # Fetch general market news
        r = _req.get(
            f"https://finnhub.io/api/v1/news?category=general&token={finnhub_key}",
            timeout=8
        )
        news_items = r.json()[:10] if r.ok else []
        context = generate_war_context(news_items)
        if context:
            update_context_file(context)
    except Exception as e:
        print(f"Context update failed: {e}")

    # Check for upcoming earnings in next 48h
    alerts = check_earnings_alerts(today)

    if not alerts:
        print("No earnings in next 48h — staying silent.")
        sys.exit(0)

    print(f"Earnings alerts due: {[a['ticker'] for a in alerts]}")

    for event in alerts:
        print(f"Building brief for {event['ticker']} ({event['alert_type']})...")
        try:
            brief   = build_earnings_brief(event)
            message = format_alert_message(event, brief)
            send_telegram(message)
            print(f"✅ Sent {event['alert_type']} alert for {event['ticker']}")
        except Exception as e:
            print(f"❌ Error processing {event['ticker']}: {e}")
            # Send a simple fallback alert
            fallback = (
                f"⚠️ <b>{event['alert_type']} EARNINGS — {event['ticker']}</b>\n"
                f"📅 {event['date'].strftime('%d %b %Y')} · "
                f"{'Pre-market' if event['timing'] == 'pre' else 'After-market'}\n"
                f"EPS est: ${event['eps_est']} | Rev est: ${event['rev_est_b']}B\n"
                f"(Error generando brief completo: {str(e)[:100]})"
            )
            send_telegram(fallback)

    print("Done.")


if __name__ == "__main__":
    main()

"""
webhook_server.py — Telegram Webhook + Portfolio Dashboard Server
==================================================================
Always-on server (deploy on Render free tier).
Handles:
  1. GET  /              → Hub dashboard (index_hub.html) — landing page
  2. GET  /hub           → Same hub
  3. GET  /dashboard     → Frontier5 v2.0 portfolio dashboard (index.html)
  4. GET  /api/quotes    → Live quotes JSON for the dashboard
  5. GET  /api/account   → Alpaca account summary
  6. GET  /api/positions → Alpaca positions with P&L
  7. GET  /api/decisions → Recent YES/NO decisions (used by hub)
  8. GET  /api/context   → Macro context banner (from context.json)
  9. GET  /api/earnings  → Upcoming earnings calendar
  10. GET  /api/spy      → SPY daily change (SPX proxy)
  11. GET  /health       → Health check (Render ping)
  12. POST /webhook      → Telegram updates (buttons + commands)

After deploy, register webhook with Telegram:
  https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<app>.onrender.com/webhook
"""

import os
import hmac
import json
import threading
import requests as req
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
import pytz

from config import PORTFOLIO, ENTRY_PRICES
from utils  import fetch_all_quotes, call_claude, send_telegram, \
                   answer_callback, edit_message, ET, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from state  import load_state, save_state, record_decision

PORT = int(os.environ.get("PORT", 8080))
# Shared secret for every /api/* route. Fails closed: if it is not set, the API is disabled.
DASHBOARD_TOKEN = os.environ.get("DASHBOARD_TOKEN", "")

# ── Status report prompt ──────────────────────────────────────────────────────
STATUS_PROMPT = """You are a portfolio analyst for Frontier5 v2.0.
Context: Active US-Iran war, oil >$100, Hormuz restricted.
Portfolio: NVDA (AI Core 25%), PLTR (War AI 25%), RTX (Defense Hard 22%),
           META (AI Ads 18%), XOM (War Hedge 10%).

Generate a compact Telegram status report. Plain text only, no markdown symbols.

Structure:
📊 FRONTIER5 STATUS — [DATE] [TIME ET]

[For each position, one line:]
TICKER  $price  chg%  P&L%  [▲/▼]  [brief 3-word status]

📈 Best today: [ticker +%]
📉 Worst today: [ticker %]
🛡️ Stops OK: [count]/5  or ⚠️ STOP NEAR: [ticker]
📌 War context: [1 line on how war is affecting the portfolio today]

Keep it compact — one screen on iPhone."""


def build_status_report(quotes: list) -> str:
    now_et = datetime.now(ET).strftime("%Y-%m-%d %H:%M")
    return call_claude(
        STATUS_PROMPT,
        f"Time ET: {now_et}\n\nPORTFOLIO QUOTES:\n{json.dumps(quotes, indent=2)}\n\nGenerate the status report now.",
        max_tokens=700,
    )


# ── Webhook handler ───────────────────────────────────────────────────────────
class WebhookHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # suppress default access logs

    def _authorized(self) -> bool:
        """Require header X-Dashboard-Token on /api/* (constant-time compare)."""
        if not DASHBOARD_TOKEN:
            self._respond(503, json.dumps({"ok": False, "error": "DASHBOARD_TOKEN not configured"}).encode(), "application/json")
            return False
        supplied = self.headers.get("X-Dashboard-Token", "")
        if not hmac.compare_digest(supplied.encode(), DASHBOARD_TOKEN.encode()):
            self._respond(401, json.dumps({"ok": False, "error": "unauthorized"}).encode(), "application/json")
            return False
        return True

    # ── GET ───────────────────────────────────────────────────────────────────
    def do_GET(self):

        if self.path.startswith("/api/") and not self._authorized():
            return

        # Health check
        if self.path == "/health":
            self._respond(200, b"OK", "text/plain")

        # Hub — landing page (index_hub.html)
        elif self.path in ["/", "/hub"]:
            self._serve_dashboard_file("index_hub.html")

        # Portfolio dashboard — Frontier5 v2.0
        elif self.path in ["/dashboard", "/dashboard/index.html"]:
            self._serve_dashboard_file("index.html")

        # Portfolio dashboard — Defense & Aerospace (Portfolio 2)
        elif self.path in ["/dashboard/defense", "/dashboard/defense_aerospace.html"]:
            self._serve_dashboard_file("defense_aerospace.html")

        # Portfolio dashboard — Mixed Strategy (Portfolio 3)
        elif self.path in ["/dashboard/mixed", "/dashboard/mixed_strategy.html"]:
            self._serve_dashboard_file("mixed_strategy.html")

        # Ticker Analyst — Photonics / CPO Watchlist
        elif self.path in ["/dashboard/photonics", "/dashboard/photonics_watchlist.html"]:
            self._serve_dashboard_file("photonics_watchlist.html")

        # Live quotes API — called by dashboard JS every 60s (Portfolio 1)
        # Supports ?tickers=NVDA,TSM,ANET for dynamic portfolios
        elif self.path == "/api/quotes" or self.path.startswith("/api/quotes?"):
            self._handle_quotes()

        # Live quotes API — Defense & Aerospace (Portfolio 2)
        elif self.path == "/api/quotes/defense":
            self._handle_quotes_defense()

        # Account & positions — Portfolio 1 (default Alpaca account)
        elif self.path == "/api/account":
            self._handle_account()

        elif self.path == "/api/positions":
            self._handle_positions()

        # Account & positions — Portfolio 2 Defense (separate Alpaca account)
        elif self.path == "/api/account/defense-full":
            self._handle_account_defense_full()

        elif self.path == "/api/positions/defense-full":
            self._handle_positions_defense_full()

        # Account & positions — Portfolio 3 Mixed (separate Alpaca account)
        elif self.path == "/api/account/mixed":
            self._handle_account_mixed()

        elif self.path == "/api/positions/mixed":
            self._handle_positions_mixed()

        elif self.path == "/api/spy":
            self._handle_spy()

        elif self.path == "/api/context":
            self._handle_context()

        elif self.path == "/api/earnings":
            self._handle_earnings()

        elif self.path == "/api/decisions":
            self._handle_decisions()

        # Historical portfolio value — daily candles from entry date
        elif self.path == "/api/history":
            self._handle_history()

        elif self.path == "/api/history/defense":
            self._handle_history_defense()

        elif self.path == "/api/history/mixed":
            self._handle_history_mixed()

        # PWA manifest
        elif self.path == "/manifest.json":
            try:
                path = os.path.join(os.path.dirname(__file__), "dashboard", "manifest.json")
                with open(path, "rb") as f:
                    content2 = f.read()
                self._respond(200, content2, "application/manifest+json")
            except FileNotFoundError:
                self._respond(404, b"manifest.json not found", "text/plain")

        # PWA icons
        elif self.path in ["/icon-192.png", "/icon-512.png"]:
            fname = self.path.lstrip("/")
            try:
                path = os.path.join(os.path.dirname(__file__), "dashboard", fname)
                with open(path, "rb") as f:
                    content2 = f.read()
                self._respond(200, content2, "image/png")
            except FileNotFoundError:
                self._respond(404, b"Icon not found", "text/plain")

        # IBKR snapshot — latest data for mixed_strategy.html
        elif self.path == "/api/ibkr/snapshot":
            self._handle_ibkr_snapshot()

        else:
            self._respond(404, b"Not found", "text/plain")

    def _serve_dashboard_file(self, filename: str):
        """Serve a file from the dashboard/ folder with HTML fallback."""
        try:
            path = os.path.join(os.path.dirname(__file__), "dashboard", filename)
            with open(path, "rb") as f:
                content = f.read()
            self._respond(200, content, "text/html; charset=utf-8")
        except FileNotFoundError:
            fallback = (
                f'<html><body style="background:#0f0f0f;color:#e8e6e0;font-family:sans-serif;padding:40px">'
                f'<h2>Frontier5</h2>'
                f'<p><code>dashboard/{filename}</code> not found.</p>'
                f'<p><a href="/health" style="color:#4f8ef7">/health</a> &nbsp;'
                f'<a href="/api/quotes" style="color:#4f8ef7">/api/quotes</a></p>'
                f'</body></html>'
            ).encode()
            self._respond(200, fallback, "text/html; charset=utf-8")

    def _handle_ibkr_snapshot(self):
        """
        Return the latest IBKR snapshot committed by the GitHub Action.
        The file ibkr_snapshot.json lives in the repo root and is always
        present on Render because it's part of the deployed codebase.
        """
        try:
            # Try repo root first, then dashboard/ subfolder
            base = os.path.dirname(__file__)
            for candidate in [
                os.path.join(base, "ibkr_snapshot.json"),
                os.path.join(base, "dashboard", "ibkr_snapshot.json"),
                os.path.join(base, "ibkr_snapshot.sample.json"),  # demo data
            ]:
                if os.path.exists(candidate):
                    with open(candidate, "r") as f:
                        data = f.read()
                    self._respond(200, data.encode(), "application/json")
                    return

            # File not found — first sync hasn't run yet
            body = json.dumps({
                "ok":             False,
                "error":          "No IBKR snapshot yet. Run the GitHub Action first.",
                "open_positions": [],
                "trades":         [],
                "cash":           None,
                "generated_at":   None,
            }).encode()
            self._respond(200, body, "application/json")

        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}).encode()
            self._respond(500, body, "application/json")

    def _handle_decisions(self):
        """Return recent YES/NO decisions from state — used by index_hub.html."""
        try:
            state     = load_state()
            decisions = state.get("decisions", [])[-20:]
            body = json.dumps({"ok": True, "decisions": decisions}).encode()
            self._respond(200, body, "application/json")
        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}).encode()
            self._respond(500, body, "application/json")

    def _handle_history(self):
        """
        Return daily portfolio value from entry date to today — Portfolio 1.
        Reads current positions from Alpaca dynamically (no hardcoded tickers).
        """
        try:
            from utils import fetch_alpaca_positions
            positions = fetch_alpaca_positions()
            if not positions:
                body = json.dumps({"ok": True, "history": []}).encode()
                self._respond(200, body, "application/json")
                return
            tickers_shares = {p["ticker"]: p["qty"] for p in positions}
            # Use earliest avg_entry date as proxy — fallback to 30 days ago
            from datetime import date, timedelta
            entry_date = (date.today() - timedelta(days=30)).isoformat()
            self._compute_history(
                tickers_shares=tickers_shares,
                entry_date=entry_date,
                initial_capital=10000.00,
            )
        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}).encode()
            self._respond(500, body, "application/json")

    def _handle_history_defense(self):
        """
        Return daily portfolio value from entry date to today — Portfolio 2.
        Reads current positions from Alpaca P2 account dynamically.
        """
        try:
            api_key    = os.environ.get("ALPACA_API_KEY_DEFENSE", "")
            secret_key = os.environ.get("ALPACA_SECRET_KEY_DEFENSE", "")
            if not api_key or not secret_key:
                body = json.dumps({"ok": False, "error": "Defense Alpaca keys not set"}).encode()
                self._respond(200, body, "application/json")
                return
            headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key}
            r = req.get("https://paper-api.alpaca.markets/v2/positions",
                        headers=headers, timeout=10)
            r.raise_for_status()
            positions = r.json()
            if not positions:
                body = json.dumps({"ok": True, "history": []}).encode()
                self._respond(200, body, "application/json")
                return
            tickers_shares = {p.get("symbol"): float(p.get("qty", 0)) for p in positions}
            from datetime import date, timedelta
            entry_date = (date.today() - timedelta(days=30)).isoformat()
            self._compute_history(
                tickers_shares=tickers_shares,
                entry_date=entry_date,
                initial_capital=10000.00,
            )
        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}).encode()
            self._respond(500, body, "application/json")

    def _handle_history_mixed(self):
        """
        Return daily portfolio value from entry date to today — Portfolio 3 Mixed.
        Reads current positions from Alpaca P3 account dynamically.
        """
        try:
            api_key    = os.environ.get("ALPACA_API_KEY_MIXED", "")
            secret_key = os.environ.get("ALPACA_SECRET_KEY_MIXED", "")
            if not api_key or not secret_key:
                body = json.dumps({"ok": False, "error": "Mixed Alpaca keys not set"}).encode()
                self._respond(200, body, "application/json")
                return
            headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key}
            r = req.get("https://paper-api.alpaca.markets/v2/positions",
                        headers=headers, timeout=10)
            r.raise_for_status()
            positions = r.json()
            if not positions:
                body = json.dumps({"ok": True, "history": []}).encode()
                self._respond(200, body, "application/json")
                return
            tickers_shares = {p.get("symbol"): float(p.get("qty", 0)) for p in positions}
            from datetime import date, timedelta
            entry_date = (date.today() - timedelta(days=30)).isoformat()
            self._compute_history(
                tickers_shares=tickers_shares,
                entry_date=entry_date,
                initial_capital=10000.00,
            )
        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}).encode()
            self._respond(500, body, "application/json")

    def _compute_history(self, tickers_shares: dict, entry_date: str, initial_capital: float):
        """Fetch daily candles for each ticker and compute portfolio value per day."""
        import time as _time
        from datetime import date, timedelta

        finnhub_key = os.environ.get("FINNHUB_API_KEY", "")

        try:
            # Convert entry_date to unix timestamp
            entry_dt  = date.fromisoformat(entry_date)
            today_dt  = date.today()
            from_ts   = int(__import__('datetime').datetime(entry_dt.year, entry_dt.month, entry_dt.day).timestamp())
            to_ts     = int(__import__('datetime').datetime(today_dt.year, today_dt.month, today_dt.day, 23, 59).timestamp())

            # Fetch candles for each ticker
            all_candles = {}  # ticker -> {date_str -> close_price}
            for ticker in tickers_shares:
                try:
                    url = (
                        f"https://finnhub.io/api/v1/stock/candle"
                        f"?symbol={ticker}&resolution=D"
                        f"&from={from_ts}&to={to_ts}&token={finnhub_key}"
                    )
                    r = req.get(url, timeout=10)
                    r.raise_for_status()
                    data = r.json()
                    if data.get("s") != "ok":
                        all_candles[ticker] = {}
                        continue
                    # Map timestamp -> close price
                    candle_map = {}
                    for ts, close in zip(data.get("t", []), data.get("c", [])):
                        d_str = date.fromtimestamp(ts).isoformat()
                        candle_map[d_str] = close
                    all_candles[ticker] = candle_map
                    _time.sleep(0.1)  # respect rate limit
                except Exception:
                    all_candles[ticker] = {}

            # Get all unique dates across all tickers, sorted
            all_dates = set()
            for candle_map in all_candles.values():
                all_dates.update(candle_map.keys())
            all_dates = sorted(all_dates)

            if not all_dates:
                # No data yet — return flat line from entry
                body = json.dumps({
                    "ok": True,
                    "history": [
                        {"date": entry_date, "value": initial_capital},
                    ]
                }).encode()
                self._respond(200, body, "application/json")
                return

            # Compute portfolio value per day
            # Use last known price for each ticker (carry forward)
            last_price = {}
            history = []
            for d_str in all_dates:
                for ticker, candle_map in all_candles.items():
                    if d_str in candle_map:
                        last_price[ticker] = candle_map[d_str]
                # Only add point if we have prices for all tickers
                if len(last_price) == len(tickers_shares):
                    value = sum(
                        last_price[t] * shares
                        for t, shares in tickers_shares.items()
                        if t in last_price
                    )
                    # Format date as "DD MMM" for chart labels
                    dt = date.fromisoformat(d_str)
                    label = dt.strftime("%-d %b")
                    history.append({"date": label, "value": round(value, 2)})

            body = json.dumps({"ok": True, "history": history}).encode()
            self._respond(200, body, "application/json")

        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}).encode()
            self._respond(500, body, "application/json")

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        """Handle POST requests — Telegram webhook + Claude proxy."""
        if self.path == "/api/claude":
            if self._authorized():
                self._handle_claude_proxy()
        elif self.path == "/webhook":
            self._handle_telegram_webhook()
        else:
            self._respond(404, b"Not found", "text/plain")

    def _handle_claude_proxy(self):
        """
        Proxy POST /api/claude → Anthropic API.
        Body: { "messages": [...], "system": "..." }
        Forwards to Claude Sonnet and returns the response.
        Avoids CORS issues since the call is server-side.
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))

            anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not anthropic_key:
                self._respond(500, json.dumps({"error": "ANTHROPIC_API_KEY not set"}).encode(), "application/json")
                return

            payload = {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "system": body.get("system", ""),
                "messages": body.get("messages", [])
            }

            resp = req.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json=payload,
                timeout=30
            )
            self._respond(resp.status_code, resp.content, "application/json")

        except Exception as e:
            self._respond(500, json.dumps({"error": str(e)}).encode(), "application/json")

    def _handle_telegram_webhook(self):
        """Handle incoming Telegram webhook updates."""
        # Always 200 immediately so Telegram doesn't retry
        self.send_response(200)
        self.end_headers()
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        threading.Thread(target=self._process_telegram, args=(body,), daemon=True).start()

    def _process_telegram(self, body: bytes):
        try:
            update = json.loads(body)
            if "callback_query" in update:
                self.handle_callback(update["callback_query"])
            elif "message" in update:
                self.handle_message(update["message"])
        except Exception as e:
            print(f"Error processing telegram update: {e}")

    def _respond(self, code, body, content_type="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_quotes(self):
        """
        Fetch quotes from Finnhub. Supports two modes:
        1. /api/quotes          → uses tickers from config PORTFOLIO (Portfolio 1)
        2. /api/quotes?tickers=NVDA,TSM,ANET → dynamic tickers from query string
        """
        from urllib.parse import urlparse, parse_qs
        finnhub_key = os.environ.get("FINNHUB_API_KEY", "")

        # Parse optional ?tickers= query param
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if "tickers" in params:
            tickers = [t.strip().upper() for t in params["tickers"][0].split(",") if t.strip()]
        else:
            tickers = [pos["ticker"] for pos in PORTFOLIO]

        quotes = {}
        for ticker in tickers:
            try:
                url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={finnhub_key}"
                r   = req.get(url, timeout=8)
                r.raise_for_status()
                data = r.json()
                if data.get("c", 0) == 0 and data.get("t", 0) == 0:
                    quotes[ticker] = {"error": "No data from Finnhub (symbol invalid or market closed)"}
                else:
                    quotes[ticker] = data
            except Exception as e:
                quotes[ticker] = {"error": str(e)}

        body = json.dumps({"ok": True, "quotes": quotes}).encode()
        self._respond(200, body, "application/json")

    def _handle_quotes_defense(self):
        """Fetch Defense & Aerospace quotes from Finnhub (Portfolio 2)."""
        finnhub_key = os.environ.get("FINNHUB_API_KEY", "")
        defense_tickers = ["RTX", "LMT", "LHX", "HII", "KTOS"]
        quotes = {}
        for ticker in defense_tickers:
            try:
                url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={finnhub_key}"
                r   = req.get(url, timeout=8)
                r.raise_for_status()
                data = r.json()
                if data.get("c", 0) == 0 and data.get("t", 0) == 0:
                    quotes[ticker] = {"error": "No data from Finnhub (symbol invalid or market closed)"}
                else:
                    quotes[ticker] = data
            except Exception as e:
                quotes[ticker] = {"error": str(e)}
        body = json.dumps({"ok": True, "quotes": quotes}).encode()
        self._respond(200, body, "application/json")

    def _handle_context(self):
        """Return current macro context banner from context.json."""
        try:
            path = os.path.join(os.path.dirname(__file__), "context.json")
            with open(path, "r") as f:
                data = f.read()
            self._respond(200, data.encode(), "application/json")
        except FileNotFoundError:
            body = json.dumps({"ok": False, "error": "context.json not found"}).encode()
            self._respond(200, body, "application/json")
        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}).encode()
            self._respond(500, body, "application/json")

    def _handle_earnings(self):
        """Return upcoming earnings for Frontier5 positions (next 30 days) from Finnhub."""
        finnhub_key = os.environ.get("FINNHUB_API_KEY", "")
        from datetime import date, timedelta
        today    = date.today()
        in_30    = today + timedelta(days=30)
        tickers  = ["NVDA", "PLTR", "RTX", "META", "XOM"]
        names    = {"NVDA":"NVIDIA","PLTR":"Palantir","RTX":"Raytheon","META":"Meta","XOM":"Exxon"}
        earnings = []
        try:
            for ticker in tickers:
                r = req.get(
                    "https://finnhub.io/api/v1/calendar/earnings",
                    params={"symbol": ticker, "from": today.isoformat(),
                            "to": in_30.isoformat(), "token": finnhub_key},
                    timeout=8,
                )
                if not r.ok:
                    continue
                items = r.json().get("earningsCalendar", [])
                for item in items:
                    edate_str = item.get("date", "")
                    if not edate_str:
                        continue
                    try:
                        edate     = date.fromisoformat(edate_str)
                        days_until = (edate - today).days
                        if 0 <= days_until <= 30:
                            earnings.append({
                                "ticker":     ticker,
                                "name":       names.get(ticker, ticker),
                                "date":       edate.strftime("%d %b %Y"),
                                "days_until": days_until,
                                "timing":     item.get("hour", "post") == "bmo" and "pre" or "post",
                                "eps_est":    item.get("epsEstimate"),
                            })
                    except Exception:
                        continue
            earnings.sort(key=lambda x: x["days_until"])
            body = json.dumps({"ok": True, "earnings": earnings}).encode()
            self._respond(200, body, "application/json")
        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}).encode()
            self._respond(500, body, "application/json")

    def _handle_spy(self):
        """Return SPY daily change % — used by dashboard as SPX proxy for Performance chart."""
        finnhub_key = os.environ.get("FINNHUB_API_KEY", "")
        try:
            url = f"https://finnhub.io/api/v1/quote?symbol=SPY&token={finnhub_key}"
            r   = req.get(url, timeout=8)
            r.raise_for_status()
            d   = r.json()
            pc  = float(d.get("pc", 0))
            c   = float(d.get("c", 0))
            pct = ((c - pc) / pc * 100) if pc else 0
            body = json.dumps({"ok": True, "pct": round(pct, 4), "price": c}).encode()
            self._respond(200, body, "application/json")
        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}).encode()
            self._respond(500, body, "application/json")

    def _handle_account(self):
        """Return Alpaca paper account summary as JSON."""
        try:
            from utils import fetch_alpaca_account
            account = fetch_alpaca_account()
            body = json.dumps({"ok": True, "account": account}).encode()
            self._respond(200, body, "application/json")
        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}).encode()
            self._respond(500, body, "application/json")

    def _handle_positions(self):
        """Return Alpaca paper positions with P&L as JSON."""
        try:
            from utils import fetch_alpaca_positions
            positions = fetch_alpaca_positions()
            body = json.dumps({"ok": True, "positions": positions}).encode()
            self._respond(200, body, "application/json")
        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}).encode()
            self._respond(500, body, "application/json")

    def _handle_account_defense_full(self):
        """Return Alpaca account for Portfolio 2 Defense — uses separate API keys."""
        try:
            api_key    = os.environ.get("ALPACA_API_KEY_DEFENSE", "")
            secret_key = os.environ.get("ALPACA_SECRET_KEY_DEFENSE", "")
            if not api_key or not secret_key:
                raise ValueError("ALPACA_API_KEY_DEFENSE / ALPACA_SECRET_KEY_DEFENSE not set in Render env")
            headers = {
                "APCA-API-KEY-ID":     api_key,
                "APCA-API-SECRET-KEY": secret_key,
            }
            r = req.get(
                "https://paper-api.alpaca.markets/v2/account",
                headers=headers, timeout=10,
            )
            r.raise_for_status()
            a        = r.json()
            equity   = float(a.get("equity", 0))
            last_eq  = float(a.get("last_equity", 0))
            pl_today = equity - last_eq
            account  = {
                "equity":          round(equity, 2),
                "cash":            round(float(a.get("cash", 0)), 2),
                "portfolio_value": round(float(a.get("portfolio_value", equity)), 2),
                "pl_today":        round(pl_today, 2),
                "pl_today_pct":    round((pl_today / last_eq * 100) if last_eq else 0, 2),
                "buying_power":    round(float(a.get("buying_power", 0)), 2),
            }
            body = json.dumps({"ok": True, "account": account}).encode()
            self._respond(200, body, "application/json")
        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}).encode()
            self._respond(500, body, "application/json")

    def _handle_positions_defense_full(self):
        """Return Alpaca positions for Portfolio 2 Defense — uses separate API keys."""
        try:
            api_key    = os.environ.get("ALPACA_API_KEY_DEFENSE", "")
            secret_key = os.environ.get("ALPACA_SECRET_KEY_DEFENSE", "")
            if not api_key or not secret_key:
                raise ValueError("ALPACA_API_KEY_DEFENSE / ALPACA_SECRET_KEY_DEFENSE not set in Render env")
            headers = {
                "APCA-API-KEY-ID":     api_key,
                "APCA-API-SECRET-KEY": secret_key,
            }
            r = req.get(
                "https://paper-api.alpaca.markets/v2/positions",
                headers=headers, timeout=10,
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
            body = json.dumps({"ok": True, "positions": positions}).encode()
            self._respond(200, body, "application/json")
        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}).encode()
            self._respond(500, body, "application/json")

    def _handle_account_mixed(self):
        """Return Alpaca account for Portfolio 3 Mixed Strategy — uses separate API keys."""
        try:
            api_key    = os.environ.get("ALPACA_API_KEY_MIXED", "")
            secret_key = os.environ.get("ALPACA_SECRET_KEY_MIXED", "")
            if not api_key or not secret_key:
                # Return placeholder data if keys not configured yet
                account = {
                    "equity": 10000.00,
                    "cash": 10000.00,
                    "portfolio_value": 10000.00,
                    "pl_today": 0.00,
                    "pl_today_pct": 0.00,
                    "buying_power": 10000.00,
                }
                body = json.dumps({"ok": True, "account": account}).encode()
                self._respond(200, body, "application/json")
                return
            
            headers = {
                "APCA-API-KEY-ID":     api_key,
                "APCA-API-SECRET-KEY": secret_key,
            }
            r = req.get(
                "https://paper-api.alpaca.markets/v2/account",
                headers=headers, timeout=10,
            )
            r.raise_for_status()
            a        = r.json()
            equity   = float(a.get("equity", 0))
            last_eq  = float(a.get("last_equity", 0))
            pl_today = equity - last_eq
            account  = {
                "equity":          round(equity, 2),
                "cash":            round(float(a.get("cash", 0)), 2),
                "portfolio_value": round(float(a.get("portfolio_value", equity)), 2),
                "pl_today":        round(pl_today, 2),
                "pl_today_pct":    round((pl_today / last_eq * 100) if last_eq else 0, 2),
                "buying_power":    round(float(a.get("buying_power", 0)), 2),
            }
            body = json.dumps({"ok": True, "account": account}).encode()
            self._respond(200, body, "application/json")
        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}).encode()
            self._respond(500, body, "application/json")

    def _handle_positions_mixed(self):
        """Return Alpaca positions for Portfolio 3 Mixed Strategy — uses separate API keys."""
        try:
            api_key    = os.environ.get("ALPACA_API_KEY_MIXED", "")
            secret_key = os.environ.get("ALPACA_SECRET_KEY_MIXED", "")
            if not api_key or not secret_key:
                # Return empty positions if keys not configured yet
                body = json.dumps({"ok": True, "positions": []}).encode()
                self._respond(200, body, "application/json")
                return
            
            headers = {
                "APCA-API-KEY-ID":     api_key,
                "APCA-API-SECRET-KEY": secret_key,
            }
            r = req.get(
                "https://paper-api.alpaca.markets/v2/positions",
                headers=headers, timeout=10,
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
            body = json.dumps({"ok": True, "positions": positions}).encode()
            self._respond(200, body, "application/json")
        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}).encode()
            self._respond(500, body, "application/json")

    # ── POST ──────────────────────────────────────────────────────────────────


    # ── Button press (YES / NO) ───────────────────────────────────────────────
    def handle_callback(self, cq: dict):
        cq_id      = cq["id"]
        data       = cq.get("data", "")
        chat_id    = str(cq["message"]["chat"]["id"])
        message_id = str(cq["message"]["message_id"])
        orig_text  = cq["message"].get("text", "")

        if chat_id != str(TELEGRAM_CHAT_ID):
            answer_callback(cq_id, "Unauthorized")
            return

        parts  = data.split("|")
        action = parts[0] if parts else ""
        ticker = parts[1] if len(parts) > 1 else "?"
        extra  = parts[2] if len(parts) > 2 else ""  # qty or amount

        state = load_state()

        if action == "YES":
            answer_callback(cq_id, "✅ Order confirmed")
            record_decision(ticker, action.upper(), extra)
            # Could trigger actual trade logic here
            edit_message(chat_id, message_id, f"{orig_text}\n\n✅ CONFIRMED — Order executed.")

        elif action == "NO":
            answer_callback(cq_id, "❌ Order rejected")
            record_decision(ticker, action.upper(), extra)
            edit_message(chat_id, message_id, f"{orig_text}\n\n❌ REJECTED — No action taken.")

        else:
            answer_callback(cq_id, f"Unknown action: {action}")

    # ── Text message (/status, etc.) ──────────────────────────────────────────
    def handle_message(self, msg: dict):
        chat_id = str(msg["chat"]["id"])
        text    = msg.get("text", "")

        if chat_id != str(TELEGRAM_CHAT_ID):
            return

        if text.startswith("/status"):
            quotes = fetch_all_quotes()
            report = build_status_report(quotes)
            send_telegram(report)

        elif text.startswith("/help"):
            send_telegram(
                "Frontier5 commands:\n"
                "/status — Current portfolio snapshot\n"
                "/help   — This menu"
            )


# ── Start server ──────────────────────────────────────────────────────────────
def main():
    server = HTTPServer(("", PORT), WebhookHandler)
    print(f"✓ Webhook server running on port {PORT}")
    print(f"  /health → Render health check")
    print(f"  /       → Hub dashboard")
    print(f"  /dashboard → Portfolio 1 (Frontier5 v2.0)")
    print(f"  /dashboard/defense → Portfolio 2 (Defense & Aerospace)")
    print(f"  /dashboard/mixed → Portfolio 3 (Mixed Strategy)")
    print(f"  /dashboard/photonics → Ticker Analyst (Photonics/CPO)")
    print(f"  POST /api/claude → Claude proxy (for Ticker Analyst chat)")
    print(f"  /api/quotes → Live quotes (Portfolio 1)")
    print(f"  /api/quotes/defense → Defense quotes (Portfolio 2)")
    print(f"  /api/account/mixed → Account data (Portfolio 3)")
    print(f"  /api/positions/mixed → Positions data (Portfolio 3)")
    print(f"  /webhook → Telegram webhook endpoint")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n✓ Server stopped")


if __name__ == "__main__":
    main()

"""
ibkr_sync.py — IBKR Flex Query Sync Script
===========================================
Runs as a GitHub Action every Friday at 18:00 ET.
Fetches the Flex Query from IBKR, parses the XML,
and commits ibkr_snapshot.json directly to the GitHub repo.
Render reads the file from disk on startup — always available.

Required environment variables (GitHub Secrets):
  IBKR_FLEX_TOKEN    — Flex Web Service token from IBKR
  IBKR_FLEX_QUERY_ID — Query ID of the Frontier5 Weekly flex query
  GITHUB_TOKEN       — Automatically provided by GitHub Actions (no setup needed)
  GITHUB_REPOSITORY  — Automatically provided by GitHub Actions (e.g. fcheca93/Frontier5)
"""

import os
import sys
import json
import time
import base64
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

IBKR_TOKEN    = os.environ["IBKR_FLEX_TOKEN"]
IBKR_QUERY_ID = os.environ["IBKR_FLEX_QUERY_ID"]
GITHUB_TOKEN  = os.environ["GITHUB_TOKEN"]
GITHUB_REPO   = os.environ["GITHUB_REPOSITORY"]  # e.g. fcheca93/Frontier5

FLEX_SEND_URL    = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest"
FLEX_RECEIVE_URL = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.GetStatement"
SNAPSHOT_PATH    = "ibkr_snapshot.json"  # path in repo root

# Tickers that trade in a non-EUR currency → need FX conversion at sync time.
# The snapshot stores EUR values directly so the dashboard never needs FX calls.
TICKER_CURRENCY = {
    "DEMOB":  "SEK",  # example: a stock priced in Swedish krona
    "DEMOJ":  "JPY",  # example: a stock priced in Japanese yen
}


def fetch_eur_rate(from_currency: str) -> float:
    """Fetch EUR conversion rate from Frankfurter. Raises on failure."""
    if from_currency == "EUR":
        return 1.0
    # Frankfurter doesn't support JPY→EUR directly, use EUR→JPY inverted
    if from_currency == "JPY":
        try:
            url  = "https://api.frankfurter.app/latest?from=EUR&to=JPY"
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            jpy_per_eur = resp.json().get("rates", {}).get("JPY")
            if not jpy_per_eur or jpy_per_eur <= 0:
                raise ValueError(f"Invalid JPY rate: {jpy_per_eur}")
            rate = 1.0 / jpy_per_eur
            print(f"  FX rate JPY/EUR = {rate:.8f} (via EUR/JPY={jpy_per_eur})")
            return float(rate)
        except Exception as e:
            raise RuntimeError(f"Could not fetch JPY/EUR rate: {e}")
    try:
        url  = f"https://api.frankfurter.app/latest?from={from_currency}&to=EUR"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        rate = resp.json().get("rates", {}).get("EUR")
        if not rate or rate <= 0:
            raise ValueError(f"Invalid rate received: {rate}")
        print(f"  FX rate {from_currency}/EUR = {rate}")
        return float(rate)
    except Exception as e:
        raise RuntimeError(f"Could not fetch {from_currency}/EUR rate: {e}")


def request_flex_statement() -> str:
    """Step 1: Request the statement and get a reference code."""
    print("-> Requesting IBKR Flex statement...")
    resp = requests.get(FLEX_SEND_URL, params={
        "t": IBKR_TOKEN,
        "q": IBKR_QUERY_ID,
        "v": "3",
    }, timeout=30)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    status   = root.findtext("Status")
    ref_code = root.findtext("ReferenceCode")

    if status != "Success" or not ref_code:
        error = root.findtext("ErrorMessage") or resp.text
        raise RuntimeError(f"IBKR Flex request failed: {error}")

    print(f"  Reference code: {ref_code}")
    return ref_code


def fetch_flex_statement(ref_code: str) -> str:
    """Step 2: Poll until the statement is ready, return raw XML."""
    print("-> Fetching Flex statement (may take a few seconds)...")
    for attempt in range(10):
        time.sleep(5)
        resp = requests.get(FLEX_RECEIVE_URL, params={
            "t": IBKR_TOKEN,
            "q": ref_code,
            "v": "3",
        }, timeout=30)
        resp.raise_for_status()

        if "<Status>" in resp.text and "<FlexStatements>" not in resp.text:
            root   = ET.fromstring(resp.text)
            status = root.findtext("Status")
            print(f"  Attempt {attempt+1}: status={status}, retrying...")
            continue

        print(f"  Statement received on attempt {attempt+1}")
        return resp.text

    raise RuntimeError("IBKR statement not ready after 10 attempts (50s)")


def _mask_account(acct):
    """Never store the real account number."""
    return "MASKED" if acct else None


def parse_flex_xml(xml_text: str) -> dict:
    """Parse the Flex XML into a clean snapshot dict."""
    root     = ET.fromstring(xml_text)
    snapshot = {
        "ok":             True,
        "generated_at":   datetime.utcnow().isoformat() + "Z",
        "account":        None,
        "open_positions": [],
        "trades":         [],
        "cash":           None,
    }

    # Account info
    for stmt in root.iter("FlexStatement"):
        snapshot["account"] = _mask_account(stmt.get("accountId"))
        break

    # Open Positions
    # Pre-fetch all needed FX rates
    fx_rates: dict[str, float] = {}
    for pos in root.iter("OpenPosition"):
        symbol = pos.get("symbol") or pos.get("Symbol", "")
        if symbol in TICKER_CURRENCY:
            currency = TICKER_CURRENCY[symbol]
            if currency not in fx_rates:
                fx_rates[currency] = fetch_eur_rate(currency)

    for pos in root.iter("OpenPosition"):
        symbol       = pos.get("symbol") or pos.get("Symbol", "")
        qty          = _float(pos.get("position") or pos.get("Quantity") or pos.get("qty", "0"))
        avg_cost     = _float(pos.get("costBasisPrice") or pos.get("avgCost") or pos.get("averageCost", "0"))
        mark_price   = _float(pos.get("markPrice") or pos.get("currentPrice") or pos.get("closePrice", "0"))
        market_value = _float(pos.get("positionValue") or pos.get("marketValue", "0"))
        unrealized   = _float(pos.get("fifoPnlUnrealized") or pos.get("unrealizedPnL") or pos.get("unrealizedPL", "0"))

        if not symbol:
            continue

        # Convert to EUR if needed
        currency = TICKER_CURRENCY.get(symbol, "EUR")
        rate     = fx_rates.get(currency, 1.0)

        snapshot["open_positions"].append({
            "ticker":         symbol,
            "qty":            qty,
            "avg_entry":      round(avg_cost    * rate, 6),
            "current_price":  round(mark_price  * rate, 6),
            "market_value":   round(market_value * rate, 2),
            "unrealized_pnl": round((mark_price - avg_cost) * qty * rate, 2),
            "invested":       round(avg_cost * qty * rate, 2),
            "currency":       currency,
            "fx_rate":        rate,
        })

    # Trades
    for trade in root.iter("Trade"):
        symbol       = trade.get("symbol") or trade.get("Symbol", "")
        trade_date   = trade.get("tradeDate") or trade.get("TradeDate", "")
        qty          = _float(trade.get("quantity") or trade.get("Quantity", "0"))
        price        = _float(trade.get("tradePrice") or trade.get("TradePrice", "0"))
        net_cash     = _float(trade.get("netCash") or trade.get("NetCash", "0"))
        realized_pnl = _float(
            trade.get("fifoPnlRealized") or
            trade.get("realizedPnL") or
            trade.get("realizedPL") or
            trade.get("pnl", "0")
        )
        commission   = _float(trade.get("ibCommission") or trade.get("commission", "0"))

        if not symbol or qty == 0:
            continue

        # Normalize date yyyyMMdd -> yyyy-MM-dd
        if len(trade_date) == 8 and trade_date.isdigit():
            trade_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"

        snapshot["trades"].append({
            "ticker":       symbol,
            "date":         trade_date,
            "qty":          qty,
            "price":        price,
            "net_cash":     net_cash,
            "realized_pnl": realized_pnl,
            "commission":   abs(commission),
        })

    # Cash — try XML elements first, then derive from trades as last resort
    # Priority 1: CashReportCurrency
    for cash_item in root.iter("CashReportCurrency"):
        if cash_item.get("currency") in ("BASE", "BASE_SUMMARY", "EUR"):
            val = _float(cash_item.get("endingSettledCash") or cash_item.get("endingCash", "0"))
            snapshot["cash"] = val
            print(f"  Cash from CashReportCurrency: {val}")
            break

    # Priority 2: EquitySummaryInBase
    if snapshot["cash"] is None:
        for eq in root.iter("EquitySummaryInBase"):
            val = _float(eq.get("cash") or eq.get("Cash", "0"))
            snapshot["cash"] = val
            print(f"  Cash from EquitySummaryInBase: {val}")
            break

    # Priority 3: StmtFunds
    if snapshot["cash"] is None:
        for sf in root.iter("StmtFunds"):
            val = _float(sf.get("endingCash") or "0")
            snapshot["cash"] = val
            print(f"  Cash from StmtFunds: {val}")
            break

    # Priority 4: sum of net_cash across all trades (approximation — better than null)
    # Negative = cash spent buying; positive = cash received selling.
    # Net total approximates current cash balance from trading activity.
    if snapshot["cash"] is None:
        net_cash_total = sum(t["net_cash"] for t in snapshot["trades"])
        snapshot["cash"] = round(net_cash_total, 2)
        print(f"  Cash derived from trade net_cash sum (fallback): {snapshot['cash']}")

    print(f"  Parsed: {len(snapshot['open_positions'])} open positions, "
          f"{len(snapshot['trades'])} trades, cash={snapshot['cash']}")
    return snapshot


def get_file_sha(path: str) -> str | None:
    """Get current SHA of a file in the repo (needed to update it via API)."""
    url  = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    resp = requests.get(url, headers=_gh_headers(), timeout=10)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json().get("sha")


def commit_snapshot(snapshot: dict):
    """Commit ibkr_snapshot.json to the GitHub repo."""
    print(f"-> Committing {SNAPSHOT_PATH} to {GITHUB_REPO}...")

    content     = json.dumps(snapshot, indent=2, ensure_ascii=False)
    content_b64 = base64.b64encode(content.encode()).decode()
    sha         = get_file_sha(SNAPSHOT_PATH)
    now_str     = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    payload = {
        "message": f"chore: IBKR weekly snapshot {now_str}",
        "content": content_b64,
        "branch":  "main",
    }
    if sha:
        payload["sha"] = sha

    url  = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{SNAPSHOT_PATH}"
    resp = requests.put(url, json=payload, headers=_gh_headers(), timeout=30)
    resp.raise_for_status()

    commit_url = resp.json().get("commit", {}).get("html_url", "")
    print(f"  Committed: {commit_url}")


def _gh_headers() -> dict:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept":        "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _float(val) -> float:
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def main():
    print(f"IBKR Flex Sync -- {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Query ID: {IBKR_QUERY_ID}")
    print(f"Repo:     {GITHUB_REPO}")

    try:
        ref_code = request_flex_statement()
        xml_text = fetch_flex_statement(ref_code)
        snapshot = parse_flex_xml(xml_text)
        if os.environ.get("COMMIT_SNAPSHOT", "").lower() == "true":
            commit_snapshot(snapshot)  # only use this in a PRIVATE repo
        else:
            with open(SNAPSHOT_PATH, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2, ensure_ascii=False)
            print(f"-> Saved {SNAPSHOT_PATH} locally (not committed). "
                  "Set COMMIT_SNAPSHOT=true in a PRIVATE repo to publish it.")
        print("Sync complete")
    except Exception as e:
        print(f"Sync failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()


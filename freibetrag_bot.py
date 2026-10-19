"""
freibetrag_bot.py — Freibetrag Harvest Bot · Frontier5 v2.0
=============================================================
Runs in December via GitHub Actions (1st Monday of December, 08:00 ET).
Also triggerable manually at any time of year for planning purposes.

What it does:
  1. Fetches current prices for all 5 positions
  2. Calculates unrealized P&L in EUR for each position
  3. Identifies the optimal position to harvest up to €1,000 tax-free
  4. Calculates exactly how many shares to sell and immediately repurchase
  5. Sends a Telegram brief with the exact action plan

German tax context:
  - Kapitalertragsteuer: 26.375% (25% + Solidaritätszuschlag 5.5%)
  - Freibetrag 2026: €1,000 per person (singles), €2,000 (married filing jointly)
  - Freibetrag resets every Jan 1 — use it or lose it
  - Strategy: sell enough shares to realize exactly €1,000 gain,
    immediately repurchase at same price to maintain position
  - Works best with positions that have small-moderate unrealized gains
  - Not useful for positions with unrealized losses

EUR/USD rate is fetched at runtime for accurate calculations.
"""

import sys
import os
import json
from datetime import datetime, date

import pytz
import requests

from config import PORTFOLIO, ENTRY_PRICES, TICKER_MAP
from utils  import call_claude, send_telegram, ET

# ── Constants ─────────────────────────────────────────────────────────────────
TAX_RATE_DE   = 0.26375   # Kapitalertragsteuer + Soli
FREIBETRAG    = 1000.0    # EUR — annual exempt amount (2026)
INITIAL_CAP   = 10000.0   # USD

# ── Forex helper ──────────────────────────────────────────────────────────────
def get_eur_usd_rate() -> float:
    """Fetch current EUR/USD exchange rate from Finnhub."""
    try:
        key = os.environ.get("FINNHUB_API_KEY", "")
        r   = requests.get(
            f"https://finnhub.io/api/v1/forex/rates?base=USD&token={key}",
            timeout=8
        )
        rates = r.json().get("quote", {})
        eur_per_usd = rates.get("EUR", 0)
        if eur_per_usd:
            return 1 / eur_per_usd  # returns USD per EUR → invert to get EUR per USD
    except Exception:
        pass
    # Fallback to approximate rate if API fails
    print("⚠️ Could not fetch EUR/USD rate — using fallback 0.92")
    return 0.92


def usd_to_eur(usd: float, rate: float) -> float:
    """Convert USD to EUR using EUR/USD rate (rate = EUR per 1 USD)."""
    return usd * rate


# ── Price fetcher ─────────────────────────────────────────────────────────────
def fetch_current_price(ticker: str) -> float:
    """Fetch current price from Finnhub."""
    key = os.environ.get("FINNHUB_API_KEY", "")
    r   = requests.get(
        f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={key}",
        timeout=8
    )
    return r.json().get("c", 0)


# ── P&L calculator ────────────────────────────────────────────────────────────
def calculate_position_pnl(ticker: str, current_price: float, eur_rate: float) -> dict:
    """
    Calculate unrealized P&L for a position in both USD and EUR.
    Returns dict with all relevant numbers for harvest analysis.
    """
    pos_cfg    = TICKER_MAP.get(ticker, {})
    weight     = pos_cfg.get("weight", 0)
    entry      = ENTRY_PRICES.get(ticker)

    if not entry or not current_price:
        return {"ticker": ticker, "valid": False}

    capital_usd  = INITIAL_CAP * weight
    shares       = capital_usd / entry

    # Unrealized P&L
    cost_basis_usd = entry * shares
    current_val_usd = current_price * shares
    pnl_usd        = current_val_usd - cost_basis_usd
    pnl_pct        = (pnl_usd / cost_basis_usd * 100)

    # Convert to EUR
    pnl_eur         = usd_to_eur(pnl_usd, eur_rate)
    cost_basis_eur  = usd_to_eur(cost_basis_usd, eur_rate)
    current_val_eur = usd_to_eur(current_val_usd, eur_rate)

    # Harvest calculation
    # To realize exactly FREIBETRAG EUR of gain:
    # shares_to_sell = FREIBETRAG / (gain_per_share_in_EUR)
    gain_per_share_eur = usd_to_eur(current_price - entry, eur_rate)

    can_harvest = pnl_eur > 0  # only positions with gains
    shares_to_sell  = 0
    harvest_gain_eur = 0
    tax_saved_eur   = 0

    if can_harvest and gain_per_share_eur > 0:
        if pnl_eur >= FREIBETRAG:
            # Position has more than €1,000 gain — sell exactly enough shares
            shares_to_sell  = FREIBETRAG / gain_per_share_eur
            harvest_gain_eur = FREIBETRAG
        else:
            # Position has less than €1,000 gain — sell all shares to harvest full gain
            shares_to_sell  = shares
            harvest_gain_eur = pnl_eur

        tax_saved_eur = harvest_gain_eur * TAX_RATE_DE

    return {
        "ticker":           ticker,
        "sector":           pos_cfg.get("sector", ""),
        "weight":           weight,
        "valid":            True,
        "entry":            entry,
        "current_price":    current_price,
        "shares":           shares,
        "pnl_usd":          pnl_usd,
        "pnl_eur":          pnl_eur,
        "pnl_pct":          pnl_pct,
        "cost_basis_eur":   cost_basis_eur,
        "current_val_eur":  current_val_eur,
        "can_harvest":      can_harvest,
        "shares_to_sell":   shares_to_sell,
        "harvest_gain_eur": harvest_gain_eur,
        "tax_saved_eur":    tax_saved_eur,
        "gain_per_share_eur": gain_per_share_eur,
    }


# ── Harvest optimizer ─────────────────────────────────────────────────────────
def find_optimal_harvest(positions_data: list) -> dict | None:
    """
    Find the best position to harvest the Freibetrag from.
    Priority:
      1. Position with gain ≥ €1,000 and smallest gain above threshold
         (minimize market impact of partial sale)
      2. If no position has ≥ €1,000 gain, combine multiple positions
         to reach €1,000 total
    Returns the primary harvest candidate or None if no gains available.
    """
    # Filter to positions with gains
    gainers = [p for p in positions_data if p.get("valid") and p.get("can_harvest")]

    if not gainers:
        return None

    # Find positions with >= €1,000 gain (partial harvest)
    full_harvestable = [p for p in gainers if p["pnl_eur"] >= FREIBETRAG]

    if full_harvestable:
        # Best candidate: smallest gain above threshold (least disruption)
        return min(full_harvestable, key=lambda p: p["pnl_eur"])

    # No single position has €1,000+ gain — return the biggest gainer
    # (even if it's less than €1,000, still worth harvesting)
    return max(gainers, key=lambda p: p["pnl_eur"])


# ── Message builder ───────────────────────────────────────────────────────────
def build_freibetrag_message(positions_data: list, harvest: dict | None,
                              eur_rate: float, already_used: float = 0.0) -> str:
    """Build the complete Freibetrag analysis Telegram message."""
    now_et    = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    year      = datetime.now().year
    remaining = FREIBETRAG - already_used

    lines = [
        f"🇩🇪 <b>FREIBETRAG HARVEST ANALYSIS — {year}</b>",
        f"📅 {now_et}",
        f"💶 EUR/USD rate: {1/eur_rate:.4f} (1 EUR = ${1/eur_rate:.4f})",
        "",
        f"<b>Freibetrag {year}:</b> €{FREIBETRAG:,.0f} total",
        f"<b>Ya utilizado:</b> €{already_used:,.2f}",
        f"<b>Disponible:</b> €{remaining:,.2f}",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "<b>P&L no realizado por posición:</b>",
        "",
    ]

    # Position summary table
    total_pnl_eur = 0
    for p in sorted(positions_data, key=lambda x: x.get("pnl_eur", 0), reverse=True):
        if not p.get("valid"):
            lines.append(f"  {p['ticker']}: datos no disponibles")
            continue

        pnl_eur = p["pnl_eur"]
        total_pnl_eur += pnl_eur
        icon    = "📈" if pnl_eur > 0 else "📉" if pnl_eur < 0 else "➡️"
        sign    = "+" if pnl_eur >= 0 else ""
        lines.append(
            f"  {icon} <b>{p['ticker']}</b> ({p['sector'][:8]}): "
            f"{sign}€{pnl_eur:,.2f} ({p['pnl_pct']:+.1f}%)"
        )

    lines.extend([
        "",
        f"  <b>TOTAL portafolio: {'+' if total_pnl_eur >= 0 else ''}€{total_pnl_eur:,.2f}</b>",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
    ])

    # Harvest recommendation
    if not harvest or remaining <= 0:
        if remaining <= 0:
            lines.extend([
                "✅ <b>Freibetrag ya utilizado completamente.</b>",
                "No se requiere ninguna acción.",
            ])
        else:
            lines.extend([
                "ℹ️ <b>Sin ganancias para cosechar.</b>",
                "Todas las posiciones están en pérdida o plano.",
                "No se recomienda acción este año.",
            ])
    else:
        harvest_eur  = min(harvest["harvest_gain_eur"], remaining)
        shares_sell  = harvest["shares_to_sell"] if harvest["pnl_eur"] >= FREIBETRAG \
                       else min(harvest["shares"], remaining / max(harvest["gain_per_share_eur"], 0.001))
        tax_saved    = harvest_eur * TAX_RATE_DE
        sell_price   = harvest["current_price"]
        sell_val_usd = shares_sell * sell_price

        lines.extend([
            f"🎯 <b>RECOMENDACIÓN DE HARVEST:</b>",
            "",
            f"  Posición: <b>{harvest['ticker']}</b>",
            f"  Shares a vender: <b>{shares_sell:.4f}</b>",
            f"  Precio actual: ${sell_price:.2f}",
            f"  Valor de venta: ~${sell_val_usd:.2f} (~€{usd_to_eur(sell_val_usd, eur_rate):.2f})",
            f"  Ganancia realizada: ~€{harvest_eur:,.2f}",
            f"  Impuesto ahorrado: ~€{tax_saved:,.2f} 💰",
            "",
            f"  <b>Acción:</b>",
            f"  1. Vende {shares_sell:.4f} shares de {harvest['ticker']} en Alpaca Paper",
            f"  2. Inmediatamente recompra {shares_sell:.4f} shares al precio de mercado",
            f"  3. Resultado: tesis mantenida + €{harvest_eur:,.2f} de ganancia libre de impuestos",
            "",
            f"⚠️ Ejecutar antes del 31 Dic {year} cierre de mercado (16:00 ET)",
            f"⚠️ La recompra inmediata mantiene la posición — no es una salida",
        ])

        # Warning if position is near stop-loss
        dist_stop = harvest.get("dist_stop_pct")
        if dist_stop and dist_stop < 10:
            lines.extend([
                "",
                f"⚠️ {harvest['ticker']} está al {dist_stop:.1f}% de su stop-loss.",
                "Considera si la tesis sigue intacta antes de hacer el harvest.",
            ])

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"ℹ️ Tasa Kapitalertragsteuer: {TAX_RATE_DE*100:.3f}%",
        "ℹ️ Consulta con tu Steuerberater para confirmar aplicabilidad.",
    ])

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    now_et = datetime.now(ET)
    month  = now_et.month
    print(f"Freibetrag Bot — {now_et.strftime('%Y-%m-%d %H:%M ET')}")

    # Warn if not December (but still run — useful for planning)
    if month != 12:
        print(f"⚠️ Running outside December (month={month}) — planning mode only")
        send_telegram(
            f"📊 <b>Freibetrag Bot — Modo planificación</b>\n"
            f"Ejecutado en {now_et.strftime('%B %Y')} (no es diciembre).\n"
            f"Mostrando análisis actual para planificación anticipada."
        )

    # 1. Fetch EUR/USD rate
    print("Fetching EUR/USD rate...")
    eur_rate = get_eur_usd_rate()
    print(f"  EUR/USD: {eur_rate:.4f} (1 USD = €{eur_rate:.4f})")

    # 2. Fetch prices and calculate P&L for all positions
    print("Calculating P&L for all positions...")
    positions_data = []

    for pos in PORTFOLIO:
        ticker = pos["ticker"]
        try:
            price = fetch_current_price(ticker)
            data  = calculate_position_pnl(ticker, price, eur_rate)
            # Add stop distance for harvest warning
            entry    = ENTRY_PRICES.get(ticker)
            stop_pct = TICKER_MAP.get(ticker, {}).get("stop_loss_pct", 0.10)
            if entry and price:
                stop_lvl = entry * (1 - stop_pct)
                data["dist_stop_pct"] = (price - stop_lvl) / price * 100
            positions_data.append(data)
            sign = "+" if data["pnl_eur"] >= 0 else ""
            print(f"  {ticker}: {sign}€{data['pnl_eur']:.2f} ({data['pnl_pct']:+.1f}%)")
        except Exception as e:
            print(f"  ❌ {ticker}: {e}")
            positions_data.append({"ticker": ticker, "valid": False})

    # 3. Find optimal harvest candidate
    harvest = find_optimal_harvest(positions_data)
    if harvest:
        print(f"Best harvest candidate: {harvest['ticker']} (€{harvest['pnl_eur']:.2f} gain)")
    else:
        print("No positions with gains — no harvest possible")

    # 4. Build and send message
    # already_used: set this manually if you've already crystallized some gains this year
    # For simplicity, we assume 0 already used — update if needed
    already_used = 0.0

    message = build_freibetrag_message(positions_data, harvest, eur_rate, already_used)
    send_telegram(message)
    print("✅ Freibetrag analysis sent to Telegram.")
    print("Done.")


if __name__ == "__main__":
    main()

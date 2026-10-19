"""
config.py — Multi-portfolio dispatcher · Frontier5 v2.0
=========================================================
This file is the ONLY thing the bots import. It reads PORTFOLIO_ID from
the environment and exposes the chosen portfolio's values as module-level
names — so intraday_scan.py, dca_bot.py, earnings_alert.py, quarterly_review.py
all continue to work with zero changes.

Usage in GitHub Actions workflows:
  env:
    PORTFOLIO_ID: frontier5_v2      ← Portfolio 1 (default)
    PORTFOLIO_ID: defense_aerospace ← Portfolio 2

To add a new portfolio:
  1. Create configs/my_portfolio.py (copy defense_aerospace.py as template)
  2. Add it to PORTFOLIO_REGISTRY below
  3. Set PORTFOLIO_ID=my_portfolio in the relevant workflow env block

Available portfolios:
  frontier5_v2      — US Equities, Alpaca Paper, 5 positions (active)
  defense_aerospace — Defense & Aerospace, Alpaca Paper, 5 positions (active)
"""

import os
import sys

# ── Registry ──────────────────────────────────────────────────────────────────
from configs.frontier5_v2      import config as _frontier5_v2
from configs.defense_aerospace import config as _defense_aerospace

PORTFOLIO_REGISTRY = {
    "frontier5_v2":      _frontier5_v2,
    "defense_aerospace": _defense_aerospace,
    # "macro_hedge":      _macro,   ← uncomment when ready
    # "crypto_bot":       _crypto,  ← uncomment when ready
}

# ── Portfolio selection ────────────────────────────────────────────────────────
_portfolio_id = os.environ.get("PORTFOLIO_ID", "frontier5_v2")

if _portfolio_id not in PORTFOLIO_REGISTRY:
    print(
        f"[config.py] ERROR: PORTFOLIO_ID='{_portfolio_id}' not found in registry.\n"
        f"Available: {list(PORTFOLIO_REGISTRY.keys())}",
        file=sys.stderr,
    )
    sys.exit(1)

_cfg = PORTFOLIO_REGISTRY[_portfolio_id]

# ── Module-level exports ───────────────────────────────────────────────────────
PORTFOLIO_ID     = _cfg.PORTFOLIO_ID
PORTFOLIO_NAME   = _cfg.PORTFOLIO_NAME

PORTFOLIO        = _cfg.PORTFOLIO
ENTRY_PRICES     = _cfg.ENTRY_PRICES

INITIAL_CAPITAL  = _cfg.INITIAL_CAPITAL
ENTRY_DATE       = _cfg.ENTRY_DATE
BROKER           = _cfg.BROKER
CURRENCY         = _cfg.CURRENCY
COUNTRY          = _cfg.COUNTRY

ALERT_DROP_PCT    = _cfg.ALERT_DROP_PCT
ALERT_EXTREME_PCT = _cfg.ALERT_EXTREME_PCT

STOP_LOSS_RULES          = _cfg.STOP_LOSS_RULES
TRIM_RSI_RULES           = _cfg.TRIM_RSI_RULES
TRIM_CONCENTRATION_RULES = _cfg.TRIM_CONCENTRATION_RULES
NEVER_SELL_CONDITIONS    = _cfg.NEVER_SELL_CONDITIONS
DCA_RULES                = _cfg.DCA_RULES
FREIBETRAG_RULES         = _cfg.FREIBETRAG_RULES

CRITICAL_NEWS_KEYWORDS   = _cfg.CRITICAL_NEWS_KEYWORDS
TOP_NEWS_COUNT           = _cfg.TOP_NEWS_COUNT
TOP5_TICKERS             = _cfg.TOP5_TICKERS
TICKER_MAP               = _cfg.TICKER_MAP
STOP_LEVELS              = _cfg.STOP_LEVELS

PORTFOLIO_CONTEXT        = _cfg.PORTFOLIO_CONTEXT
PORTFOLIO_EMOJI          = _cfg.PORTFOLIO_EMOJI
EARNINGS_CALENDAR        = _cfg.EARNINGS_CALENDAR

TAX_RATE_DE    = _cfg.TAX_RATE_DE
FREIBETRAG_EUR = _cfg.FREIBETRAG_EUR

# ── Debug ──────────────────────────────────────────────────────────────────────
if os.environ.get("CONFIG_DEBUG"):
    print(f"[config.py] Loaded: {PORTFOLIO_ID} ({PORTFOLIO_NAME})")
    print(f"[config.py] Broker: {BROKER} | Tickers: {TOP5_TICKERS}")

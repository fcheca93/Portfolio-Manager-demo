"""
configs/base.py — Base class for all Frontier5 portfolio configurations
========================================================================
Every portfolio config inherits from PortfolioConfig and must implement
the abstract properties. The config.py dispatcher then exposes the chosen
portfolio's values as module-level names so all existing bots work unchanged.

To add a new portfolio:
  1. Create configs/my_portfolio.py inheriting PortfolioConfig
  2. Register it in config.py's PORTFOLIO_REGISTRY dict
  3. Set PORTFOLIO_ID=my_portfolio in the GitHub Actions workflow env
"""

from abc import ABC, abstractmethod


class PortfolioConfig(ABC):
    """
    Abstract base for all portfolio configurations.
    All properties below must be implemented by each concrete config.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    @property
    @abstractmethod
    def PORTFOLIO_ID(self) -> str:
        """Unique slug. Must match the key in config.py PORTFOLIO_REGISTRY."""
        ...

    @property
    @abstractmethod
    def PORTFOLIO_NAME(self) -> str:
        """Human-readable name shown in Telegram alerts and dashboard."""
      
    @property
    @abstractmethod
    def PORTFOLIO_EMOJI(self) -> str:
        """Emoji identifier for Telegram messages."""
        ...

    # ── Broker ────────────────────────────────────────────────────────────────
    @property
    @abstractmethod
    def BROKER(self) -> str:
        """Broker identifier: 'alpaca_paper', 'alpaca_live', 'binance', 'kraken', etc."""
        ...

    @property
    @abstractmethod
    def CURRENCY(self) -> str:
        """Base currency for reporting: 'USD', 'EUR', 'BTC', etc."""
        ...

    # ── Positions ─────────────────────────────────────────────────────────────
    @property
    @abstractmethod
    def PORTFOLIO(self) -> list:
        """
        List of position dicts. Each dict must have:
          ticker (str), weight (float 0-1), sector (str), stop_loss_pct (float)
        """
        ...

    @property
    @abstractmethod
    def ENTRY_PRICES(self) -> dict:
        """Dict of {ticker: float}. None value = position not yet open."""
        ...

    # ── Capital & tax ─────────────────────────────────────────────────────────
    @property
    @abstractmethod
    def INITIAL_CAPITAL(self) -> float:
        """Starting capital in CURRENCY."""
        ...

    @property
    @abstractmethod
    def ENTRY_DATE(self) -> str:
        """ISO date string of when positions were opened, e.g. '2026-03-25'."""
        ...

    @property
    @abstractmethod
    def COUNTRY(self) -> str:
        """Two-letter country code for tax context, e.g. 'DE'."""
        ...

    # ── Alert thresholds ──────────────────────────────────────────────────────
    @property
    @abstractmethod
    def ALERT_DROP_PCT(self) -> float:
        """Alert if position drops more than this % intraday (negative number)."""
        ...

    @property
    @abstractmethod
    def ALERT_EXTREME_PCT(self) -> float:
        """Alert if position moves more than this % in either direction."""
        ...

    # ── Rules ─────────────────────────────────────────────────────────────────
    @property
    @abstractmethod
    def STOP_LOSS_RULES(self) -> dict:
        ...

    @property
    @abstractmethod
    def TRIM_RSI_RULES(self) -> dict:
        ...

    @property
    @abstractmethod
    def TRIM_CONCENTRATION_RULES(self) -> dict:
        ...

    @property
    @abstractmethod
    def DCA_RULES(self) -> dict:
        ...

    @property
    @abstractmethod
    def NEVER_SELL_CONDITIONS(self) -> list:
        ...

    @property
    @abstractmethod
    def FREIBETRAG_RULES(self) -> dict:
        ...

    # ── News keywords ─────────────────────────────────────────────────────────
    @property
    @abstractmethod
    def CRITICAL_NEWS_KEYWORDS(self) -> list:
        ...

    # ── Claude context string ─────────────────────────────────────────────────
    @property
    @abstractmethod
    def PORTFOLIO_CONTEXT(self) -> str:
        """
        Multi-line string injected into every Claude system prompt.
        Should describe: strategy, positions, entry prices, stop levels, rules.
        """
        ...

    @property
    @abstractmethod
    def EARNINGS_CALENDAR(self) -> list:
        """
        List of upcoming earnings events for this portfolio's tickers.
        Each dict must have: ticker, name, sector, date (datetime.date),
        timing ('pre'/'post'), eps_est, rev_est_b, eps_history (list of 4),
        macro_context, key_metrics, thesis_check.
        Update after each earnings season.
        """
        ...

    # ── Derived helpers (auto-computed — do not override unless needed) ────────
    @property
    def TOP_NEWS_COUNT(self) -> int:
        return len(self.PORTFOLIO)

    @property
    def TOP5_TICKERS(self) -> list:
        sorted_pos = sorted(self.PORTFOLIO, key=lambda x: x["weight"], reverse=True)
        return [p["ticker"] for p in sorted_pos[:self.TOP_NEWS_COUNT]]

    @property
    def TICKER_MAP(self) -> dict:
        return {p["ticker"]: p for p in self.PORTFOLIO}

    @property
    def STOP_LEVELS(self) -> dict:
        tm = self.TICKER_MAP
        ep = self.ENTRY_PRICES
        return {
            ticker: round(ep[ticker] * (1 - tm[ticker]["stop_loss_pct"]), 2)
            if ep.get(ticker) else None
            for ticker in tm
        }

    # ── Tax constants (DE defaults — override in subclass if different) ───────
    TAX_RATE_DE   = 0.26375
    FREIBETRAG_EUR = 1_000.0

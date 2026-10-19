"""
configs/defense_aerospace.py — Frontier5 · Defense & Aerospace · Alpaca Paper
===============================================================================
Portfolio 2: Cobertura completa del espectro de defensa.
Abierto: 7 Abril 2026

Selección: RTX (28%) · LMT (28%) · LHX (20%) · HII (14%) · KTOS (10%)
Capital: $10,000 · Broker: Alpaca Paper · País: DE (KeSt 26.375%)
"""

from configs.base import PortfolioConfig


class DefenseAerospaceConfig(PortfolioConfig):

    @property
    def PORTFOLIO_ID(self): return "defense_aerospace"

    @property
    def PORTFOLIO_NAME(self): return "Defense & Aerospace"

    @property
    def BROKER(self): return "alpaca_paper"

    @property
    def CURRENCY(self): return "USD"

    @property
    def PORTFOLIO(self):
        return [
            {"ticker": "RTX",  "weight": 0.28, "sector": "Misiles & Air Defense",  "stop_loss_pct": 0.20},
            {"ticker": "LMT",  "weight": 0.28, "sector": "Plataformas & C2",        "stop_loss_pct": 0.20},
            {"ticker": "LHX",  "weight": 0.20, "sector": "Electrónica & ISR",       "stop_loss_pct": 0.20},
            {"ticker": "HII",  "weight": 0.14, "sector": "Naval & Submarinos",      "stop_loss_pct": 0.20},
            {"ticker": "KTOS", "weight": 0.10, "sector": "Drones & Hipersónico",    "stop_loss_pct": 0.20},
        ]

    @property
    def ENTRY_PRICES(self):
        return {
            "RTX":  198.41,
            "LMT":  637.90,
            "LHX":  358.73,
            "HII":  407.66,
            "KTOS":  74.09,
        }

    @property
    def INITIAL_CAPITAL(self): return 10_000.00

    @property
    def ENTRY_DATE(self): return "2026-04-07"

    @property
    def COUNTRY(self): return "DE"

    @property
    def ALERT_DROP_PCT(self): return -5.0

    @property
    def ALERT_EXTREME_PCT(self): return 7.0

    @property
    def STOP_LOSS_RULES(self):
        return {"action": "SELL_ALL", "timing": "immediate", "order_type": "market", "exceptions": []}

    @property
    def TRIM_RSI_RULES(self):
        return {
            "condition_1": "rsi_weekly_gt_75", "condition_2": "price_gt_2x_entry",
            "both_required": True, "trim_pct": 0.25, "action": "SELL_25PCT",
            "timing": "that_week", "order_type": "market",
            "post_trim_action": "raise_stop_to_85pct_of_recent_high",
        }

    @property
    def TRIM_CONCENTRATION_RULES(self):
        return {
            "trigger_pct": 0.40, "trim_pct": 0.25, "action": "SELL_25PCT",
            "timing": "that_week", "order_type": "market",
            "cash_priority_1": "DCA_into_NOC_if_rsi_lt_45",
            "cash_priority_2": "hold_cash_wait_for_pullback",
            "cash_never": "reinvest_immediately_without_thesis",
        }

    @property
    def DCA_RULES(self):
        return {
            "signal_1": "rsi_lt_45", "signal_2": "price_near_ema20",
            "both_helps": True, "max_add_pct_of_position": 0.20,
            "never_add_if_stop_near": True,
            "watchlist_dca": ["NOC"],
        }

    @property
    def NEVER_SELL_CONDITIONS(self):
        return [
            "daily_move_lt_7pct", "negative_news_no_fundamental_impact",
            "general_market_decline_no_specific_cause", "emotional_pressure_or_fear",
            "short_term_analyst_downgrade", "ceasefire_rumor_without_signed_agreement",
            "defense_budget_debate_without_final_cut",
        ]

    @property
    def FREIBETRAG_RULES(self):
        return {
            "target_eur": 1_000.0, "execute_month": 12, "execute_week": "last",
            "priority": "largest_unrealized_loss_first", "rebuying": True,
            "wash_sale_applies": False,
        }

    @property
    def CRITICAL_NEWS_KEYWORDS(self):
        return [
            "earnings", "beat", "miss", "guidance", "revenue", "eps", "backlog",
            "contract award", "program cut", "program cancelled", "cost overrun",
            "ceo", "resign", "investigation", "sec", "doj",
            "defense budget", "pentagon", "ndaa", "continuing resolution",
            "sequestration", "budget cut", "supplemental", "ukraine aid",
            "nato", "2pct gdp", "article 5",
            "f-35", "patriot", "thaad", "amraam", "stinger", "himars",
            "ford class", "virginia class", "l3harris", "valkyrie", "xq-58",
            "drone", "uav", "ucav",
            "raytheon", "lockheed", "huntington", "kratos",
            "ukraine", "russia", "taiwan", "china", "iran",
            "middle east", "hormuz", "escalation", "ceasefire", "war",
            "foreign military sales", "fms", "itar", "arms sale", "sanction",
        ]

    @property
    def PORTFOLIO_EMOJI(self): return "🛡"

    @property
    def EARNINGS_CALENDAR(self):
        from datetime import date
        return [
            {
                "ticker": "RTX", "name": "Raytheon Technologies", "sector": "Misiles & Air Defense",
                "date": date(2026, 4, 22), "timing": "pre",
                "eps_est": 1.62, "rev_est_b": 20.5,
                "eps_history": [1.47, 1.56, 1.70, 1.55],
                "macro_context": "Reposición NATO activa. Backlog $202B. Demanda Patriot máximos.",
                "key_metrics": "Defense backlog, Patriot/AMRAAM production rate, margins",
                "thesis_check": "¿Sigue creciendo backlog de misiles guiados?",
            },
            {
                "ticker": "LMT", "name": "Lockheed Martin", "sector": "Plataformas & C2",
                "date": date(2026, 4, 22), "timing": "pre",
                "eps_est": 7.80, "rev_est_b": 18.2,
                "eps_history": [7.28, 7.29, 6.95, 7.43],
                "macro_context": "F-35 producción sostenida. HIMARS demanda alta. Backlog $160B.",
                "key_metrics": "F-35 deliveries, backlog growth, free cash flow",
                "thesis_check": "¿Mantiene F-35 como plataforma central de la OTAN?",
            },
            {
                "ticker": "LHX", "name": "L3Harris Technologies", "sector": "Electrónica & ISR",
                "date": date(2026, 4, 29), "timing": "pre",
                "eps_est": 3.10, "rev_est_b": 5.4,
                "eps_history": [2.41, 2.78, 2.70, 2.86],
                "macro_context": "Demanda comunicaciones tácticas e ISR en máximos.",
                "key_metrics": "Funded backlog, international orders, margin expansion",
                "thesis_check": "¿Creciendo revenue en electrónica táctica >8% YoY?",
            },
            {
                "ticker": "HII", "name": "Huntington Ingalls", "sector": "Naval & Submarinos",
                "date": date(2026, 5, 1), "timing": "pre",
                "eps_est": 4.20, "rev_est_b": 3.0,
                "eps_history": [3.79, 3.86, 3.68, 4.04],
                "macro_context": "Programa Virginia-class acelerado. Ford-class en producción.",
                "key_metrics": "Shipbuilding revenue, Virginia-class deliveries, backlog",
                "thesis_check": "¿Sigue siendo el único constructor de portaaviones nucleares?",
            },
            {
                "ticker": "KTOS", "name": "Kratos Defense", "sector": "Drones & Hipersónico",
                "date": date(2026, 5, 7), "timing": "post",
                "eps_est": 0.20, "rev_est_b": 0.38,
                "eps_history": [0.12, 0.11, 0.14, 0.18],
                "macro_context": "XQ-58 Valkyrie en producción. Demanda drones combate máximos.",
                "key_metrics": "Unmanned systems revenue, DoD contract awards, backlog growth",
                "thesis_check": "¿Acelerando beats EPS y creciendo drone backlog?",
            },
        ]

    @property
    def PORTFOLIO_CONTEXT(self):
        return """
Defense & Aerospace — Frontier5 · Portfolio 2
Abierto 7 Abril 2026 vía Alpaca Paper Trading. Capital: $10,000.

Tesis: Capitalizar el incremento global de presupuestos de defensa.
Contexto: Guerra activa EEUU-Irán, NATO spending en máximos, aranceles
favorecen empresas 100% domésticas DoD. Inversor en Alemania (KeSt 26.375%).

Posiciones (precios reales Finnhub 7 Abr 2026):
  RTX  (28%) — Raytheon. Misiles & Air Defense. Entrada $198.41. Stop −20% → $158.73.
  LMT  (28%) — Lockheed Martin. Plataformas & C2. Entrada $637.90. Stop −20% → $510.32.
  LHX  (20%) — L3Harris. Electrónica & ISR. Entrada $358.73. Stop −20% → $286.98.
  HII  (14%) — Huntington Ingalls. Naval. Entrada $407.66. Stop −20% → $326.13.
  KTOS (10%) — Kratos. Drones. Entrada $74.09. Stop −20% → $59.27.

Stop universal: −20% desde avg_entry para todas las posiciones.
Watchlist DCA: NOC — añadir cuando RSI < 45.

Reglas:
  1. Stop activado → SELL 100% inmediato
  2. Tesis rota    → SELL 100% en 1-2 días
  3. RSI >75 + 2×  → SELL 25% trim
  4. Freibetrag dic → harvest €1,000

Nunca vender por: caída <7%, rumores paz sin acuerdo, debate presupuestario sin corte.
"""


# Singleton
config = DefenseAerospaceConfig()

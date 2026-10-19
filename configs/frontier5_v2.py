"""
configs/frontier5_v2.py — Frontier5 · AI Cycle · Alpaca Paper
==============================================================
Portfolio 1: El ciclo completo de la IA — desde el silicio y la fabricación,
pasando por las redes que mueven los datos, hasta el software que los monetiza.

Contexto de apertura (8 Abril 2026):
  - S&P en corrección −8.7% desde enero por guerra EEUU-Irán + aranceles
  - Sector tech rebotando hoy fuertemente: ANET +7.9%, TSM +6.0%, MRVL +4.8%
  - Aranceles 15% no afectan directamente a software/servicios cloud
  - Demanda de AI compute sigue acelerando — NVDA Blackwell en plena rampa

Selección — 5 posiciones cubriendo el ciclo completo de IA:
  NVDA (30%) — GPU · TSM (25%) — Fabricación · ANET (20%) — Redes
  PLTR (15%) — Software IA · MRVL (10%) — Silicon Fotónico

Capital: $10,000 · Broker: Alpaca Paper · País: DE (KeSt 26.375%)
Abierto: 8 Abril 2026
"""

from configs.base import PortfolioConfig


class Frontier5V2Config(PortfolioConfig):

    @property
    def PORTFOLIO_ID(self): return "frontier5_v2"

    @property
    def PORTFOLIO_NAME(self): return "Frontier5 — AI Cycle"

    @property
    def BROKER(self): return "alpaca_paper"

    @property
    def CURRENCY(self): return "USD"

    @property
    def PORTFOLIO(self):
        return [
            {"ticker": "NVDA", "weight": 0.30, "sector": "GPU & Compute",          "stop_loss_pct": 0.20},
            {"ticker": "TSM",  "weight": 0.25, "sector": "Fabricación Semis",       "stop_loss_pct": 0.20},
            {"ticker": "ANET", "weight": 0.20, "sector": "Redes & Data Centers",    "stop_loss_pct": 0.20},
            {"ticker": "PLTR", "weight": 0.15, "sector": "Software IA & Datos",     "stop_loss_pct": 0.20},
            {"ticker": "MRVL", "weight": 0.10, "sector": "Silicon Fotónico & ASIC", "stop_loss_pct": 0.20},
        ]

    @property
    def ENTRY_PRICES(self):
        return {
            "NVDA": 181.89,
            "TSM":  365.35,
            "ANET": 143.99,
            "PLTR": 146.58,
            "MRVL": 114.80,
        }

    @property
    def INITIAL_CAPITAL(self): return 10_000.00

    @property
    def ENTRY_DATE(self): return "2026-04-08"

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
            "cash_priority_1": "add_to_position_with_rsi_lt_45",
            "cash_priority_2": "hold_cash_wait_for_correction",
            "cash_never": "reinvest_immediately_without_thesis",
        }

    @property
    def DCA_RULES(self):
        return {
            "signal_1": "rsi_lt_45", "signal_2": "price_near_ema20",
            "both_helps": True, "max_add_pct_of_position": 0.20,
            "never_add_if_stop_near": True,
        }

    @property
    def NEVER_SELL_CONDITIONS(self):
        return [
            "daily_move_lt_7pct", "negative_news_no_fundamental_impact",
            "general_market_decline_no_specific_cause", "emotional_pressure_or_fear",
            "short_term_analyst_downgrade", "ai_bubble_narrative_without_earnings_miss",
            "geopolitical_noise_not_affecting_ai_capex",
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
            "earnings", "beat", "miss", "guidance", "revenue", "eps",
            "ceo", "resign", "fired", "lawsuit", "investigation", "sec",
            "nvidia", "blackwell", "hopper", "gb200", "gb300",
            "tsmc", "n2", "n3", "advanced packaging", "cowos",
            "arista", "data center", "hyperscaler", "switch",
            "palantir", "aip", "maven", "pentagon", "dod contract",
            "marvell", "asic", "custom silicon", "optical", "photonics",
            "ai capex", "ai spending", "data center investment",
            "chip ban", "export control", "semiconductor",
            "openai", "anthropic", "google gemini", "deepseek",
            "china", "taiwan", "tsmc fab", "semiconductor act",
            "tariff", "sanction",
        ]

    @property
    def PORTFOLIO_EMOJI(self): return "🧠"

    @property
    def EARNINGS_CALENDAR(self):
        from datetime import date
        return [
            {
                "ticker": "TSM", "name": "TSMC", "sector": "Fabricación Semis",
                "date": date(2026, 4, 17), "timing": "pre",
                "eps_est": 2.18, "rev_est_b": 25.6,
                "eps_history": [1.50, 1.62, 1.78, 1.94],
                "macro_context": "Demanda AI chips acelerando. N2 process en rampa.",
                "key_metrics": "CoWoS capacity, N2 yield, AI revenue mix",
                "thesis_check": "¿Sigue siendo el único fab capaz de producir chips NVDA?",
            },
            {
                "ticker": "PLTR", "name": "Palantir", "sector": "Software IA & Datos",
                "date": date(2026, 5, 5), "timing": "post",
                "eps_est": 0.27, "rev_est_b": 1.08,
                "eps_history": [0.13, 0.16, 0.21, 0.25],
                "macro_context": "Contratos DoD en expansión. AIP adoption acelerando.",
                "key_metrics": "US commercial revenue growth, AIP customers, Rule of 40",
                "thesis_check": "¿Sigue creciendo revenue US commercial >40% YoY?",
            },
            {
                "ticker": "ANET", "name": "Arista Networks", "sector": "Redes & Data Centers",
                "date": date(2026, 5, 6), "timing": "post",
                "eps_est": 0.88, "rev_est_b": 2.10,
                "eps_history": [0.65, 0.73, 0.75, 0.82],
                "macro_context": "Hyperscalers aumentando capex AI data centers.",
                "key_metrics": "AI backend revenue, hyperscaler orders, backlog",
                "thesis_check": "¿Sigue creciendo la demanda de switches AI data center?",
            },
            {
                "ticker": "NVDA", "name": "NVIDIA", "sector": "GPU & Compute",
                "date": date(2026, 5, 20), "timing": "post",
                "eps_est": 1.75, "rev_est_b": 43.0,
                "eps_history": [0.96, 1.05, 1.30, 1.62],
                "macro_context": "Blackwell B300 en rampa. Demanda supera oferta.",
                "key_metrics": "Data center revenue, Blackwell shipments, gross margin",
                "thesis_check": "¿Sigue siendo NVDA el estándar de facto para AI compute?",
            },
            {
                "ticker": "MRVL", "name": "Marvell Technology", "sector": "Silicon Fotónico & ASIC",
                "date": date(2026, 6, 3), "timing": "post",
                "eps_est": 0.85, "rev_est_b": 2.20,
                "eps_history": [0.67, 0.76, 0.80, 0.80],
                "macro_context": "Demanda custom silicon AI en aceleración.",
                "key_metrics": "AI revenue, custom ASIC revenue, optical interconnect orders",
                "thesis_check": "¿Creciendo custom silicon >50% YoY para hyperscalers?",
            },
        ]

    @property
    def PORTFOLIO_CONTEXT(self):
        return """
Frontier5 — AI Cycle · Portfolio 1
Abierto 8 Abril 2026 vía Alpaca Paper Trading. Capital: $10,000.

Tesis: Cubrir el ciclo completo de la IA — desde el silicio y la fabricación,
pasando por las redes que mueven los datos, hasta el software que los monetiza.
Contexto: S&P en corrección por guerra EEUU-Irán + aranceles. Tech rebotando.
Demanda de AI compute sigue acelerando. Aranceles no afectan software/cloud.
Inversor en Alemania (Kapitalertragsteuer 26.375%).

Posiciones (precios reales Finnhub 8 Abr 2026):
  NVDA (30%) — GPU & Compute. Entrada $181.89. Stop −20% → $145.51.
  TSM  (25%) — Fabricación Semis. Entrada $365.35. Stop −20% → $292.28.
  ANET (20%) — Redes & Data Centers. Entrada $143.99. Stop −20% → $115.19.
  PLTR (15%) — Software IA & Datos. Entrada $146.58. Stop −20% → $117.26.
  MRVL (10%) — Silicon Fotónico & ASIC. Entrada $114.80. Stop −20% → $91.84.

Stop universal: −20% desde avg_entry para todas las posiciones.

Reglas:
  1. Stop activado       → SELL 100% inmediato
  2. Tesis rota          → SELL 100% en 1-2 días
  3. RSI >75 + 2×entrada → SELL 25% (trim)
  4. Concentración >40%  → SELL 25%, redistribuir a menor RSI
  5. Freibetrag dic.     → harvest €1,000, recompra inmediata
  6. DCA                 → RSI <45 + EMA-20

Nunca vender por: corrección general, narrativa burbuja IA sin miss earnings,
ruido geopolítico que no afecte capex de IA.
"""


# Singleton
config = Frontier5V2Config()

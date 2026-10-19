# Frontier5 Portfolio Bot System

> **Demo notes**
> - Everything in this repo uses placeholders. `ibkr_snapshot.sample.json` contains fictional data.
> - Secrets are read only from environment variables / GitHub Secrets. Nothing is hardcoded.
> - All `/api/*` routes require the header `X-Dashboard-Token` that matches the `DASHBOARD_TOKEN` environment variable. If the variable is not set, the API is disabled.
> - `ibkr_sync.py` masks the account number and does not commit anything unless `COMMIT_SNAPSHOT=true` (use that only in a private repo).

Sistema completo de monitoreo y alertas para el **Frontier5 Portfolio v2.0**.

---

## Portafolio

| Ticker | Nombre | Sector | Peso | Stop-loss |
|--------|--------|--------|------|-----------|
| NVDA | NVIDIA | AI Core | 25% | -10% |
| PLTR | Palantir | War AI | 25% | -12% |
| RTX | Raytheon | Defensa Hard | 22% | -8% |
| META | Meta Platforms | AI Ads | 18% | -10% |
| XOM | Exxon Mobil | War Hedge | 10% | -8% |

**Capital:** $----· **Entrada:** 21 Mar 2026 · **Broker:** IBKR Pro · **País:** Alemania

---

## Arquitectura

```
GitHub Actions (cron)              Render.com (always-on)
        |                                  |
intraday_scan.py  ←——————————→  webhook_server.py
earnings_alert.py                          |
quarterly_review.py              dashboard/index.html
freibetrag_bot.py                /api/quotes (live data)
        |                                  |
        └——————————— Telegram ————————————┘
                          |
                    Tu iPhone 📱
```

---

## Bots

### 1. Intraday Alert
Corre **3x/día** (9:15, 12:30, 15:45 ET). Silencio = todo bien.

**Triggers de alerta:**
- Posición cae >5% en el día
- Movimiento extremo >7% en cualquier dirección
- Stop-loss alcanzado o superado
- Noticia crítica en cualquiera de las 5 posiciones

**Telegram:** Alerta con botones ✅ Sí / ❌ No para registrar decisión.

### 2. Earnings Pre-Alert (`earnings_alert.py`)
Corre **diariamente a las 8:00 ET**. Solo envía alerta si hay earnings en 48h o 24h.

**Q1 2026 calendar:**

**Contenido del brief:** historial EPS 4 trimestres, consenso, war context, métricas clave, thesis check, recomendación.

### 3. Quarterly Review (`quarterly_review.py`)
Corre **manualmente** después de cada earnings season (mayo/agosto/noviembre/febrero).

**Contenido:** fundamentals TTM de Finnhub, upgrades/downgrades analistas (90 días), insider transactions (90 días), thesis validation por posición, recomendación de peso.

**Incluye Freibetrag analysis** automáticamente si se corre en noviembre o diciembre.

### 4. Freibetrag Bot (`freibetrag_bot.py`)
Corre **todos los lunes de diciembre**. También activable manualmente para planificación.

**Lógica:** calcula P&L no realizado en EUR para cada posición, identifica la candidata óptima para cristalizar exactamente €1,000 de ganancia libre de impuestos (Kapitalertragsteuer 26.375%), calcula cuántas shares vender y recomprar.

---

## Dashboard

Accesible en `https://tu-app.onrender.com` — instalable como PWA en iPhone.

**Tabs:**
- **Holdings** — tabla tipo broker con P&L real desde entrada (USD y %)
- **Overview** — gráficos de P&L total, rendimiento del día, distancia al stop
- **Allocation** — donut chart + desglose por posición

**Comandos Telegram:**
- `/status` — snapshot en tiempo real
- `/dashboard` — link al dashboard web
- `/decisions` — historial de decisiones YES/NO
- `/help` — lista de comandos

---

## Estructura del repo

```
Frontier5/
├── config.py                     # Portafolio, entry prices, thresholds
├── utils.py                      # Funciones compartidas (Finnhub, Claude, Telegram)
├── state.py                      # Estado persistente (decisiones YES/NO)
├── intraday_scan.py              # Bot de alertas intraday
├── earnings_alert.py             # Bot de pre-alertas earnings
├── quarterly_review.py           # Bot de revisión trimestral
├── freibetrag_bot.py             # Bot de harvest Freibetrag (diciembre)
├── webhook_server.py             # Servidor Render (dashboard + Telegram webhook)
├── requirements.txt
├── .github/workflows/
│   ├── intraday_scan.yml         # Cron 9:15, 12:30, 15:45 ET
│   ├── earnings_alert.yml        # Cron 8:00 ET diario
│   ├── quarterly_review.yml      # Manual (workflow_dispatch)
│   └── freibetrag_bot.yml        # Cron lunes de diciembre
└── dashboard/
    ├── index.html                # Dashboard PWA
    ├── manifest.json             # PWA manifest
    ├── icon-192.png              # App icon
    └── icon-512.png              # App icon
```

---

## Setup

### Secrets de GitHub (Settings → Secrets → Actions)

| Secret | Descripción |
|--------|-------------|
| `FINNHUB_API_KEY` | Finnhub free tier |
| `ANTHROPIC_API_KEY` | Claude API (Sonnet) |
| `TELEGRAM_TOKEN` | Bot token de BotFather |
| `TELEGRAM_CHAT_ID` | Tu chat ID numérico |

### Variables de Render

Las mismas 4 variables en Render dashboard → Environment.

### Registrar webhook de Telegram

```
https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<tu-app>.onrender.com/webhook
```

---

## Actualizar el portafolio

Todo en `config.py`:

```python
# Cambiar peso
{"ticker": "NVDA", "weight": 0.30, ...}  # de 0.25 a 0.30

# Actualizar entry price tras abrir posición real
ENTRY_PRICES = {
    "NVDA": 178.50,   # precio real de llenado en IBKR
    ...

---

## Reglas de operación

1. **Hold hasta que el bot hable** — silencio = todo dentro de parámetros normales
2. **Stop-loss es sagrado** — si el precio toca el nivel, venta inmediata sin excepción
3. **Tesis rota = salida** — 2 earnings misses consecutivos → revisión → salida
4. **Trim en sobrecompra** — RSI semanal >75 + posición >2× entrada → trim 25%
5. **Freibetrag harvest** — diciembre, cristalizar €1,000 de ganancia exenta
6. **No actuar por ruido** — movimientos del 3-5% son normales

---

## Costes mensuales estimados

| Servicio | Coste |
|----------|-------|
| GitHub Actions | Gratis |
| Render.com (free tier) | Gratis |
| Finnhub API (free tier) | Gratis |
| Anthropic API (Claude Sonnet) | ~$0.50/mes |
| Telegram | Gratis |
| **Total** | **~$0.50/mes** |

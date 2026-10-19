"""
state.py — Persistent state for portfolio recommendations
==========================================================
Stores pending recommendations and user decisions in a local JSON file.
In GitHub Actions the file resets each run — that's fine, since the webhook
server (always-on) maintains the authoritative state.json via its own volume.

For the scheduled scanner: writes pending recommendations to state.json
and sends them to Telegram with inline keyboards.

For the webhook server: reads state.json, records YES/NO decisions,
sends confirmation back to user.
"""

import json
import os
from datetime import datetime
import pytz

STATE_FILE = os.environ.get("STATE_FILE", "state.json")
ET         = pytz.timezone("America/New_York")


def load_state() -> dict:
    """Load state from file. Returns empty structure if not found."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "pending":  {},   # message_id -> recommendation dict
        "decisions": [],  # list of {ticker, action, decision, timestamp}
        "portfolio_overrides": {},  # ticker -> manual note
    }


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def add_pending(state: dict, message_id: str, rec: dict):
    """Register a new pending recommendation keyed by Telegram message_id."""
    state["pending"][str(message_id)] = {
        **rec,
        "sent_at": datetime.now(ET).isoformat(),
        "decision": None,
    }
    save_state(state)


def record_decision(state: dict, message_id: str, decision: str) -> dict | None:
    """
    Record YES or NO for a pending recommendation.
    Returns the recommendation dict if found, None otherwise.
    """
    rec = state["pending"].get(str(message_id))
    if not rec:
        return None

    rec["decision"]     = decision
    rec["decided_at"]   = datetime.now(ET).isoformat()

    state["decisions"].append({
        "ticker":    rec.get("ticker", ""),
        "action":    rec.get("action_summary", ""),
        "decision":  decision,
        "timestamp": rec["decided_at"],
    })
    save_state(state)
    return rec


def get_pending_for_ticker(state: dict, ticker: str) -> list:
    """Return all still-undecided recommendations for a given ticker."""
    return [
        rec for rec in state["pending"].values()
        if rec.get("ticker") == ticker and rec.get("decision") is None
    ]

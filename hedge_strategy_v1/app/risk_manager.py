from __future__ import annotations

import time
from dataclasses import dataclass

from .config import StrategyConfig
from .position_manager import estimate_effective_leverage
from .schema import WebhookPayload


@dataclass(slots=True)
class RiskDecision:
    allowed: bool
    reason: str
    estimated_leverage: float


def _expected_side(payload: WebhookPayload) -> str:
    if payload.action == "buy":
        return "long"
    if payload.action == "sell":
        return "short"
    return "flat"


def assess_risk(
    payload: WebhookPayload,
    state: dict,
    config: StrategyConfig,
) -> RiskDecision:
    symbol_config = config.symbols[payload.symbol]
    if not state["enabled"]:
        return RiskDecision(False, "symbol_disabled", float(state["estimated_leverage"]))

    if payload.role == "main" and payload.regime == "neutral":
        return RiskDecision(False, "neutral_regime", float(state["estimated_leverage"]))

    if payload.role == "hedge" and state["main_side"] == "flat":
        return RiskDecision(False, "missing_main_position", float(state["estimated_leverage"]))

    if payload.role == "hedge":
        main_side = state["main_side"]
        hedge_side = _expected_side(payload)
        if main_side == hedge_side:
            return RiskDecision(False, "hedge_same_side", float(state["estimated_leverage"]))

    now = int(time.time())
    if payload.role == "main" and payload.action in {"buy", "sell"}:
        if state["main_entries"] >= symbol_config.max_entries and state["main_side"] != "flat":
            return RiskDecision(False, "max_entries", float(state["estimated_leverage"]))
        if now - int(state["main_last_entry_at"]) < symbol_config.min_entry_interval_sec and state["main_side"] != "flat":
            return RiskDecision(False, "entry_cooldown", float(state["estimated_leverage"]))

    requested_main_qty = float(state["main_qty"])
    requested_hedge_qty = float(state["hedge_qty"])

    if payload.role == "main":
        if payload.action == "close":
            requested_main_qty = 0.0
        elif state["main_side"] == "flat":
            requested_main_qty = payload.size
        else:
            requested_main_qty += payload.size
    elif payload.role == "hedge":
        requested_hedge_qty = payload.size
    elif payload.role == "hedge_close":
        requested_hedge_qty = 0.0

    estimated_leverage = estimate_effective_leverage(
        price=payload.close,
        main_qty=requested_main_qty,
        hedge_qty=requested_hedge_qty,
    )
    if estimated_leverage > min(5.0, symbol_config.max_leverage):
        return RiskDecision(False, "leverage_limit", estimated_leverage)

    if payload.role == "hedge":
        max_hedge = requested_main_qty * symbol_config.max_hedge_ratio
        if requested_hedge_qty > max_hedge + 1e-9:
            return RiskDecision(False, "hedge_ratio_limit", estimated_leverage)

    return RiskDecision(True, "ok", estimated_leverage)


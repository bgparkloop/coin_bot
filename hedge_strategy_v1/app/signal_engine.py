from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from .config import StrategyConfig
from .risk_manager import assess_risk
from .schema import WebhookPayload


@dataclass(slots=True)
class ActionPlan:
    accepted: bool
    event_type: str
    symbol: str
    role: str
    side: str
    quantity: float
    price: float
    regime: str
    hedge_ratio: float
    estimated_leverage: float
    reason: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _side_from_action(action: str) -> str:
    if action == "buy":
        return "long"
    if action == "sell":
        return "short"
    return "flat"


def decide_action(payload: WebhookPayload, state: dict[str, Any], config: StrategyConfig) -> ActionPlan:
    risk = assess_risk(payload, state, config)
    side = _side_from_action(payload.action)
    if not risk.allowed:
        return ActionPlan(
            accepted=False,
            event_type="signal_rejected",
            symbol=payload.symbol,
            role=payload.role,
            side=side,
            quantity=payload.size,
            price=payload.close,
            regime=payload.regime,
            hedge_ratio=payload.hedge_ratio,
            estimated_leverage=risk.estimated_leverage,
            reason=risk.reason,
        )

    if payload.role == "main":
        event_type = "main_entry" if state["main_side"] == "flat" else "main_add"
        if payload.action == "close":
            event_type = "main_close"
    elif payload.role == "hedge":
        event_type = "hedge_open" if state["hedge_qty"] == 0 else "hedge_resize"
    else:
        event_type = "hedge_close"

    return ActionPlan(
        accepted=True,
        event_type=event_type,
        symbol=payload.symbol,
        role=payload.role,
        side=side,
        quantity=payload.size,
        price=payload.close,
        regime=payload.regime,
        hedge_ratio=payload.hedge_ratio,
        estimated_leverage=risk.estimated_leverage,
    )


from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class PositionSnapshot:
    symbol: str
    main_side: str
    main_qty: float
    main_avg: float
    main_entries: int
    hedge_side: str
    hedge_qty: float
    hedge_avg: float
    hedge_ratio_live: float
    regime: str
    estimated_leverage: float
    unrealized_pnl: float


def snapshot_from_state(state: dict[str, Any]) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=state["symbol"],
        main_side=state["main_side"],
        main_qty=float(state["main_qty"]),
        main_avg=float(state["main_avg"]),
        main_entries=int(state["main_entries"]),
        hedge_side=state["hedge_side"],
        hedge_qty=float(state["hedge_qty"]),
        hedge_avg=float(state["hedge_avg"]),
        hedge_ratio_live=float(state["hedge_ratio_live"]),
        regime=state["regime"],
        estimated_leverage=float(state["estimated_leverage"]),
        unrealized_pnl=float(state["unrealized_pnl"]),
    )


def estimate_effective_leverage(price: float, main_qty: float, hedge_qty: float, equity: float = 1.0) -> float:
    del price
    if equity <= 0:
        return 0.0
    # Webhook size is treated as a normalized exposure unit, not raw coin size.
    gross_exposure_units = abs(main_qty) + abs(hedge_qty)
    return gross_exposure_units / equity

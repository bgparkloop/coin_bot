from __future__ import annotations

import time

from .signal_engine import ActionPlan
from .state_store import StateStore


class ExecutionStub:
    """Applies action plans to local state without exchange side effects."""

    def __init__(self, store: StateStore):
        self.store = store

    def apply(self, plan: ActionPlan) -> dict:
        state = self.store.get_symbol_state(plan.symbol)
        now = int(time.time())

        if not plan.accepted:
            self.store.update_symbol_state(
                plan.symbol,
                regime=plan.regime,
                last_signal_at=now,
                last_action=plan.reason,
                estimated_leverage=plan.estimated_leverage,
            )
            return self.store.get_symbol_state(plan.symbol)

        if plan.role == "main":
            main_qty = 0.0 if plan.event_type == "main_close" else (
                plan.quantity if state["main_side"] == "flat" else float(state["main_qty"]) + plan.quantity
            )
            main_entries = 0 if plan.event_type == "main_close" else (
                1 if state["main_side"] == "flat" else int(state["main_entries"]) + 1
            )
            self.store.update_symbol_state(
                plan.symbol,
                regime=plan.regime,
                last_signal_at=now,
                last_action=plan.event_type,
                main_side="flat" if plan.event_type == "main_close" else plan.side,
                main_qty=main_qty,
                main_avg=0.0 if plan.event_type == "main_close" else plan.price,
                main_entries=main_entries,
                main_last_entry_at=0 if plan.event_type == "main_close" else now,
                estimated_leverage=plan.estimated_leverage,
            )
        elif plan.role == "hedge":
            self.store.update_symbol_state(
                plan.symbol,
                regime=plan.regime,
                last_signal_at=now,
                last_action=plan.event_type,
                hedge_side=plan.side,
                hedge_qty=plan.quantity,
                hedge_avg=plan.price,
                hedge_ratio_live=plan.hedge_ratio,
                estimated_leverage=plan.estimated_leverage,
            )
        else:
            self.store.update_symbol_state(
                plan.symbol,
                regime=plan.regime,
                last_signal_at=now,
                last_action=plan.event_type,
                hedge_side="none",
                hedge_qty=0.0,
                hedge_avg=0.0,
                hedge_ratio_live=0.0,
                estimated_leverage=plan.estimated_leverage,
            )

        return self.store.get_symbol_state(plan.symbol)


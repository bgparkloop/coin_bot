from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from .config import normalize_symbol


VALID_ACTIONS = {"buy", "sell", "close"}
VALID_ROLES = {"main", "hedge", "hedge_close", "main_close"}
VALID_REGIMES = {"bull", "bear", "neutral", "unknown"}


@dataclass(slots=True)
class WebhookPayload:
    action: str
    symbol: str
    size: float
    close: float
    regime: str = "unknown"
    role: str = "main"
    hedge_ratio: float = 0.0
    timeframe: str = "15"
    strategy_id: str = "hedge_strategy_v1"
    timestamp: int = field(default_factory=lambda: int(time.time()))
    raw: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def dedupe_key(self) -> str:
        parts = [
            self.action,
            self.symbol,
            f"{self.size:.8f}",
            f"{self.close:.8f}",
            self.regime,
            self.role,
            f"{self.hedge_ratio:.4f}",
            self.timeframe,
            self.strategy_id,
            str(self.timestamp // 60),
        ]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _parse_key_value(tokens: list[str]) -> dict[str, str]:
    extras: dict[str, str] = {}
    for token in tokens:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        extras[key.strip().lower()] = value.strip()
    return extras


def parse_webhook_payload(raw_text: str) -> WebhookPayload:
    tokens = [token.strip() for token in raw_text.split(",") if token.strip()]
    if len(tokens) < 4:
        raise ValueError(f"Invalid webhook payload: {raw_text}")

    action = tokens[0].lower()
    if action not in VALID_ACTIONS:
        raise ValueError(f"Unsupported action: {action}")

    symbol = normalize_symbol(tokens[1])
    size = float(tokens[2])
    close = float(tokens[3])
    extras = _parse_key_value(tokens[4:])

    regime = extras.get("regime", "unknown").lower()
    if regime not in VALID_REGIMES:
        regime = "unknown"

    role = extras.get("role", "main").lower()
    if role not in VALID_ROLES:
        role = "main"

    hedge_ratio = float(extras.get("hedge", extras.get("hedge_ratio", 0.0)) or 0.0)
    timeframe = extras.get("tf", extras.get("timeframe", "15"))
    strategy_id = extras.get("strategy_id", "hedge_strategy_v1")
    timestamp = int(float(extras.get("timestamp", time.time())))

    return WebhookPayload(
        action=action,
        symbol=symbol,
        size=size,
        close=close,
        regime=regime,
        role=role,
        hedge_ratio=hedge_ratio,
        timeframe=timeframe,
        strategy_id=strategy_id,
        timestamp=timestamp,
        raw=raw_text,
        extras=extras,
    )


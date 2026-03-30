from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "hedge_strategy.db"


@dataclass(slots=True)
class SymbolConfig:
    symbol: str
    max_leverage: float
    default_hedge_ratio: float
    max_hedge_ratio: float
    max_entries: int
    min_entry_interval_sec: int
    min_atr_gap_ratio: float
    commission_rate: float
    slippage_ticks: int
    tick_size: float
    enabled: bool = True


@dataclass(slots=True)
class TelegramConfig:
    token: str = ""
    chat_id: str = ""
    enabled: bool = False


@dataclass(slots=True)
class StrategyConfig:
    db_path: str = str(DEFAULT_DB_PATH)
    debounce_seconds: int = 60
    stale_signal_seconds: int = 600
    regime_timeframes: tuple[str, str, str] = ("15", "60", "240")
    symbols: dict[str, SymbolConfig] = field(default_factory=dict)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)


def _symbol_defaults() -> dict[str, SymbolConfig]:
    return {
        "BTCUSDT.P": SymbolConfig(
            symbol="BTCUSDT.P",
            max_leverage=5.0,
            default_hedge_ratio=0.25,
            max_hedge_ratio=0.5,
            max_entries=3,
            min_entry_interval_sec=900,
            min_atr_gap_ratio=0.6,
            commission_rate=0.0005,
            slippage_ticks=8,
            tick_size=0.1,
        ),
        "ETHUSDT.P": SymbolConfig(
            symbol="ETHUSDT.P",
            max_leverage=3.0,
            default_hedge_ratio=0.25,
            max_hedge_ratio=0.5,
            max_entries=3,
            min_entry_interval_sec=900,
            min_atr_gap_ratio=0.7,
            commission_rate=0.0005,
            slippage_ticks=6,
            tick_size=0.01,
        ),
    }


def normalize_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    if symbol.endswith("/USDT:USDT"):
        return symbol.replace("/USDT:USDT", "USDT.P")
    return symbol


def _read_yaml_config() -> dict[str, Any]:
    config_path = Path(__file__).resolve().parents[2] / "configs" / "config_okx.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml  # type: ignore
    except Exception:
        return {}
    with config_path.open(encoding="utf-8") as fh:
        return yaml.load(fh, Loader=yaml.FullLoader) or {}


def load_config() -> StrategyConfig:
    config = StrategyConfig(symbols=_symbol_defaults())
    raw = _read_yaml_config()

    telegram = raw.get("TELEGRAM", {})
    token = os.getenv("HEDGE_TELEGRAM_TOKEN") or telegram.get("TOKEN", "")
    chat_id = os.getenv("HEDGE_TELEGRAM_CHAT_ID") or telegram.get("ID", "")
    config.telegram = TelegramConfig(
        token=token,
        chat_id=str(chat_id) if chat_id else "",
        enabled=bool(token and chat_id),
    )

    targets = raw.get("OKX", {}).get("TARGET", [])
    options = raw.get("TRADE_OPTION", {})
    for target in targets:
        ticker = target.split("/")[0].upper()
        tv_symbol = f"{ticker}USDT.P"
        if tv_symbol not in config.symbols:
            continue
        symbol_config = config.symbols[tv_symbol]
        trade_option = options.get(ticker, {})
        leverage = float(trade_option.get("leverage", symbol_config.max_leverage))
        symbol_config.max_leverage = min(5.0, leverage)

    db_path = os.getenv("HEDGE_DB_PATH")
    if db_path:
        config.db_path = db_path
    return config


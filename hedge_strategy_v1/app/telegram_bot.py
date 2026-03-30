from __future__ import annotations

from typing import Callable, Awaitable

from .config import StrategyConfig
from .notifier import render_help_message, render_status_message
from .state_store import StateStore


class TelegramCommandHandler:
    def __init__(self, store: StateStore, config: StrategyConfig):
        self.store = store
        self.config = config

    def handle_command(self, text: str) -> str:
        tokens = text.strip().split()
        if not tokens:
            return render_help_message()

        cmd = tokens[0].lower().lstrip("/")
        if cmd == "help":
            return render_help_message()
        if cmd in {"show", "status"}:
            return render_status_message(
                self.store.all_symbol_states(),
                self.store.get_trading_enabled(),
                self.store.recent_events(),
            )
        if cmd == "trade" and len(tokens) >= 2:
            enabled = tokens[1] != "0"
            self.store.set_trading_enabled(enabled)
            return f"전체 거래 상태가 {'활성화' if enabled else '중지'} 로 변경되었습니다."
        if cmd == "set" and len(tokens) == 3 and tokens[2].lower() in {"on", "off"}:
            return self._handle_symbol_toggle(tokens[1], tokens[2])
        if cmd == "set" and len(tokens) >= 4:
            return self._handle_set(tokens[1:])
        return "지원하지 않는 명령어입니다. help 를 확인하세요."

    def _handle_symbol_toggle(self, symbol: str, value: str) -> str:
        enabled = value.lower() == "on"
        self.store.update_symbol_state(symbol.upper(), enabled=1 if enabled else 0)
        return f"{symbol.upper()} 거래 상태가 {'활성화' if enabled else '비활성화'} 되었습니다."

    def _handle_set(self, tokens: list[str]) -> str:
        symbol = tokens[0].upper()
        state = self.store.get_symbol_state(symbol)
        key = tokens[1].lower()
        value = tokens[2].lower()
        if key == "lev":
            leverage = min(5.0, float(value))
            self.store.update_symbol_state(symbol, max_leverage=leverage)
            return f"{symbol} 최대 레버리지가 {leverage:.2f} 로 변경되었습니다."
        if key == "hedge":
            hedge_ratio = float(value)
            if hedge_ratio not in {0.0, 0.25, 0.5}:
                return "hedge 값은 0, 0.25, 0.5 만 허용됩니다."
            self.store.update_symbol_state(symbol, hedge_ratio=hedge_ratio)
            return f"{symbol} 기본 헤지 비율이 {hedge_ratio:.2f} 로 변경되었습니다."
        if key in {"on", "off"}:
            enabled = key == "on"
            self.store.update_symbol_state(symbol, enabled=1 if enabled else 0)
            return f"{symbol} 거래 상태가 {'활성화' if enabled else '비활성화'} 되었습니다."
        if value in {"on", "off"}:
            enabled = value == "on"
            self.store.update_symbol_state(symbol, enabled=1 if enabled else 0)
            return f"{symbol} 거래 상태가 {'활성화' if enabled else '비활성화'} 되었습니다."
        _ = state
        return "지원하지 않는 set 명령입니다."


class TelegramNotifier:
    def __init__(self, config: StrategyConfig):
        self.config = config
        self._bot = None
        if config.telegram.enabled:
            try:
                from telegram import Bot  # type: ignore
            except Exception:
                self._bot = None
            else:
                self._bot = Bot(token=config.telegram.token)

    async def send(self, message: str) -> bool:
        if not self.config.telegram.enabled or self._bot is None:
            return False
        await self._bot.send_message(
            chat_id=self.config.telegram.chat_id,
            text=message,
        )
        return True


async def maybe_notify(send_fn: Callable[[str], Awaitable[bool]], message: str) -> None:
    try:
        await send_fn(message)
    except Exception:
        return

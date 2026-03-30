from __future__ import annotations

from dataclasses import asdict

from .config import load_config
from .executor_stub import ExecutionStub
from .notifier import render_trade_message
from .schema import parse_webhook_payload
from .signal_engine import decide_action
from .state_store import StateStore
from .telegram_bot import TelegramCommandHandler, TelegramNotifier, maybe_notify

try:
    from fastapi import FastAPI, HTTPException, Request  # type: ignore
except Exception:  # pragma: no cover
    FastAPI = None
    HTTPException = Exception
    Request = object


config = load_config()
store = StateStore(config)
store.bootstrap_symbols(config)
executor = ExecutionStub(store)
telegram_handler = TelegramCommandHandler(store, config)
telegram_notifier = TelegramNotifier(config)


def handle_webhook_text(raw_text: str) -> dict:
    payload = parse_webhook_payload(raw_text)
    if store.is_duplicate(payload.dedupe_key, config.debounce_seconds):
        state = store.get_symbol_state(payload.symbol)
        plan = decide_action(payload, state, config)
        plan.accepted = False
        plan.event_type = "signal_rejected"
        plan.reason = "duplicate_signal"
    elif not store.get_trading_enabled():
        state = store.get_symbol_state(payload.symbol)
        plan = decide_action(payload, state, config)
        plan.accepted = False
        plan.event_type = "signal_rejected"
        plan.reason = "trading_disabled"
    else:
        state = store.get_symbol_state(payload.symbol)
        plan = decide_action(payload, state, config)

    updated_state = executor.apply(plan)
    message = render_trade_message(plan, updated_state)
    store.log_event(payload.symbol, plan.event_type, plan.reason if not plan.accepted else plan.event_type, asdict(payload))
    return {
        "accepted": plan.accepted,
        "plan": plan.to_dict(),
        "state": updated_state,
        "message": message,
    }


if FastAPI is not None:  # pragma: no branch
    app = FastAPI(title="hedge_strategy_v1")

    @app.get("/hedge/health")
    async def healthcheck():
        return {"status": "ok"}

    @app.post("/hedge/webhook")
    async def webhook(request: Request):
        body = await request.body()
        raw_text = body.decode("utf-8").strip()
        if not raw_text:
            raise HTTPException(status_code=400, detail="empty webhook payload")
        result = handle_webhook_text(raw_text)
        await maybe_notify(telegram_notifier.send, result["message"])
        return result


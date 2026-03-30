from __future__ import annotations

from datetime import datetime

from .position_manager import snapshot_from_state
from .signal_engine import ActionPlan


def render_trade_message(plan: ActionPlan, state: dict) -> str:
    snap = snapshot_from_state(state)
    lines = [
        "============================================",
        f"[{plan.event_type}] {plan.symbol}",
        f"시간 : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"역할 : {plan.role}",
        f"방향 : {plan.side}",
        f"수량 : {plan.quantity:.4f}",
        f"가격 : {plan.price:.4f}",
        f"Regime : {plan.regime}",
        f"Hedge Ratio : {snap.hedge_ratio_live:.2f}",
        f"예상 실효 레버리지 : {snap.estimated_leverage:.2f}x",
        f"메인 : {snap.main_side} {snap.main_qty:.4f} @ {snap.main_avg:.4f}",
        f"헤지 : {snap.hedge_side} {snap.hedge_qty:.4f} @ {snap.hedge_avg:.4f}",
    ]
    if not plan.accepted:
        lines.append(f"거부 사유 : {plan.reason}")
    lines.append("============================================")
    return "\n".join(lines)


def render_status_message(states: list[dict], trading_enabled: bool, events: list[dict]) -> str:
    lines = [
        "============================================",
        "[Hedge Strategy Status]",
        f"거래 상태 : {'활성화' if trading_enabled else '중지'}",
    ]
    for item in states:
        snap = snapshot_from_state(item)
        lines.extend(
            [
                f"- {snap.symbol} | regime={snap.regime} | lev={snap.estimated_leverage:.2f}x",
                f"  main={snap.main_side} {snap.main_qty:.4f} @ {snap.main_avg:.4f} entries={snap.main_entries}",
                f"  hedge={snap.hedge_side} {snap.hedge_qty:.4f} ratio={snap.hedge_ratio_live:.2f}",
            ]
        )
    if events:
        lines.append("최근 이벤트:")
        for event in events[:5]:
            lines.append(f"- {event['symbol']} {event['event_type']} :: {event['message']}")
    lines.append("============================================")
    return "\n".join(lines)


def render_help_message() -> str:
    return (
        "============================================\n"
        "[Telegram Commands]\n"
        "show : 현재 포지션 및 리스크 상태 표시\n"
        "status : 최근 이벤트와 추세 상태 표시\n"
        "help : 명령어 도움말\n"
        "trade 0|1 : 전체 거래 중지/재개\n"
        "set [symbol] lev [n] : 종목별 최대 레버리지 설정 (<=5)\n"
        "set [symbol] hedge [0|0.25|0.5] : 기본 헤지 비율 설정\n"
        "set [symbol] on|off : 종목 거래 활성화/비활성화\n"
        "============================================"
    )


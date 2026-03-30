# hedge_strategy_v1

독립 실행형 저레버리지 hedge 전략 패키지입니다. 기존 거래 코드는 건드리지 않고, 별도 FastAPI webhook / SQLite 상태 저장 / Telegram 명령 / TradingView Pine Script를 제공합니다.

## 구성

- `tv_strategy_hedge.pine`: 백테스트 가능한 TradingView strategy
- `tv_indicator_hedge.pine`: 시각화 중심 indicator
- `app/webhook_app.py`: `/hedge/webhook`, `/hedge/health`
- `app/telegram_bot.py`: Telegram 명령과 알림 송신
- `app/state_store.py`: SQLite 상태 저장

## 전략 개요

- 대상: BTC, ETH
- 실효 레버리지: 최대 5배
- 추세 필터: 기본 `60m / 240m EMA`, 선택형 `Market Structure`, `VWAP+EMA`
- 거래량 필터: 기본 `15m volume / volume EMA 배수`, 선택형 `Relative Volume`, `OBV Confirm`
- 메인 포지션: 추세 방향만 진입
- 메인 진입: `15m EMA 눌림 회복` 전용
- 헤지 포지션: 메인 포지션이 있을 때만 방어용 오버레이, Pine 백테스트에서는 주문이 아니라 alert/visual로 분리

## Pine 모델

- `Trend Model`
  - `EMA` 기본
  - `STRUCTURE`
  - `VWAP_EMA`
- `Volume Model`
  - `VOL_EMA_MULT` 기본
  - `RELATIVE_VOLUME`
  - `OBV_CONFIRM`
- `Hedge Mode`
  - `DEFENSIVE_ONLY` 기본
  - `OFF`
- `Quality Preset`
  - `conservative` 기본
  - `balanced`

기본 preset은 `VWAP_EMA + OBV_CONFIRM + conservative` 이며, 타점 품질과 MDD 감소를 우선한다.

## 웹훅 포맷

기본:

```text
buy,BTCUSDT.P,1,67250
sell,ETHUSDT.P,0.5,3120
```

확장:

```text
buy,BTCUSDT.P,1,67250,regime=bull,role=main,hedge=0,tf=15
sell,BTCUSDT.P,0.25,66810,regime=bull,role=hedge,hedge=0.25,tf=15
close,BTCUSDT.P,0.25,67020,role=hedge_close
```

## 실행

FastAPI와 python-telegram-bot이 설치되어 있으면 아래처럼 별도 프로세스로 실행할 수 있습니다.

```bash
uvicorn hedge_strategy_v1.app.webhook_app:app --host 0.0.0.0 --port 8001
```

환경 변수:

- `HEDGE_DB_PATH`: SQLite 경로 override
- `HEDGE_TELEGRAM_TOKEN`: Telegram token override
- `HEDGE_TELEGRAM_CHAT_ID`: Telegram chat id override

기본값이 있으면 `configs/config_okx.yaml`의 Telegram 설정을 재사용합니다.

## Telegram 명령

- `show`
- `status`
- `help`
- `trade 0|1`
- `set BTCUSDT.P lev 3`
- `set BTCUSDT.P hedge 0.25`

## 백테스트 기준

- TradingView `strategy()` 기반
- 메인 전략만 백테스트하고 hedge는 alert overlay로 분리
- 수수료 percent 입력
- 슬리피지 tick 입력
- pyramiding 3
- bar close 체결 기준

## 테스트

표준 라이브러리 기준 unittest:

```bash
python3 -m unittest discover hedge_strategy_v1/tests
```

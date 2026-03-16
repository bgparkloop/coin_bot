# coin_bot

## OKX mode settings

`configs/config_okx.yaml`

- `OKX.POSITION_MODE`: `one_way` or `hedge`
- `OKX.ENVIRONMENT`: `live` or `demo`

`one_way` keeps the existing `posSide=net` flow. `hedge` enables side-separated long/short handling with `posSide=long|short`.

When `POSITION_MODE=hedge`, startup verifies the OKX account position mode and tries to switch it to hedge mode before the app starts handling webhook traffic.

Recommended settings:

```yaml
OKX:
  POSITION_MODE: 'hedge'
  ENVIRONMENT: 'live'
```

Use `ENVIRONMENT: 'demo'` only with OKX demo API keys. Live keys and demo keys are not interchangeable.

## Trade behavior

### One-way mode

- Existing behavior is preserved.
- Orders use `posSide=net`.
- Telegram status messages show a single net position per symbol.

### Hedge mode

- Orders use side-separated positions with `posSide=long` and `posSide=short`.
- A `buy` webhook signal is treated as a `long` signal.
- A `sell` webhook signal is treated as a `short` signal.

Signal handling:

- `long` signal
  - if no long exists, open long
  - if long exists and add condition is satisfied, add long
  - if short exists, close only the incoming signal size from short
- `short` signal
  - if no short exists, open short
  - if short exists and add condition is satisfied, add short
  - if long exists, close only the incoming signal size from long

Additional notes:

- In hedge mode, one signal does not both close the opposite side and open the new side in the same call.
- In hedge mode, `use_short` is ignored.
- Telegram status messages show `Long` and `Short` separately for each symbol.
- Startup fails if the account cannot be verified or switched into OKX hedge mode.

## Telegram output

### One-way

- Existing single-position output is unchanged.

### Hedge

- Each symbol is rendered with two lines:
  - `Long`
  - `Short`
- Each side shows:
  - current size
  - `buy_cnt / max_buy_cnt`
  - average entry price
  - unrealized PnL
  - ROE

## Hedge validation scripts

The repo includes two helper scripts for validating OKX hedge mode behavior without the Telegram flow.

- `open_pos.py`
  - opens a long position
  - waits 5 seconds
  - opens a short position
  - prints the long/short position snapshot after each step
- `close_pos.py`
  - closes the current long position if it exists
  - waits 5 seconds
  - closes the current short position if it exists
  - prints the long/short position snapshot after each step

Examples:

```bash
python3 open_pos.py --env demo
python3 close_pos.py --env demo
```

For live verification:

```bash
python3 open_pos.py --env live
python3 close_pos.py --env live
```

Optional flags:

- `--symbol BTC/USDT:USDT`
- `--trade-vol 1`
- `--wait-seconds 5`

If you see `50101 APIKey does not match current environment`, the script environment and the API key environment do not match.

- live key -> run with `--env live`
- demo key -> run with `--env demo`

## Operational checklist

Before enabling hedge mode in the main service:

1. Confirm the OKX account is a derivatives account and not a portfolio margin flow that only supports net mode.
2. Confirm the API key matches the configured environment.
3. Run `open_pos.py` and `close_pos.py` once in the target environment.
4. Set `POSITION_MODE` in `configs/config_okx.yaml`.
5. Restart the FastAPI service and confirm startup succeeds without hedge mode errors.
6. Send a small webhook test and confirm Telegram shows separate long/short state lines.

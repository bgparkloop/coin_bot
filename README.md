# coin_bot

## OKX mode settings

`configs/config_okx.yaml`

- `OKX.POSITION_MODE`: `one_way` or `hedge`
- `OKX.ENVIRONMENT`: `live` or `demo`

`one_way` keeps the existing `posSide=net` flow. `hedge` enables side-separated long/short handling with `posSide=long|short`.

When `POSITION_MODE=hedge`, startup verifies the OKX account position mode and tries to switch it to hedge mode before the app starts handling webhook traffic.

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

Optional flags:

- `--symbol BTC/USDT:USDT`
- `--trade-vol 1`
- `--wait-seconds 5`

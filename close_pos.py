import argparse
import asyncio

from core.trader import Bot


def parse_args():
    parser = argparse.ArgumentParser(description="Close OKX hedge positions for validation")
    parser.add_argument("--symbol", help="Target symbol, defaults to first config target")
    parser.add_argument("--trade-vol", type=float, default=1.0, help="Unused fallback volume in bot count units")
    parser.add_argument("--env", choices=["live", "demo"], default="demo", help="Exchange environment")
    parser.add_argument("--wait-seconds", type=float, default=5.0, help="Delay between long and short close")
    return parser.parse_args()


def find_contracts(bot, symbol, side):
    positions = bot.api.fetch_positions()
    for pos in positions:
        if pos.get("symbol") != symbol:
            continue
        if bot.get_position_side(pos) != side:
            continue
        contracts = float(pos.get("contracts") or 0)
        if contracts > 0:
            return contracts
    return 0


def print_snapshot(bot, symbol):
    positions = bot.api.fetch_positions()
    print(f"[snapshot] {symbol}")
    for side in ("long", "short"):
        found = False
        for pos in positions:
            if pos.get("symbol") != symbol:
                continue
            if bot.get_position_side(pos) != side:
                continue
            contracts = float(pos.get("contracts") or 0)
            if contracts <= 0:
                continue
            print(
                f"  {side}: contracts={contracts} entry={pos.get('entryPrice')} "
                f"pnl={pos.get('unrealizedPnl')} roe={pos.get('percentage')}"
            )
            found = True
        if not found:
            print(f"  {side}: empty")


async def main():
    args = parse_args()
    bot = Bot()
    bot.trader.config["OKX"]["POSITION_MODE"] = "hedge"
    bot.trader.config["OKX"]["ENVIRONMENT"] = args.env
    bot.setup_api()
    await bot.ensure_exchange_mode()

    symbol = args.symbol or bot.trader.get_target_symbols()[0]
    print(f"[close] symbol={symbol} env={args.env}")

    long_contracts = find_contracts(bot, symbol, "long")
    if long_contracts > 0:
        long_order = await bot.market_order_hedge(symbol, "long", "close", vol=long_contracts)
        print(f"long close order id={long_order['id']}")
    else:
        print("long position empty")
    await asyncio.sleep(args.wait_seconds)
    print_snapshot(bot, symbol)

    short_contracts = find_contracts(bot, symbol, "short")
    if short_contracts > 0:
        short_order = await bot.market_order_hedge(symbol, "short", "close", vol=short_contracts)
        print(f"short close order id={short_order['id']}")
    else:
        print("short position empty")
    await asyncio.sleep(args.wait_seconds)
    print_snapshot(bot, symbol)


if __name__ == "__main__":
    asyncio.run(main())

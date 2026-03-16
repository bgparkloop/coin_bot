import argparse
import asyncio

from core.trader import Bot


def parse_args():
    parser = argparse.ArgumentParser(description="Open OKX hedge positions for validation")
    parser.add_argument("--symbol", help="Target symbol, defaults to first config target")
    parser.add_argument("--trade-vol", type=float, default=1.0, help="Trade volume in bot count units")
    parser.add_argument("--env", choices=["live", "demo"], default="demo", help="Exchange environment")
    parser.add_argument("--wait-seconds", type=float, default=5.0, help="Delay between long and short")
    return parser.parse_args()


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
    min_vol = bot.trader.get_info(symbol, key="min_vol")
    order_amount = min_vol * args.trade_vol

    print(f"[open] symbol={symbol} env={args.env} amount={order_amount}")
    long_order = await bot.market_order_hedge(symbol, "long", "open", vol=order_amount)
    print(f"long order id={long_order['id']}")
    await asyncio.sleep(args.wait_seconds)
    print_snapshot(bot, symbol)

    short_order = await bot.market_order_hedge(symbol, "short", "open", vol=order_amount)
    print(f"short order id={short_order['id']}")
    await asyncio.sleep(args.wait_seconds)
    print_snapshot(bot, symbol)


if __name__ == "__main__":
    asyncio.run(main())

from fastapi import FastAPI, Request, HTTPException, Depends
import asyncio
from datetime import datetime
from pytz import timezone

from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters,
)

from telegram import Update

from core.trader import Bot

# ======================================================
# FastAPI
# ======================================================
app = FastAPI()

# ======================================================
# Telegram Bot
# ======================================================
bot = Bot()

tg_app = (
    ApplicationBuilder()
    .token(bot.trader.get_telegram_token())
    .build()
)

bot.set_msgbot(tg_app.bot)

# ---------- Telegram message handler ----------
async def telegram_msg_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await bot.msg_handler(update, context)

tg_app.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, telegram_msg_handler)
)

# ======================================================
# Background task
# ======================================================
async def periodic_task(interval: int):
    while True:
        try:
            msg = await bot.update_positions()
            await bot.post_message(msg)
        except Exception as e:
            print("Periodic task error:", e)
        await asyncio.sleep(interval)

# ======================================================
# FastAPI lifecycle
# ======================================================
@app.on_event("startup")
async def on_startup():
    # Telegram initialize
    await tg_app.initialize()
    await tg_app.start()

    # 시작 메시지
    start_msg = await bot.start_msg()
    await bot.post_message(start_msg)

    # 주기 작업 시작
    asyncio.create_task(periodic_task(15))


@app.on_event("shutdown")
async def on_shutdown():
    await tg_app.stop()
    await tg_app.shutdown()

# ======================================================
# TradingView Webhook
# ======================================================
ALLOWED_IPS = {
    "52.89.214.238",
    "34.212.75.30",
    "54.218.53.128",
    "52.32.178.7",
}

def check_ip(request: Request):
    client_ip = request.client.host
    if client_ip not in ALLOWED_IPS:
        raise HTTPException(status_code=403, detail="Access forbidden")

@app.post("/webhook", dependencies=[Depends(check_ip)])
async def receive_webhook(request: Request):
    body = await request.body()
    text = body.decode("utf-8")

    print("Webhook:", text)

    tokens = text.split(",")

    if tokens[0] == "buy":
        position = "long"
    elif tokens[0] == "sell":
        position = "short"
    else:
        position = None

    target_symbol = tokens[1]

    if len(tokens) > 3:
        position_size = float(tokens[2])
        cur_close = float(tokens[3])
    else:
        position_size = 1
        cur_close = 0

    print(
        datetime.now(timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S"),
        target_symbol,
        position,
        position_size,
        cur_close,
    )

    if position is None:
        msg = await bot.update_positions()
        await bot.post_message(msg)
    else:
        await bot.trade(
            symbol=target_symbol,
            check_pos=position,
            trade_vol=position_size,
            cur_close=cur_close,
        )

    return {"status": "ok"}

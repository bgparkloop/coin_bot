from fastapi import FastAPI, Request, HTTPException, Depends
import httpx
import threading
import asyncio
from pytz import timezone
from datetime import datetime
import traceback
from core.trader import Bot


app = FastAPI()
bot = Bot()
bot.setup()

async def periodic_task(interval):
    while True:
        msg = await bot.update_positions()
        await bot.post_message(msg)
        await asyncio.sleep(interval)  # interval 초 동안 대기

# 주기적으로 비동기 함수 실행
@app.on_event("startup")
async def on_startup():
    # 5초마다 실행
    asyncio.create_task(periodic_task(15))
    # asyncio.create_task(independent_task())


# 허용할 IP 주소 목록
ALLOWED_IPS = {"52.89.214.238", "34.212.75.30", "54.218.53.128", "52.32.178.7"}

def check_ip(request: Request):
    client_ip = request.client.host
    if client_ip not in ALLOWED_IPS:
        raise HTTPException(status_code=403, detail="Access forbidden: IP not allowed")

@app.post("/webhook", dependencies=[Depends(check_ip)])
async def receive_webhook(request: Request):
    """
        payload format
        {"symbol": "{{ticker}}", "position": "{{check_pos}}", "cur_close": {{close}}}
    """
    body = await request.body()  # Request 본문을 byte로 읽음
    text = body.decode('utf-8') 

    """
        text 예시
        Price_Action (close, 26, 10, 1, 2, 7, 3): 
        order sell @ 1 filled on BTCUSDT.P. New strategy position is -39
    """
    print('Content : ', text)
    tokens = text.split(',')
    print('Tokens : ', tokens)

    if tokens[0] == 'buy':
        position = 'long'
    elif tokens[0] == 'sell':
        position = 'short'
    else:
        position = None

    target_symbol = tokens[1]

    if len(tokens) > 2:
        position_size = float(tokens[1])
        cur_close = float(tokens[2])
    else:
        position_size = 1
        cur_close = 0

    print('Before Processed ', target_symbol, position, position_size, cur_close)

    # 받은 웹훅 데이터를 처리
    if position is None:
        msg = await bot.update_positions()
        bot.post_message(msg)
    else:
        print(datetime.now(timezone('Asia/Seoul')).strftime("%m/%d/%Y, %H:%M:%S"))
        print('Content : ', text)
        print(target_symbol, position_size, cur_close)

        async with asyncio.Lock():
            await bot.trade(
                symbol=target_symbol,
                check_pos=position,
                trade_vol=position_size,
                cur_close=cur_close,
            )

    return {"status": "Webhook received"}

if __name__ == "__main__":
    """
        https://www.uvicorn.org/
    """
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=80, log_level="error")

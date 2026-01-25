import os
import json
import aiofiles
import time
import random
import copy
import asyncio
import ccxt
import numpy as np
from pytz import timezone
from datetime import datetime
import pandas as pd
import traceback
from datetime import datetime
from pytz import timezone

import telegram
from core.user import UserData


class Bot:
    """
        Bot 클래스 기능 정리
        - ccxt 기반 주문, 계좌 정보 조회
        - Telegram을 통한 주문 기록 및 현재 상태 조회
    """
    def __init__(self):
        self.telegram_chk = False
        self.msg_bot = None
        self.setup()

    def setup(self):
        self.trader = UserData()
        self.api = ccxt.okx({
                    'apiKey': self.trader.config['OKX']['API'],
                    'secret': self.trader.config['OKX']['SECRET_KEY'],
                    'password': self.trader.config['OKX']['PASSWD'],
                    'enableRateLimit': True, # required https://github.com/ccxt/ccxt/wiki/Manual#rate-limit
                    'timeout': 30000,
                    'options': {
                        'defaultType': 'swap',
                        "adjustForTimeDifference": True
                    },})

        self.go_trade = True
        self.timeframe = '15m'
        self.req_data_cnt = 300

    def set_msgbot(self, msg_bot):
        self.msg_bot = msg_bot

    # ==============================
    # Telegram 메시지 전송 (FIX)
    # ==============================
    async def post_message(self, msg):
        if msg is not None:
            await self.msgbot.send_message(
                chat_id=self.trader.get_telegram_id(),
                text=msg
            )

    # ==============================
    # Telegram message handler (FIX)
    # ==============================
    async def msg_handler(self, update, context):
        user_text = update.message.text
        tokens = user_text.split()
        print('tokens : ', tokens)

        if tokens[0].lower() == 'set':
            if len(tokens) > 3:
                for target_symbol in self.trader.get_target_symbols():
                    if tokens[1].lower() in target_symbol.lower():

                        if tokens[2].lower() == 'lev':
                            lev = float(tokens[3])
                            self.trader.update(target_symbol, key='leverage', value=lev)
                            await self.set_leverage(target_symbol, lev, 'cross')
                            await self.set_leverage(target_symbol, lev, 'isolated')

                        elif tokens[2].lower() == 'cnt':
                            cnt = float(tokens[3])
                            self.trader.update(target_symbol, key='max_buy_cnt', value=cnt)

                        elif tokens[2].lower() == 'mv':
                            cnt = float(tokens[3])
                            min_vol = cnt * 0.1
                            self.trader.update(target_symbol, key='min_vol', value=min_vol)

                        elif tokens[2].lower() == 'add':
                            ratio = float(tokens[3])
                            self.trader.update(target_symbol, key='new_buy_roe', value=ratio)

                        elif tokens[2].lower() == 'trade':
                            flag = float(tokens[3]) != 0
                            self.trader.update(target_symbol, key='go_trade', value=flag)

            elif len(tokens) == 3:
                if tokens[1].lower() == 'trade':
                    flag = float(tokens[2]) != 0
                    for target_symbol in self.trader.get_target_symbols():
                        self.trader.update(target_symbol, key='go_trade', value=flag)

                elif tokens[1].lower() == 'short':
                    flag = float(tokens[2]) != 0
                    for target_symbol in self.trader.get_target_symbols():
                        self.trader.update(target_symbol, key='use_short', value=flag)

            msg = await self.update_positions()
            await self.post_message(msg)

            msg = await self.status_msg()
            await self.post_message(msg)

        elif tokens[0].lower() == 'show':
            msg = await self.status_msg()
            await self.post_message(msg)

    # ==============================
    # 기존 로직 이하 전부 그대로
    # ==============================

    async def update_positions(self):
        old_balance = self.trader.get_info(None, 'balance')

        positions = self.api.fetch_positions()
        indexed = self.api.index_by(positions, 'contracts')

        check = False
        msg = None

        self.set_balance()

        for target_symbol in self.trader.get_target_symbols():
            chk = True
            for pos in positions:
                pos_symbol = pos['symbol']
                entry_price = pos['entryPrice']
                pos_side = pos['side']
                n_contracts = float(pos['contracts'])

                if n_contracts > 0 and target_symbol == pos_symbol:
                    self.trader.update(target_symbol, key='avg_buy_price', value=float(entry_price))

                    div_num = float(self.trader.get_info(target_symbol, key='map_vol'))
                    belong_vol = n_contracts / div_num

                    self.trader.update(target_symbol, key='position', value=pos_side)

                    amt = n_contracts
                    if amt != self.trader.get_belong_vol(target_symbol):
                        self.trader.update(target_symbol, key='amt', value=belong_vol)
                        check = True

                    if amt > 0:
                        cnt = self.trader.recal_pos_list(target_symbol, amt)
                        self.trader.update(target_symbol, key='buy_cnt', value=cnt)

                    chk = False
                    break

            if chk:
                if self.trader.get_belong_vol(target_symbol) != 0:
                    check = True

                self.trader.update(target_symbol, key='position', value=None)
                self.trader.update(target_symbol, key='buy_cnt', value=0)
                self.trader.update(target_symbol, key='amt', value=0)
                self.trader.update(target_symbol, key='avg_buy_price', value=0)
                self.trader.update(target_symbol, key='position_list', value=[])

        if check or old_balance != await self.get_balance():
            msg = await self.status_msg()
            self.set_balance()
            return msg

        return msg

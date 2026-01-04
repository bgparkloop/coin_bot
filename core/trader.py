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
# import telegram
# from telegram.ext import *
from telegram import Bot, Update
from telegram.ext import (
    ApplicationBuilder, MessageHandler, ContextTypes, filters
)
import asyncio
from core.user import UserData



class Bot():
    """
        Bot 클래스 기능 정리
        - ccxt 기반 주문, 계좌 정보 조회
        - Telegram을 통한 주문 기록 및 현재 상태 조회
    """
    def __init__(self):
        self.telegram_chk = False
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

        if not self.telegram_chk:
            self.app = (
                ApplicationBuilder()
                .token(self.trader.get_telegram_token())
                .post_init(self.on_startup)   # ✔️ 여기!
                .read_timeout(10)
                .write_timeout(10)
                .build()
            )

            # bot 객체 얻기
            self.msgbot = self.app.bot

            # 메시지 핸들러 등록
            self.app.add_handler(MessageHandler(filters.TEXT, self.msg_handler))

            # self.msgbot = telegram.Bot(token=self.trader.get_telegram_token())
            # self.updater = Updater(self.trader.get_telegram_token(), use_context=True)

            # self.updater.dispatcher.add_handler(MessageHandler(Filters.text, self.msg_handler))
            # self.updater.start_polling(timeout=10)
            
            self.telegram_chk = True

            msg = self.start_msg()
            self.post_message(msg)

    # ========== OKX API ===================
    async def fetch_market_info(self):
        return self.api.fetch_markets()

    async def get_data(self, target_symbol):
        data = self.api.fetch_ohlcv(symbol=target_symbol,
                                    timeframe=self.timeframe,
                                    limit=self.req_data_cnt)

        data = pd.DataFrame(data, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        
        return data

    async def get_balance(self):
        d = self.api.fetch_balance()
        total_balance = float(d['USDT']['free'])

        return total_balance

    async def get_old_balance(self):
        return self.balance

    async def get_balance_info(self):
        d = self.api.fetch_balance()
        d2 = d['info']['data'][0]['details'][0]

        total_sum = float(d2['cashBal'])
        cur_balance = float(d2['eq'])
        unpnl = float(d2['upl'])

        return total_sum, cur_balance, unpnl

    async def fetch_order(self, target_symbol, order_id):
        return self.api.fetch_order(order_id, target_symbol)

    async def market_order(self, target_symbol, position='long', vol=0, trade_type='buy', margin_mode='cross'):
        if margin_mode == 'cross':
            params = {"tdMode" : "cross", "mgnMode" : "cross", "posSide": "net" }
        elif margin_mode == 'isolated':
            params = {"tdMode" : "isolated", "mgnMode" : "isolated", "posSide": "net" }

        if trade_type == 'buy':
            if position == 'long':
                print('BUY LONG OPEN', target_symbol)
                print()

                return self.api.create_order(symbol=target_symbol,
                                            amount=vol,
                                            type='market',
                                            side='buy',
                                            params=params
                                            )
            elif position == 'short':
                print('BUY SHORT OPEN', target_symbol)
                print()

                return self.api.create_order(symbol=target_symbol,
                                            amount=vol,
                                            type='market',
                                            side='sell',
                                            params=params
                                            )

        elif trade_type == 'sell':
            if position == 'short':
                print('SELL SHORT CLOSE', target_symbol)
                print()
                
                return self.api.create_order(symbol=target_symbol,
                                            amount=vol,
                                            type='market',
                                            side='buy',
                                            params=params
                                            )
            elif position == 'long':
                print('SELL LONG CLOSE', target_symbol)
                print()

                return self.api.create_order(symbol=target_symbol,
                                            amount=vol,
                                            type='market',
                                            side='sell',
                                            params=params
                                            )
                
    async def fetch_positions(self):
        positions = self.api.fetch_positions()
        indexed = self.api.index_by(positions, 'contracts')

        return positions, indexed

    async def check_positions(self, t_symbol=None):
        positions, indexed = self.fetch_positions()

        roe = []
        pnl = []

        for target_symbol in self.trader.get_target_symbols():
            if t_symbol is not None:
                if t_symbol != target_symbol:
                    continue

            chk = False
            for pos in positions:
                pos_symbol, entry_price, pos_side, n_contracts, _roe, _pnl \
                    = pos['symbol'], pos['entryPrice'], pos['side'], float(pos['contracts']), pos['percentage'], pos['unrealizedPnl']
            
                if n_contracts > 0 and target_symbol in pos_symbol:
                    roe.append(_roe)
                    pnl.append(_pnl)
                    chk = True
                    break

            if not chk:
                roe.append(0)
                pnl.append(0)
            

        return roe, pnl

    async def set_leverage(self, target_symbol, leverage=0, margin_mode='cross'):
        """
            ref: https://github.com/ccxt/ccxt/issues/11975
        """
        if leverage >= 1 and leverage <= 50:
            if margin_mode == 'cross':
                params = {"tdMode" : "cross", "mgnMode" : "cross", "posSide" : "net"}
            else:
                params = {"tdMode" : "isolated", "mgnMode" : "isolated", "posSide" : "net"}

            try:
                self.api.set_leverage(
                    leverage,
                    target_symbol,
                    params=params
                    )
            except:
                pass

    # ========== OKX API ===================
    """
        트레이딩 관련 함수들
    """

    async def trade(self, symbol, check_pos, trade_vol, cur_close):
        if not self.go_trade:
            return
            
        try:
            roe, pnl = await self.check_positions()
            cur_pos = []
            order_list = []
            if 'USDT.P' in symbol:
                target_coin = symbol.split('USDT.P')[0] + '/USDT:USDT'
            else:
                target_coin = symbol.split('/')[0] + '/USDT:USDT'

            print('============' * 5)
            print(datetime.now(timezone('Asia/Seoul')).strftime("%m/%d/%Y, %H:%M:%S"))
            print('HERE!', symbol, target_coin, check_pos)
            print()
            print('============' * 5)

            """
                Trend Check
            """
            for ti, target_symbol in enumerate(self.trader.get_target_symbols()):
                if target_coin not in target_symbol:
                    continue

                # -----------------------------
                # 기본 정보
                # -----------------------------
                cur_pos   = self.trader.get_info(target_symbol, key='position')
                new_buy_roe = self.trader.get_info(target_coin, key='new_buy_roe')
                use_short = self.trader.get_info(target_coin, key='use_short')

                _roe, _pnl = roe[ti], pnl[ti]
                cur_time = time.time()

                buy_time  = self.trader.get_info(target_coin, key='buy_time')
                sell_time = self.trader.get_info(target_coin, key='sell_time')

                def append_none():
                    order_list.append([target_coin, None, None, trade_vol, cur_time])

                # =============================
                # 1️⃣ 신규 진입
                # =============================
                if cur_pos is None:

                    if check_pos is None or cur_time == buy_time:
                        append_none()
                        continue

                    if check_pos == 'short' and not use_short:
                        append_none()
                        continue

                    buy_qty = self.trader.get_info(target_coin, key='min_vol') * trade_vol

                    order = self.market_order(
                        target_coin,
                        position=check_pos,
                        vol=buy_qty,
                        trade_type='buy'
                    )

                    self.trader.update_pos_list(target_coin, trade_vol)
                    order_list.append([target_coin, order, f'buy_{check_pos}', trade_vol, cur_time])
                    continue

                # =============================
                # 2️⃣ 추가 매수 (물타기)
                # =============================
                if (
                    cur_pos == check_pos and
                    cur_time != buy_time and
                    _roe < -new_buy_roe and
                    self.trader.get_info(target_coin, key='buy_cnt') + trade_vol
                        <= self.trader.get_info(target_coin, key='max_buy_cnt')
                ):

                    avg_price = self.trader.get_info(target_coin, key='avg_buy_price')

                    price_ok = (
                        (cur_pos == 'long'  and avg_price > cur_close) or
                        (cur_pos == 'short' and avg_price < cur_close)
                    )

                    if not price_ok:
                        append_none()
                        continue

                    # ---- ROE 기반 배수 계산 ----
                    def calc_max_mult(roe):
                        if roe < -50: return 30
                        if roe < -40: return 25
                        if roe < -30: return 20
                        if roe < -20: return 15
                        return 0

                    max_mult = calc_max_mult(_roe)

                    if max_mult > 0:
                        pos_list = self.trader.get_info(target_coin, key='position_list')
                        cur_buy_cnt = self.trader.get_info(target_coin, key='buy_cnt')
                        sum_pos = sum(pos_list)

                        for mult in range(max_mult, 0, -1):
                            _trade_vol = (mult / 10.0) * sum_pos
                            if cur_buy_cnt + _trade_vol <= self.trader.get_info(target_coin, key='max_buy_cnt'):
                                trade_vol = _trade_vol
                                break

                    buy_qty = self.trader.get_info(target_coin, key='min_vol') * trade_vol

                    order = self.market_order(
                        target_coin,
                        position=check_pos,
                        vol=buy_qty,
                        trade_type='buy'
                    )

                    self.trader.update_pos_list(target_coin, trade_vol)
                    order_list.append([target_coin, order, f'buy_{check_pos}', trade_vol, cur_time])
                    continue

                # =============================
                # 3️⃣ 반대 포지션 → 전량 청산
                # =============================
                if (
                    cur_pos != check_pos and
                    cur_time != sell_time and
                    self.trader.get_info(target_coin, key='buy_cnt') > 0
                ):

                    sell_cnt = self.trader.remove_pos_list(target_coin)
                    sell_qty = self.trader.get_info(target_coin, key='min_vol') * sell_cnt

                    order = self.market_order(
                        target_symbol,
                        position=cur_pos,
                        vol=sell_qty,
                        trade_type='sell'
                    )

                    order_list.append([target_symbol, order, f'sell_{cur_pos}', trade_vol, cur_time])
                    continue

                # =============================
                # 4️⃣ 아무것도 안 함
                # =============================
                append_none()

            
        except ccxt.InvalidOrder as e:
            print(datetime.now(timezone('Asia/Seoul')).strftime("%m/%d/%Y, %H:%M:%S"))
            print('InvalidOrder Error Raised!')
            print(traceback.format_exc())
            print('target_symbol : ', target_symbol, cur_pos, check_pos)
            del self.api
            print('deleted api')
            
            self.setup()
            print('New API generated')

        except ccxt.InsufficientFunds as e:
            print(datetime.now(timezone('Asia/Seoul')).strftime("%m/%d/%Y, %H:%M:%S"))
            print('Insufficient Fund Error Raised!')
            print(traceback.format_exc())
            print('target_symbol : ', target_symbol, cur_pos, check_pos)
            del self.api
            print('deleted api')
            
            self.setup()
            print('New API generated')
            

        try:
            msg_list = await self.post_trade(order_list)

            for idx, msg in enumerate(msg_list):
                self.post_message(msg)
                self.sleep(0.1)

            msg = await self.update_positions()
            # msg = asyncio.run(self.update_positions())
            self.post_message(msg)
            self.sleep(1)

        except (telegram.error.NetworkError, telegram.error.BadRequest, telegram.error.TimedOut):            
            print()
            print(datetime.now(timezone('Asia/Seoul')).strftime("%m/%d/%Y, %H:%M:%S"))
            print('Network 관련 에러 발생!\nBot 재시작!')
            print(traceback.format_exc())
            print()

        except Exception as e:
            print(datetime.now(timezone('Asia/Seoul')).strftime("%m/%d/%Y, %H:%M:%S"))
            print('Other Error Raised!')
            print(traceback.format_exc())
            
            del self.api
            print('deleted api')
            
            self.setup()
            msg = self.start_msg()
            self.post_message(msg)
            print('New API generated')

    async def post_trade(self, order_list):
        msg_list = []

        for target_symbol, order, trade_type, trade_vol, cur_time in order_list:
            if order is None or trade_type is None:
                msg_list.append(None)
                continue

            # -----------------------------
            # 체결 정보 조회
            # -----------------------------
            _order = self.fetch_order(target_symbol, order['id'])
            self.sleep(1)

            target_coin = self.symbol_parser(target_symbol)
            now_str = datetime.now(timezone('Asia/Seoul')).strftime("%m/%d/%Y, %H:%M:%S")

            # ==================================================
            # 🟢 BUY
            # ==================================================
            if trade_type.startswith('buy'):
                avg_price = float(_order['price'])

                cur_buy_cnt = self.trader.get_info(target_symbol, key='buy_cnt')
                self.trader.update(target_symbol, key='buy_cnt', value=cur_buy_cnt + trade_vol)
                self.trader.update(target_symbol, key='buy_time', value=cur_time)

                # 포지션 업데이트
                msg_list.append(await self.update_positions())
                self.set_balance()

                trade_chat = (
                    f"현재 시간 : {now_str}\n"
                    f"[매수 - {target_symbol.split('/')[0].upper()}] "
                    f"- 수량 : {self.trader.get_real_trade_vol(target_symbol, trade_vol):,.{self.trader.get_info(target_symbol, key='round_num')}f}\n"
                    f"현재 포지션 : {self.trader.get_info(target_symbol, key='position')} | "
                    f"Lev : x{self.trader.get_info(target_symbol, key='leverage'):.1f}\n"
                    f"평균 진입 가격 : {avg_price:.{self.trader.get_info(target_symbol, key='precision')}f}\n"
                    f"현재 보유 수량 : "
                    f"[{self.trader.get_belong_vol(target_symbol, False):,.{self.trader.get_info(target_symbol, key='round_num')}f}/"
                    f"{self.trader.get_buy_vol(target_symbol) * self.trader.get_info(target_symbol, key='max_buy_cnt'):,.{self.trader.get_info(target_symbol, key='round_num')}f}] "
                    f"[{self.trader.get_info(target_symbol, key='buy_cnt')}/{self.trader.get_info(target_symbol, key='max_buy_cnt')}]\n"
                )

                await self.trader.save_info()
                msg_list.append(trade_chat)
                continue

            # ==================================================
            # 🔴 SELL
            # ==================================================
            if trade_type.startswith('sell'):
                map_vol = self.trader.get_info(target_symbol, key='map_vol')
                round_num = self.trader.get_info(target_symbol, key='round_num')

                filled_vol = round(float(_order['amount']) / map_vol, round_num)
                filled_price = float(_order['price'])

                total_profit = self.trader.calc_profit(target_symbol, filled_price, filled_vol)
                ratio = abs(total_profit) / self.get_balance()

                cum_profit = self.trader.get_info(None, key='cum_profit')
                cum_pnl = self.trader.get_info(None, key='cum_pnl')

                # 승패 처리
                self.trader.update(None, key='tot_cnt', value=self.trader.get_info(None, key='tot_cnt') + 1)
                if total_profit < 0:
                    ratio = -ratio
                    profit_type = 'LOSS'
                else:
                    self.trader.update(None, key='win_cnt', value=self.trader.get_info(None, key='win_cnt') + 1)
                    profit_type = 'PROFIT'

                self.trader.update(target_symbol, key='sell_time', value=cur_time)
                self.trader.update(None, key='cum_profit', value=cum_profit + total_profit)
                self.trader.update(None, key='cum_pnl', value=cum_pnl + ratio)

                win_cnt = self.trader.get_info(None, key='win_cnt')
                tot_cnt = self.trader.get_info(None, key='tot_cnt')

                avg_price = self.trader.get_info(target_symbol, key='avg_buy_price')

                trade_chat = (
                    f"현재 시간 : {now_str}\n"
                    f"[매도 - {target_symbol.split('/')[0].upper()}] - [{profit_type}]\n"
                    f"현재 포지션 : {self.trader.get_info(target_symbol, key='position')} | "
                    f"Lev : x{self.trader.get_info(target_symbol, key='leverage'):.1f}\n"
                    f"평균 진입 가격 : {avg_price:.{self.trader.get_info(target_symbol, key='precision')}f}\n"
                    f"매도 수량 : {filled_vol:.{round_num}f}\n"
                    f"남은 수량 : {self.trader.get_belong_vol(target_symbol, False) - filled_vol:.{round_num}f}\n"
                    f"평균 매도 가격 : {filled_price:.{self.trader.get_info(target_symbol, key='precision')}f}\n"
                    f"현재 거래 이익 : {total_profit:,.2f} USDT [{ratio * 100:,.2f}%]\n"
                    f"누적 거래 이익 : {self.trader.get_info(None, key='cum_profit'):,.2f} USDT "
                    f"[{self.trader.get_info(None, key='cum_pnl') * 100:,.2f}%]\n"
                    f"승률 : [{win_cnt}/{tot_cnt}] "
                    f"- {(win_cnt / tot_cnt * 100 if tot_cnt > 0 else 0):.4f}%\n"
                )

                msg_list.append(await self.update_positions())
                self.set_balance()
                await self.trader.save_info()
                msg_list.append(trade_chat)
                continue

            msg_list.append(None)

        return msg_list

    async def update_positions(self):
        # bak_info = copy.deepcopy(self.get_balance())
        old_balance = self.trader.get_info(None, 'balance')

        positions = self.api.fetch_positions()
        indexed = self.api.index_by(positions, 'contracts')

        # print('indexed : ', indexed)
        # print()

        check=False
        msg = None

        self.set_balance()

        for target_symbol in self.trader.get_target_symbols():
            chk = True
            for pos in positions:
                pos_symbol, entry_price, pos_side, n_contracts = pos['symbol'], pos['entryPrice'], pos['side'], float(pos['contracts'])
                if n_contracts > 0 and target_symbol == pos_symbol:

                # if float(csz) > 0 and target_symbol in data['symbol']:
                    # print('Have Position : ', target_symbol, pos_symbol, n_contracts, self.get_info(target_symbol, key='amt'))

                    self.trader.update(target_symbol, key='avg_buy_price', value=float(entry_price))
                    
                    div_num = float(self.trader.get_info(symbol, key='map_vol'))
                    belong_vol = float(n_contracts) / div_num

                    self.trader.update(target_symbol, key='position', value=pos_side)

                    avg_buy_price = self.trader.get_info(target_symbol, key='avg_buy_price')
                    amt = n_contracts

                    if amt != self.trader.get_belong_vol(target_symbol):
                        print('Different Amount! ', target_symbol, amt, self.trader.get_belong_vol(target_symbol))
                        self.trader.update(target_symbol, key='amt', value=belong_vol)
                        check=True

                    if amt > 0:
                        cnt = self.trader.recal_pos_list(target_symbol, amt)
                        # print('Setup new buy cnt : ', cnt)
                        self.trader.update(target_symbol, key='buy_cnt', value=cnt)

                    chk = False
                    break
                # elif float(csz) > 0:
                #     print('Have Position2 : ', target_symbol, data['symbol'], float(csz), self.get_info(target_symbol, key='amt'))

            if chk:
                if self.trader.get_belong_vol(target_symbol) != 0:
                    check = True
                # print('HERE? ', target_symbol)
                # self.init_buy_vol()
                self.trader.update(target_symbol, key='position', value=None)
                self.trader.update(target_symbol, key='buy_cnt', value=0)
                self.trader.update(target_symbol, key='amt', value=0)
                self.trader.update(target_symbol, key='avg_buy_price', value=0)
                self.trader.update(target_symbol, key='position_list', value=[])
                

        if check or old_balance != self.get_balance():
            print(check, old_balance, self.get_balance())
            print()
            msg = await self.status_msg()

            self.set_balance()
            return msg

        return msg


    def set_balance(self):
        d = self.api.fetch_balance()
        total_balance = float(d['USDT']['free'])
        
        self.trader.update(None, 'balance', total_balance)

    def get_cur_balance(self):
        d = self.api.fetch_balance()
        d2 = d['info']['data'][0]['details'][0]

        total_sum = float(d2['cashBal'])
        cur_balance = float(d2['eq'])
        unpnl = float(d2['upl'])

        return total_sum, cur_balance, unpnl


    """
        기타 함수들    
    """
    def start_msg(self):
        text = "============================================\n"
        text += '현재 시간 : {}\n'.format(datetime.now(timezone('Asia/Seoul')).strftime("%m/%d/%Y, %H:%M:%S"),)
        text += "[자동 거래 시작] USER : [{}]\n".format(
            self.trader.get_info(None, 'user_name'),
            )

        total_sum, cur_balance, unpnl = self.get_cur_balance()

        text += "현재 계좌\nFree : [{:.2f}/{:.2f} USDT]\n".format(
            self.trader.get_info(None, 'balance'),
            cur_balance,
        )

        text += '현재 누적 거래 이익 : {:,.2f} USDT [{:,.2f}%]\n'.format(
                self.trader.get_info(None, key='cum_profit'), 
                self.trader.get_info(None, key='cum_pnl') * 100,
            )

        text += '현재 미실현 손익 : {:,.2f} USDT [{:,.2f}%]\n'.format(
                unpnl, (unpnl/total_sum) * 100,
            )

        text += '활성화 코인 리스트 - [{} 개]\n\n'.format(len(self.trader.get_target_symbols()))
        for ti, symbol in enumerate(self.trader.get_target_symbols()):
            text += '[{}] - [Lev : x{:.1f} | 포지션 : {}]\n'.format(
                symbol.split('/')[0].upper(),
                self.trader.get_info(symbol, key='leverage'),
                self.trader.get_info(symbol, key='position'),
            )
            text += "평균 진입 가격 : {:.{}f}\n".format(self.trader.get_info(symbol, key='avg_buy_price'), 
                                                    self.trader.get_info(symbol, key='precision'))
            text += '현재 보유 수량 : [{:,.{}f} / {:,.{}f}] [{}/{}]\n'.format(
                self.trader.get_belong_vol(symbol, False),
                self.trader.get_info(symbol, key='round_num'),
                self.trader.get_buy_vol(symbol) * self.trader.get_info(symbol, key='max_buy_cnt'),
                self.trader.get_info(symbol, key='round_num'),
                self.trader.get_info(symbol, key='buy_cnt'),
                self.trader.get_info(symbol, key='max_buy_cnt'),
                )
            if ti+1 < len(self.trader.get_target_symbols()):
                text += '\n'

        text += "============================================"

        return text

    async def status_msg(self):
        text = "============================================\n"
       
        if self.go_trade:
            text += '[거래 중]\n'
        else:
            text += '[거래 일시중지]\n'

        total_sum, cur_balance, unpnl = self.get_cur_balance()

        # text += "현재 거래 방법 : [{}]\n".format(self.get_trade_mode())
        text += "[현재 정보] USER : [{}]\n현재 시간 : {}\n".format(
            self.trader.get_info(None, 'user_name'),
            datetime.now(timezone('Asia/Seoul')).strftime("%m/%d/%Y, %H:%M:%S"),            
        )

        text += "현재 계좌\nFree : [{:.2f}/{:.2f} USDT]\n".format(
            self.trader.get_info(None, 'balance'),
            cur_balance,
        )
        
        text += '현재 누적 거래 이익 : {:,.2f} USDT [{:,.2f}%]\n'.format(
                self.trader.get_info(None, key='cum_profit'), 
                self.trader.get_info(None, key='cum_pnl') * 100,
            )

        text += '현재 미실현 손익 : {:,.2f} USDT [{:,.2f}%]\n'.format(
                unpnl, (unpnl/total_sum) * 100,
            )

        roe, pnl = await self.check_positions()
        
        text += '활성화 코인 리스트 - [{} 개]\n\n'.format(len(self.trader.get_target_symbols()))
        for ti, symbol in enumerate(self.trader.get_target_symbols()):
            text += '[{}] - [Lev : x{:.1f} | 포지션 : {}]\n'.format(
                symbol.split('/')[0].upper(),
                self.trader.get_info(symbol, key='leverage'),
                self.trader.get_info(symbol, key='position'),
            )

            text += '현재 보유 수량 : [{:,.{}f} / {:,.{}f}] [{}/{}]\n'.format(
                self.trader.get_belong_vol(symbol, False),
                self.trader.get_info(symbol, key='round_num'),
                self.trader.get_buy_vol(symbol) * self.trader.get_info(symbol, key='max_buy_cnt'),
                self.trader.get_info(symbol, key='round_num'),
                self.trader.get_info(symbol, key='buy_cnt'),
                self.trader.get_info(symbol, key='max_buy_cnt'),
                )

            avg_price = self.trader.get_info(symbol, key='avg_buy_price')
            text += "평균 진입 가격 : {:.{}f}\n".format(avg_price, self.trader.get_info(symbol, key='precision'))
            text += "현재 이익률 : [{:,.2f} USDT | {:,.2f}%]\n\n".format(
                pnl[ti],
                roe[ti],
            )

        return text

    def help_msg(self):
        text = "============================================\n"
        text += "[Set 명령어 모음]\n"
        text += "1) set [coin 이름] [leverage] : 해당 코인이름의 레버리지 정보 변화.\n"
        text += "2) set [coin 이름] [max buy cnt] : 해당 코인이름의 최대 매수 갯수 정보 변화.\n"
        text += "4) set [coin 이름] mv [숫자] : 최소 거래 단위 설정 (예 - BTC 기준 0.001 x 수량).\n"
        text += "5) set short [숫자] : 0이면 short 진입 X, 0외의 숫자면 short 진입.\n\n"

        text += "[정보 명령어 모음]\n"
        text += "1) show : 현재 거래 상태를 보여줌.\n"
        text += "2) help : 명령어 정보를 보여줌.\n\n"

        text += "[트레이딩 시작/일시정지]\n"
        text += "1) trade [0 or 아무숫자] : 0이면 거래 일시정지 | 그 외 숫자면 거래 활성화.\n"
        text += "============================================\n"

        return text

    async def on_startup(self, app):
        print("스타트업 콜백 실행됨!")
        await self.msgbot.send_message(chat_id=self.trader.get_telegram_id(), text="봇 시작됨!")

    # async def msg_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    #     text = update.message.text
    #     print("받은 메시지:", text)
    #     await update.message.reply_text(f"메시지 받음: {text}")

    async def post_message(self, msg):
        if msg is not None:
            await self.msgbot.send_message(chat_id=self.trader.get_telegram_id(), text=msg)

    def start(self):
        self.app.run_polling()

    async def msg_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_text = update.message.text
        tokens = user_text.split()
        print(tokens)

        # if tokens[0].lower() == 'set':
        #     for ti, target_symbol in enumerate(self.trader.get_target_symbols()):
        #         target_coin = self.symbol_parser(target_symbol)
                
        #         if tokens[1].lower() in target_coin.lower():
        #             if tokens[2].lower() == 'lev':
        #                 lev = float(tokens[3])
        #                 self.update(target_symbol, key='leverage', value=lev)
                    
        #             elif tokens[2].lower() == 'ratio':
        #                 ratio = float(tokens[3])
        #                 self.update(target_symbol, key='ratio', value=ratio)
                        
        #             elif tokens[2].lower() == 'cnt':
        #                 cnt = float(tokens[3])
        #                 self.update(target_symbol, key='max_buy_cnt', value=cnt)

        #             elif tokens[2].lower() == 'mv':
        #                 cnt = float(tokens[3])
        #                 min_vol = cnt * 0.1
        #                 self.update(target_symbol, key='min_vol', value=min_vol)

        #             elif tokens[2].lower() == 'add':
        #                 ratio = float(tokens[3])
        #                 self.update(target_symbol, key='new_buy_roe', value=ratio)

        #                 # if self.target_info[target_coin]['trade_mode'] == 'rsi':

        #     if tokens[1].lower() == 'type':
        #         self.set_trade_type(int(tokens[2]))

        #     elif tokens[1].lower() == 'mode':
        #         if tokens[2].lower() in ['all', 'cond', 'rand', 'rsi', 'danta']:
        #             self.set_trade_mode(tokens[2])

        #     elif tokens[1].lower() == 'short':
        #         tgt = float(tokens[2])
        #         if tgt != 0:
        #             flag = True
        #         else:
        #             flag = False
                
        #         self.set_use_short(flag)

        #     # self.init_buy_vol()
        #     # msg = self.update_positions()
        #     msg = asyncio.run(self.update_positions())
        #     self.post_message(msg)

        #     msg = self.status_msg()
        #     self.post_message(msg)

        # elif tokens[0].lower() == 'show':
        #     msg = self.status_msg()
        #     self.post_message(msg)

        # elif tokens[0].lower() == 'help':
        #     msg = self.help_msg()
        #     self.post_message(msg)

        # elif tokens[0].lower() == 'trade':
        #     cnt = int(tokens[1])

        #     self.set_trade(cnt)
        #     # msg = self.update_positions()
        #     msg = asyncio.run(self.update_positions())
        #     self.post_message(msg)
            
        #     msg = self.status_msg()
        #     self.post_message(msg)

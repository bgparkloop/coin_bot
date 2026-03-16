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
import telegram
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
        self.msgbot = None
        self.setup()

    def setup_api(self):
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
        if self.trader.get_environment() == 'demo' and hasattr(self.api, 'set_sandbox_mode'):
            self.api.set_sandbox_mode(True)

    def setup(self):
        self.trader = UserData()
        self.setup_api()
        self.go_trade = True
        self.timeframe = '15m'
        self.req_data_cnt = 300

    def set_msgbot(self, msg_bot):
        # pip install "python-telegram-bot==20.3"

        self.msgbot = msg_bot

    async def ensure_exchange_mode(self):
        desired_mode = self.trader.get_position_mode()
        if desired_mode != 'hedge':
            return

        current_mode = self.get_exchange_position_mode()
        if current_mode == 'long_short_mode':
            return

        try:
            if hasattr(self.api, 'set_position_mode'):
                self.api.set_position_mode(True)
            elif hasattr(self.api, 'setPositionMode'):
                self.api.setPositionMode(True)
            elif hasattr(self.api, 'private_post_account_set_position_mode'):
                self.api.private_post_account_set_position_mode({'posMode': 'long_short_mode'})
            elif hasattr(self.api, 'privatePostAccountSetPositionMode'):
                self.api.privatePostAccountSetPositionMode({'posMode': 'long_short_mode'})
            else:
                raise RuntimeError('OKX position mode API is not available in ccxt client')
        except Exception as exc:
            raise RuntimeError(f'Failed to enable hedge mode on OKX: {exc}') from exc

        current_mode = self.get_exchange_position_mode()
        if current_mode != 'long_short_mode':
            raise RuntimeError(f'OKX hedge mode verification failed: {current_mode}')

    def get_exchange_position_mode(self):
        try:
            if hasattr(self.api, 'fetch_position_mode'):
                mode = self.api.fetch_position_mode()
                if isinstance(mode, dict):
                    hedged = mode.get('hedged')
                    if hedged is True:
                        return 'long_short_mode'
                    if hedged is False:
                        return 'net_mode'
            if hasattr(self.api, 'fetchPositionMode'):
                mode = self.api.fetchPositionMode()
                if isinstance(mode, dict):
                    hedged = mode.get('hedged')
                    if hedged is True:
                        return 'long_short_mode'
                    if hedged is False:
                        return 'net_mode'
            if hasattr(self.api, 'private_get_account_config'):
                resp = self.api.private_get_account_config()
            elif hasattr(self.api, 'privateGetAccountConfig'):
                resp = self.api.privateGetAccountConfig()
            else:
                return None
            data = resp.get('data', [])
            if data:
                return data[0].get('posMode')
        except Exception:
            return None
        return None

    def get_position_side(self, pos):
        side = pos.get('side')
        if side in ('long', 'short'):
            return side
        info = pos.get('info', {})
        pos_side = info.get('posSide')
        if pos_side in ('long', 'short', 'net'):
            return pos_side
        return side

    def build_order_entry(self, target_symbol, order, trade_type, trade_vol, cur_time, side=None, action=None):
        return {
            'target_symbol': target_symbol,
            'order': order,
            'trade_type': trade_type,
            'trade_vol': trade_vol,
            'cur_time': cur_time,
            'side': side,
            'action': action,
        }

    def side_label(self, side):
        return '롱' if side == 'long' else '숏'

    async def market_order_hedge(self, target_symbol, position_side, action, vol=0, margin_mode='cross'):
        if margin_mode == 'cross':
            params = {"tdMode": "cross", "mgnMode": "cross", "posSide": position_side}
        else:
            params = {"tdMode": "isolated", "mgnMode": "isolated", "posSide": position_side}

        if action == 'open':
            side = 'buy' if position_side == 'long' else 'sell'
        elif action == 'close':
            side = 'sell' if position_side == 'long' else 'buy'
        else:
            raise ValueError(f'Unknown hedge action: {action}')

        print(f'HEDGE {action.upper()} {position_side.upper()}', target_symbol)
        print()

        return self.api.create_order(
            symbol=target_symbol,
            amount=vol,
            type='market',
            side=side,
            params=params,
        )

    def get_side_metrics(self, positions, target_symbol):
        result = {
            'long': {'roe': 0, 'pnl': 0},
            'short': {'roe': 0, 'pnl': 0},
        }

        for pos in positions:
            pos_symbol = pos.get('symbol')
            if pos_symbol != target_symbol:
                continue
            side = self.get_position_side(pos)
            if side not in result:
                continue
            contracts = float(pos.get('contracts') or 0)
            if contracts <= 0:
                continue
            result[side]['roe'] = pos.get('percentage') or 0
            result[side]['pnl'] = pos.get('unrealizedPnl') or 0

        return result


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
        positions, indexed = await self.fetch_positions()

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

    async def check_positions_hedge(self, t_symbol=None):
        positions, _ = await self.fetch_positions()
        metrics = {}

        for target_symbol in self.trader.get_target_symbols():
            if t_symbol is not None and t_symbol != target_symbol:
                continue
            metrics[target_symbol] = self.get_side_metrics(positions, target_symbol)

        return metrics

    async def set_leverage(self, target_symbol, leverage=0, margin_mode='cross'):
        """
            ref: https://github.com/ccxt/ccxt/issues/11975
        """
        if leverage >= 1 and leverage <= 50:
            pos_sides = ['net']
            if self.trader.is_hedge_mode():
                pos_sides = ['long', 'short']

            for pos_side in pos_sides:
                if margin_mode == 'cross':
                    params = {"tdMode" : "cross", "mgnMode" : "cross", "posSide" : pos_side}
                else:
                    params = {"tdMode" : "isolated", "mgnMode" : "isolated", "posSide" : pos_side}

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
    def sleep(self, sleep_time):
        time.sleep(sleep_time)

    async def trade(self, symbol, check_pos, trade_vol, cur_close):
        if self.trader.is_hedge_mode():
            return await self.trade_hedge(symbol, check_pos, trade_vol, cur_close)

        # if not self.go_trade:
        #     return
            
        try:
            roe, pnl = await self.check_positions()
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

                if not self.trader.get_info(target_coin, key='go_trade'):
                    continue

                # -----------------------------
                # 기본 정보
                # -----------------------------
                cur_pos   = self.trader.get_info(target_coin, key='position')
                new_buy_roe = self.trader.get_info(target_coin, key='new_buy_roe')
                use_short = self.trader.get_info(target_coin, key='use_short')

                _roe, _pnl = roe[ti], pnl[ti]
                cur_time = time.time()
                cur_amt = self.trader.get_belong_vol(target_coin, False)

                buy_time  = self.trader.get_info(target_coin, key='buy_time')
                sell_time = self.trader.get_info(target_coin, key='sell_time')

                def append_none():
                    order_list.append([target_coin, None, None, trade_vol, cur_time])

                print('ti: ', ti, target_symbol, cur_pos, _roe, _pnl, check_pos)

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

                    print('HHHERE1')
                    order = await self.market_order(
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
                elif (
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

                    print('HHHERE2')
                    order = await self.market_order(
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
                elif (
                    cur_pos != check_pos and
                    cur_time != sell_time and
                    cur_amt > 0
                ):

                    sell_cnt = self.trader.remove_pos_list(target_coin)
                    sell_qty = self.trader.get_info(target_coin, key='min_vol') * sell_cnt

                    order = await self.market_order(
                        target_symbol,
                        position=cur_pos,
                        vol=sell_qty,
                        trade_type='sell'
                    )

                    print('HHHERE3')
                    order_list.append([target_symbol, order, f'sell_{cur_pos}', trade_vol, cur_time])
                    continue

                else:
                    # =============================
                    # 4️⃣ 아무것도 안 함
                    # =============================
                    print('HHHERE4')
                    append_none()

            
        except ccxt.InvalidOrder as e:
            print(datetime.now(timezone('Asia/Seoul')).strftime("%m/%d/%Y, %H:%M:%S"))
            print('InvalidOrder Error Raised!')
            print(traceback.format_exc())
            print('target_symbol : ', target_symbol, cur_pos, check_pos)
            del self.api
            print('deleted api')
            
            self.setup_api()
            print('New API generated')

        except ccxt.InsufficientFunds as e:
            print(datetime.now(timezone('Asia/Seoul')).strftime("%m/%d/%Y, %H:%M:%S"))
            print('Insufficient Fund Error Raised!')
            print(traceback.format_exc())
            print('target_symbol : ', target_symbol, cur_pos, check_pos)
            del self.api
            print('deleted api')
            
            self.setup_api()
            print('New API generated')
            

        print('Order List')
        for ii, _order in enumerate(order_list):
            print(ii+1, _order)
            print()
        print()

        try:
            msg_list = await self.post_trade(order_list)

            for idx, msg in enumerate(msg_list):
                await self.post_message(msg)
                self.sleep(0.1)

            msg = await self.update_positions()
            # msg = asyncio.run(self.update_positions())
            await self.post_message(msg)
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
            
            self.setup_api()
            msg = self.start_msg()
            await self.post_message(msg)
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
            _order = await self.fetch_order(target_symbol, order['id'])
            self.sleep(1)

            # target_coin = self.symbol_parser(target_symbol)
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
                ratio = abs(total_profit) / await self.get_balance()

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
        if self.trader.is_hedge_mode():
            return await self.update_positions_hedge()

        old_balance = self.trader.get_info(None, 'balance')

        positions = self.api.fetch_positions()
        indexed = self.api.index_by(positions, 'contracts')

        check=False
        msg = None

        self.set_balance()

        for target_symbol in self.trader.get_target_symbols():
            chk = True
            for pos in positions:
                pos_symbol, entry_price, pos_side, n_contracts = pos['symbol'], pos['entryPrice'], pos['side'], float(pos['contracts'])
                if n_contracts > 0 and target_symbol == pos_symbol:
                    self.trader.update(target_symbol, key='avg_buy_price', value=float(entry_price))
                    
                    div_num = float(self.trader.get_info(target_symbol, key='map_vol'))
                    belong_vol = float(n_contracts) / div_num

                    self.trader.update(target_symbol, key='position', value=pos_side)

                    avg_buy_price = self.trader.get_info(target_symbol, key='avg_buy_price')
                    amt = n_contracts

                    if amt != self.trader.get_belong_vol(target_symbol):
                        print('Different Amount! ', target_symbol, amt, self.trader.get_belong_vol(target_symbol))
                        self.trader.update(target_symbol, key='amt', value=belong_vol)
                        check=True

                    if belong_vol > 0:
                        cnt = self.trader.recal_pos_list(target_symbol, belong_vol)
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
            if check:
                print(check, old_balance, await self.get_balance())
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
    async def start_msg(self):
        if self.trader.is_hedge_mode():
            return await self.start_msg_hedge()

        text = "============================================\n"
        text += '현재 시간: {}\n'.format(datetime.now(timezone('Asia/Seoul')).strftime("%m/%d/%Y, %H:%M:%S"),)
        text += "[자동 거래 시작] USER : [{}]\n".format(
            self.trader.get_info(None, 'user_name'),
            )

        total_sum, cur_balance, unpnl = self.get_cur_balance()

        text += "현재 계좌\nFree: [{:.2f}/{:.2f} USDT]\n".format(
            self.trader.get_info(None, 'balance'),
            cur_balance,
        )

        text += '현재 누적 거래 이익: {:,.2f} USDT [{:,.2f}%]\n'.format(
                self.trader.get_info(None, key='cum_profit'), 
                self.trader.get_info(None, key='cum_pnl') * 100,
            )

        text += '현재 미실현 손익: {:,.2f} USDT [{:,.2f}%]\n'.format(
                unpnl, (unpnl/total_sum) * 100,
            )

        n_act = 0
        for symbol in self.trader.get_target_symbols():
            if self.trader.get_info(symbol, key='go_trade'):
                n_act += 1

        text += '활성화 코인 리스트 - [{}/{} 개]\n\n'.format(n_act, len(self.trader.get_target_symbols()))
        for ti, symbol in enumerate(self.trader.get_target_symbols()):
            if self.trader.get_info(symbol, key='go_trade'):
                text += '[{}] - [Lev: x{:.1f} | 포지션: {} | Use Short: {}]\n'.format(
                    symbol.split('/')[0].upper(),
                    self.trader.get_info(symbol, key='leverage'),
                    self.trader.get_info(symbol, key='position'),
                    self.trader.get_info(symbol, key='use_short'),
                )
                text += "평균 진입 가격: {:.{}f}\n".format(self.trader.get_info(symbol, key='avg_buy_price'), 
                                                        self.trader.get_info(symbol, key='precision'))
                text += '현재 보유 수량: [{:,.{}f} / {:,.{}f}] [{}/{}]\n'.format(
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
        if self.trader.is_hedge_mode():
            return await self.status_msg_hedge()

        text = "============================================\n"
       
        if self.go_trade:
            text += '[거래 중]\n'
        else:
            text += '[거래 일시중지]\n'

        total_sum, cur_balance, unpnl = self.get_cur_balance()

        # text += "현재 거래 방법 : [{}]\n".format(self.get_trade_mode())
        text += "[현재 정보] USER: [{}]\n현재 시간 : {}\n".format(
            self.trader.get_info(None, 'user_name'),
            datetime.now(timezone('Asia/Seoul')).strftime("%m/%d/%Y, %H:%M:%S"),            
        )

        text += "현재 계좌\nFree: [{:.2f}/{:.2f} USDT]\n".format(
            self.trader.get_info(None, 'balance'),
            cur_balance,
        )
        
        text += '현재 누적 거래 이익: {:,.2f} USDT [{:,.2f}%]\n'.format(
                self.trader.get_info(None, key='cum_profit'), 
                self.trader.get_info(None, key='cum_pnl') * 100,
            )

        text += '현재 미실현 손익: {:,.2f} USDT [{:,.2f}%]\n'.format(
                unpnl, (unpnl/total_sum) * 100,
            )

        roe, pnl = await self.check_positions()
        
        n_act = 0
        for symbol in self.trader.get_target_symbols():
            if self.trader.get_info(symbol, key='go_trade'):
                n_act += 1

        text += '활성화 코인 리스트 - [{}/{} 개]\n\n'.format(n_act, len(self.trader.get_target_symbols()))
        for ti, symbol in enumerate(self.trader.get_target_symbols()):
            if self.trader.get_info(symbol, key='go_trade'):
                text += '[{}] - [Lev: x{:.1f} | 포지션: {} | Use Short: {}]\n'.format(
                    symbol.split('/')[0].upper(),
                    self.trader.get_info(symbol, key='leverage'),
                    self.trader.get_info(symbol, key='position'),
                    self.trader.get_info(symbol, key='use_short'),
                )

                text += '현재 보유 수량: [{:,.{}f} / {:,.{}f}] [{}/{}]\n'.format(
                    self.trader.get_belong_vol(symbol, False),
                    self.trader.get_info(symbol, key='round_num'),
                    self.trader.get_buy_vol(symbol) * self.trader.get_info(symbol, key='max_buy_cnt'),
                    self.trader.get_info(symbol, key='round_num'),
                    self.trader.get_info(symbol, key='buy_cnt'),
                    self.trader.get_info(symbol, key='max_buy_cnt'),
                    )

                avg_price = self.trader.get_info(symbol, key='avg_buy_price')
                text += "평균 진입 가격: {:.{}f}\n".format(avg_price, self.trader.get_info(symbol, key='precision'))
                text += "현재 이익률: [{:,.2f} USDT | {:,.2f}%]\n\n".format(
                    pnl[ti],
                    roe[ti],
                )

        return text

    def normalize_target_symbol(self, symbol):
        if 'USDT.P' in symbol:
            return symbol.split('USDT.P')[0] + '/USDT:USDT'
        return symbol.split('/')[0] + '/USDT:USDT'

    async def trade_hedge(self, symbol, check_pos, trade_vol, cur_close):
        target_coin = self.normalize_target_symbol(symbol)
        cur_time = time.time()
        order_list = []

        try:
            metrics = await self.check_positions_hedge(target_coin)

            for target_symbol in self.trader.get_target_symbols():
                if target_coin not in target_symbol:
                    continue

                if not self.trader.get_info(target_coin, key='go_trade'):
                    continue

                side = check_pos
                opp_side = 'short' if side == 'long' else 'long'
                side_amt = self.trader.get_side_belong_vol(target_coin, side, False)
                opp_amt = self.trader.get_side_belong_vol(target_coin, opp_side, False)
                side_buy_cnt = self.trader.get_side_info(target_coin, side, 'buy_cnt')
                new_buy_roe = self.trader.get_info(target_coin, key='new_buy_roe')
                max_buy_cnt = self.trader.get_info(target_coin, key='max_buy_cnt')
                min_vol = self.trader.get_info(target_coin, key='min_vol')
                buy_time = self.trader.get_side_info(target_coin, side, 'buy_time')
                opp_sell_time = self.trader.get_side_info(target_coin, opp_side, 'sell_time')
                side_metrics = metrics.get(target_coin, {}).get(side, {'roe': 0, 'pnl': 0})
                side_roe = float(side_metrics.get('roe') or 0)
                side_avg = self.trader.get_side_info(target_coin, side, 'avg_buy_price')

                if opp_amt > 0 and cur_time != opp_sell_time:
                    max_close_contracts = opp_amt * self.trader.get_info(target_coin, key='map_vol')
                    requested_contracts = min_vol * trade_vol
                    close_contracts = min(requested_contracts, max_close_contracts)
                    executed_trade_vol = round(close_contracts / min_vol, self.trader.get_info(target_coin, key='round_num'))
                    if close_contracts > 0:
                        order = await self.market_order_hedge(
                            target_coin,
                            opp_side,
                            'close',
                            vol=close_contracts,
                        )
                        order_list.append(
                            self.build_order_entry(
                                target_coin,
                                order,
                                f'close_{opp_side}',
                                executed_trade_vol,
                                cur_time,
                                side=opp_side,
                                action='close',
                            )
                        )
                    else:
                        order_list.append(self.build_order_entry(target_coin, None, None, trade_vol, cur_time))
                    continue

                if side_amt <= 0:
                    order = await self.market_order_hedge(
                        target_coin,
                        side,
                        'open',
                        vol=min_vol * trade_vol,
                    )
                    self.trader.update_side_pos_list(target_coin, side, trade_vol)
                    order_list.append(
                        self.build_order_entry(
                            target_coin,
                            order,
                            f'open_{side}',
                            trade_vol,
                            cur_time,
                            side=side,
                            action='open',
                        )
                    )
                    continue

                price_ok = (
                    (side == 'long' and side_avg > cur_close) or
                    (side == 'short' and side_avg < cur_close)
                )
                can_add = (
                    cur_time != buy_time and
                    side_roe < -new_buy_roe and
                    side_buy_cnt + trade_vol <= max_buy_cnt and
                    price_ok
                )

                if can_add:
                    def calc_max_mult(roe):
                        if roe < -50:
                            return 30
                        if roe < -40:
                            return 25
                        if roe < -30:
                            return 20
                        if roe < -20:
                            return 15
                        return 0

                    max_mult = calc_max_mult(side_roe)
                    if max_mult > 0:
                        pos_list = self.trader.get_side_info(target_coin, side, 'position_list')
                        sum_pos = sum(pos_list)
                        for mult in range(max_mult, 0, -1):
                            adjusted_trade_vol = (mult / 10.0) * sum_pos
                            if side_buy_cnt + adjusted_trade_vol <= max_buy_cnt:
                                trade_vol = adjusted_trade_vol
                                break

                    order = await self.market_order_hedge(
                        target_coin,
                        side,
                        'open',
                        vol=min_vol * trade_vol,
                    )
                    self.trader.update_side_pos_list(target_coin, side, trade_vol)
                    order_list.append(
                        self.build_order_entry(
                            target_coin,
                            order,
                            f'open_{side}',
                            trade_vol,
                            cur_time,
                            side=side,
                            action='open',
                        )
                    )
                    continue

                order_list.append(self.build_order_entry(target_coin, None, None, trade_vol, cur_time))

        except ccxt.InvalidOrder:
            print(datetime.now(timezone('Asia/Seoul')).strftime("%m/%d/%Y, %H:%M:%S"))
            print('InvalidOrder Error Raised!')
            print(traceback.format_exc())
            del self.api
            self.setup_api()
            return
        except ccxt.InsufficientFunds:
            print(datetime.now(timezone('Asia/Seoul')).strftime("%m/%d/%Y, %H:%M:%S"))
            print('Insufficient Fund Error Raised!')
            print(traceback.format_exc())
            del self.api
            self.setup_api()
            return

        print('Hedge Order List')
        for ii, item in enumerate(order_list):
            print(ii + 1, item)
            print()

        try:
            msg_list = await self.post_trade_hedge(order_list)

            for msg in msg_list:
                await self.post_message(msg)
                self.sleep(0.1)

            msg = await self.update_positions_hedge()
            await self.post_message(msg)
            self.sleep(1)
        except (telegram.error.NetworkError, telegram.error.BadRequest, telegram.error.TimedOut):
            print(datetime.now(timezone('Asia/Seoul')).strftime("%m/%d/%Y, %H:%M:%S"))
            print('Network 관련 에러 발생!\nBot 재시작!')
            print(traceback.format_exc())
        except Exception:
            print(datetime.now(timezone('Asia/Seoul')).strftime("%m/%d/%Y, %H:%M:%S"))
            print('Other Error Raised!')
            print(traceback.format_exc())
            del self.api
            self.setup_api()

    async def post_trade_hedge(self, order_list):
        msg_list = []

        for entry in order_list:
            order = entry['order']
            if order is None or entry['trade_type'] is None:
                msg_list.append(None)
                continue

            target_symbol = entry['target_symbol']
            side = entry['side']
            action = entry['action']
            trade_vol = entry['trade_vol']
            cur_time = entry['cur_time']
            order_info = await self.fetch_order(target_symbol, order['id'])
            self.sleep(1)

            now_str = datetime.now(timezone('Asia/Seoul')).strftime("%m/%d/%Y, %H:%M:%S")
            round_num = self.trader.get_info(target_symbol, key='round_num')
            filled_vol = round(float(order_info['amount']) / self.trader.get_info(target_symbol, key='map_vol'), round_num)
            filled_price = float(order_info['price'])

            if action == 'open':
                cur_buy_cnt = self.trader.get_side_info(target_symbol, side, 'buy_cnt')
                self.trader.update_side_info(target_symbol, side, 'buy_cnt', cur_buy_cnt + trade_vol)
                self.trader.update_side_info(target_symbol, side, 'buy_time', cur_time)
                await self.update_positions_hedge()
                self.set_balance()
                trade_chat = (
                    f"현재 시간 : {now_str}\n"
                    f"[{self.side_label(side)} 진입 - {target_symbol.split('/')[0].upper()}] "
                    f"- 수량 : {filled_vol:.{round_num}f}\n"
                    f"평균 진입 가격 : {filled_price:.{self.trader.get_info(target_symbol, key='precision')}f}\n"
                    f"현재 보유 수량 : "
                    f"[{self.trader.get_side_belong_vol(target_symbol, side, False):,.{round_num}f}/"
                    f"{self.trader.get_buy_vol(target_symbol) * self.trader.get_info(target_symbol, key='max_buy_cnt'):,.{round_num}f}] "
                    f"[{self.trader.get_side_info(target_symbol, side, 'buy_cnt')}/{self.trader.get_info(target_symbol, key='max_buy_cnt')}]\n"
                )
                await self.trader.save_info()
                msg_list.append(trade_chat)
                continue

            total_profit = self.trader.calc_side_profit(target_symbol, side, filled_price, filled_vol)
            ratio = abs(total_profit) / await self.get_balance()
            cum_profit = self.trader.get_info(None, key='cum_profit')
            cum_pnl = self.trader.get_info(None, key='cum_pnl')
            avg_entry_price = self.trader.get_side_info(target_symbol, side, 'avg_buy_price')

            self.trader.update(None, key='tot_cnt', value=self.trader.get_info(None, key='tot_cnt') + 1)
            if total_profit < 0:
                ratio = -ratio
                profit_type = 'LOSS'
            else:
                self.trader.update(None, key='win_cnt', value=self.trader.get_info(None, key='win_cnt') + 1)
                profit_type = 'PROFIT'

            self.trader.update_side_info(target_symbol, side, 'sell_time', cur_time)
            self.trader.update(None, key='cum_profit', value=cum_profit + total_profit)
            self.trader.update(None, key='cum_pnl', value=cum_pnl + ratio)
            await self.update_positions_hedge()
            self.set_balance()

            trade_chat = (
                f"현재 시간 : {now_str}\n"
                f"[{self.side_label(side)} 청산 - {target_symbol.split('/')[0].upper()}] - [{profit_type}]\n"
                f"평균 진입 가격 : {avg_entry_price:.{self.trader.get_info(target_symbol, key='precision')}f}\n"
                f"청산 수량 : {filled_vol:.{round_num}f}\n"
                f"남은 수량 : {self.trader.get_side_belong_vol(target_symbol, side, False):.{round_num}f}\n"
                f"평균 청산 가격 : {filled_price:.{self.trader.get_info(target_symbol, key='precision')}f}\n"
                f"현재 거래 이익 : {total_profit:,.2f} USDT [{ratio * 100:,.2f}%]\n"
                f"누적 거래 이익 : {self.trader.get_info(None, key='cum_profit'):,.2f} USDT "
                f"[{self.trader.get_info(None, key='cum_pnl') * 100:,.2f}%]\n"
            )
            await self.trader.save_info()
            msg_list.append(trade_chat)

        return msg_list

    async def update_positions_hedge(self):
        old_balance = self.trader.get_info(None, 'balance')
        positions = self.api.fetch_positions()
        check = False
        msg = None

        self.set_balance()

        for target_symbol in self.trader.get_target_symbols():
            found = {'long': False, 'short': False}
            div_num = float(self.trader.get_info(target_symbol, key='map_vol'))

            for pos in positions:
                pos_symbol = pos.get('symbol')
                if pos_symbol != target_symbol:
                    continue

                side = self.get_position_side(pos)
                if side not in ('long', 'short'):
                    continue

                n_contracts = float(pos.get('contracts') or 0)
                if n_contracts <= 0:
                    continue

                found[side] = True
                entry_price = float(pos.get('entryPrice') or pos.get('entry_price') or 0)
                belong_vol = n_contracts / div_num
                prev_amt = self.trader.get_side_belong_vol(target_symbol, side, False)

                self.trader.update_side_info(target_symbol, side, 'avg_buy_price', entry_price)
                self.trader.update_side_info(target_symbol, side, 'amt', belong_vol)

                if abs(prev_amt - belong_vol) > 1e-12:
                    check = True

                cnt = self.trader.recal_side_pos_list(target_symbol, side, belong_vol)
                self.trader.update_side_info(target_symbol, side, 'buy_cnt', cnt)

            for side in ('long', 'short'):
                if found[side]:
                    continue
                if self.trader.get_side_belong_vol(target_symbol, side, False) != 0:
                    check = True
                self.trader.reset_side_info(target_symbol, side)

            long_amt = self.trader.get_side_belong_vol(target_symbol, 'long', False)
            short_amt = self.trader.get_side_belong_vol(target_symbol, 'short', False)
            if long_amt > 0 and short_amt > 0:
                summary_pos = 'hedge'
            elif long_amt > 0:
                summary_pos = 'long'
            elif short_amt > 0:
                summary_pos = 'short'
            else:
                summary_pos = None

            self.trader.update(target_symbol, key='position', value=summary_pos)
            self.trader.update(target_symbol, key='amt', value=long_amt + short_amt)
            self.trader.update(target_symbol, key='buy_cnt', value=(
                self.trader.get_side_info(target_symbol, 'long', 'buy_cnt') +
                self.trader.get_side_info(target_symbol, 'short', 'buy_cnt')
            ))

        if check or old_balance != await self.get_balance():
            if check:
                msg = await self.status_msg_hedge()
            self.set_balance()
            return msg

        return msg

    async def start_msg_hedge(self):
        total_sum, cur_balance, unpnl = self.get_cur_balance()
        text = "============================================\n"
        text += '현재 시간: {}\n'.format(datetime.now(timezone('Asia/Seoul')).strftime("%m/%d/%Y, %H:%M:%S"),)
        text += "[자동 거래 시작] USER : [{}]\n".format(self.trader.get_info(None, 'user_name'))
        text += "현재 모드 : [hedge]\n"
        text += "현재 계좌\nFree: [{:.2f}/{:.2f} USDT]\n".format(
            self.trader.get_info(None, 'balance'),
            cur_balance,
        )
        text += '현재 누적 거래 이익: {:,.2f} USDT [{:,.2f}%]\n'.format(
            self.trader.get_info(None, key='cum_profit'),
            self.trader.get_info(None, key='cum_pnl') * 100,
        )
        text += '현재 미실현 손익: {:,.2f} USDT [{:,.2f}%]\n'.format(
            unpnl, (unpnl / total_sum) * 100,
        )
        text += await self.render_hedge_positions()
        text += "============================================"
        return text

    async def status_msg_hedge(self):
        total_sum, cur_balance, unpnl = self.get_cur_balance()
        metrics = await self.check_positions_hedge()
        text = "============================================\n"
        text += '[거래 중]\n' if self.go_trade else '[거래 일시중지]\n'
        text += "[현재 정보] USER: [{}]\n현재 시간 : {}\n".format(
            self.trader.get_info(None, 'user_name'),
            datetime.now(timezone('Asia/Seoul')).strftime("%m/%d/%Y, %H:%M:%S"),
        )
        text += "현재 모드 : [hedge]\n"
        text += "현재 계좌\nFree: [{:.2f}/{:.2f} USDT]\n".format(
            self.trader.get_info(None, 'balance'),
            cur_balance,
        )
        text += '현재 누적 거래 이익: {:,.2f} USDT [{:,.2f}%]\n'.format(
            self.trader.get_info(None, key='cum_profit'),
            self.trader.get_info(None, key='cum_pnl') * 100,
        )
        text += '현재 미실현 손익: {:,.2f} USDT [{:,.2f}%]\n'.format(
            unpnl, (unpnl / total_sum) * 100,
        )
        text += await self.render_hedge_positions(metrics)
        return text

    async def render_hedge_positions(self, metrics=None):
        if metrics is None:
            metrics = await self.check_positions_hedge()

        n_act = 0
        for symbol in self.trader.get_target_symbols():
            if self.trader.get_info(symbol, key='go_trade'):
                n_act += 1

        text = '활성화 코인 리스트 - [{}/{} 개]\n\n'.format(n_act, len(self.trader.get_target_symbols()))
        for ti, symbol in enumerate(self.trader.get_target_symbols()):
            if not self.trader.get_info(symbol, key='go_trade'):
                continue

            text += '[{}] - [Lev: x{:.1f}]\n'.format(
                symbol.split('/')[0].upper(),
                self.trader.get_info(symbol, key='leverage'),
            )

            for side in ('long', 'short'):
                side_metrics = metrics.get(symbol, {}).get(side, {'roe': 0, 'pnl': 0})
                text += '{} : 수량 [{:,.{}f} / {:,.{}f}] [{}/{}]\n'.format(
                    self.side_label(side),
                    self.trader.get_side_belong_vol(symbol, side, False),
                    self.trader.get_info(symbol, key='round_num'),
                    self.trader.get_buy_vol(symbol) * self.trader.get_info(symbol, key='max_buy_cnt'),
                    self.trader.get_info(symbol, key='round_num'),
                    self.trader.get_side_info(symbol, side, 'buy_cnt'),
                    self.trader.get_info(symbol, key='max_buy_cnt'),
                )
                text += '{} 평균 진입 가격: {:.{}f}\n'.format(
                    self.side_label(side),
                    self.trader.get_side_info(symbol, side, 'avg_buy_price'),
                    self.trader.get_info(symbol, key='precision'),
                )
                text += '{} 현재 이익률: [{:,.2f} USDT | {:,.2f}%]\n'.format(
                    self.side_label(side),
                    float(side_metrics.get('pnl') or 0),
                    float(side_metrics.get('roe') or 0),
                )
            if ti + 1 < len(self.trader.get_target_symbols()):
                text += '\n'

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

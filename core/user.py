import os
import json
import aiofiles
import math
import traceback
from pytz import timezone
from datetime import datetime
import numpy as np
from core.misc import read_config_okx


class UserData():
    """
        UserData 기능
        - 전체 계좌 금액 관리
        - 코인 별 상태 저장
    """
    def __init__(self):
        config = read_config_okx()
        self.config = config

        self.data = {}
        self.user_name = self.config['USER']['NAME']
        self.user_id = self.config['USER']['ID']
        self.balance = 0
        self.cum_profit = 0
        self.cum_pnl = 0
        self.win_cnt = 0
        self.tot_cnt = 0

        for target in self.config['OKX']['TARGET']:
            if target not in self.data:
                self.data[target] = {}

            ticker = target.split('/')[0]
            options = self.config['TRADE_OPTION'][ticker]

            for k, v in options.items():
                self.data[target][k] = v
            self.data[target]['position'] = None
            self.data[target]['amt'] = 0
            self.data[target]['buy_cnt'] = 0
            self.data[target]['max_buy_cnt'] = 500
            self.data[target]['avg_buy_price'] = 0
            self.data[target]['position_list'] = 0
            self.data[target]['buy_time'] = 0
            self.data[target]['sell_time'] = 0

        self.load_info()

    def get_target_symbols(self):
        return self.config['OKX']['TARGET']

    def update(self, target_symbol, key, value=None):
        assert key is not None, f"{target_symbol} - Error! Key shouldn't None!"

        if target_symbol is None:
            setattr(self, key, value)
        else:
            assert key in self.data[target_symbol], f"{target_symbol} - Error! Key Not Founded"
            self.data[target_symbol][key] = value

    def get_info(self, target_symbol, key):
        assert key is not None, f"{target_symbol} | {key} - Error! Key shouldn't None!"

        if target_symbol is None:
            return getattr(self, key)
        else:
            assert key in self.data[target_symbol], f"{target_symbol} | {key}  - Error! Key Not Founded"
            return self.data[target_symbol][key]

    def update_pos_list(self, target_symbol, qty):
        self.data[target_symbol]['position_list'].append(qty)

    def remove_pos_list(self, target_symbol):
        return self.data[target_symbol]['position_list'].pop()

    def recal_pos_list(self, target_symbol, amt):
        # -----------------------------
        # 기본 정보 로드
        # -----------------------------
        position_list = []
        prev_positions = self.get_info(target_symbol, key='position_list')
        max_cnt = self.get_info(target_symbol, key='max_buy_cnt')
        min_vol = self.get_info(target_symbol, key='min_vol')

        real_cnt = round(amt / min_vol)

        # -----------------------------
        # last_qty 계산
        # -----------------------------
        buy_ratio = real_cnt / max_cnt

        if buy_ratio > 0.5:
            last_qty = real_cnt // 2
        elif buy_ratio > 0.25:
            last_qty = real_cnt // 3
        else:
            last_qty = 0

        base_cnt = real_cnt - last_qty if last_qty > 0 else real_cnt

        # -----------------------------
        # 공통 유틸: 4단위 분할
        # -----------------------------
        def split_by_4(cnt):
            result = []
            while cnt > 0:
                if cnt >= 4:
                    result.append(4)
                    cnt -= 4
                else:
                    result.append(cnt)
                    break
            return result

        # -----------------------------
        # 기존 포지션이 있는 경우
        # -----------------------------
        cum_cnt = 0

        if prev_positions:
            matched = False

            for qty in prev_positions:
                if matched:
                    break

                used = 0
                for _ in range(int(qty)):
                    if cum_cnt == base_cnt:
                        matched = True
                        break
                    used += 1
                    cum_cnt += 1

                if matched:
                    position_list.append(used)
                    break
                else:
                    position_list.append(qty)

            # 남은 수량 분배
            remain = base_cnt - cum_cnt
            if last_qty == 0 and remain > 0:
                position_list.extend(split_by_4(remain))
                cum_cnt += remain

        # -----------------------------
        # 기존 포지션이 없는 경우
        # -----------------------------
        else:
            if base_cnt <= max_cnt:
                position_list.extend(split_by_4(base_cnt))
                cum_cnt = base_cnt
            else:
                position_list.extend(split_by_4(base_cnt))
                cum_cnt = base_cnt

        # -----------------------------
        # last_qty 추가
        # -----------------------------
        if last_qty > 0:
            position_list.append(last_qty)
            cum_cnt += last_qty

        # -----------------------------
        # 결과 저장
        # -----------------------------
        self.update(target_symbol, key='position_list', value=position_list)

        # -----------------------------
        # 반환 cnt 보정
        # -----------------------------
        if cum_cnt > 0 and cum_cnt * min_vol < amt:
            return amt // cum_cnt

        return int(cum_cnt)

    def get_telegram_id(self):
        return self.config['TELEGRAM']['ID']

    def get_telegram_token(self):
        return self.config['TELEGRAM']['TOKEN']

    def calc_profit(self, target_symbol, filled_price, filled_vol):
        position = self.get_info(target_symbol, key='position')
        avg_price = self.data[target_symbol]['avg_buy_price']

        if position == 'long':
            diff = (filled_price - avg_price)

        elif position == 'short':
            diff = (avg_price - filled_price)

        print('profit : ', diff, filled_vol, self.commition)

        profit = ((diff * filled_vol) * (1 - self.commition * 2)) # * self.leverage

        return profit

    def get_real_trade_vol(self, target_symbol, trade_vol):
        min_vol = self.get_info(target_symbol, key='min_vol')
        map_vol = self.get_info(target_symbol, key='map_vol')

        return min_vol / map_vol * trade_vol

    def get_belong_vol(self, target_symbol, is_trade=True):
        amt = self.get_info(target_symbol, key='amt')
        map_vol = self.get_info(target_symbol, key='map_vol')
        rnd_num = self.get_info(target_symbol, key='round_num')

        if is_trade:
            return round(amt * map_vol, rnd_num)
        else:
            return amt

    def get_buy_vol(self, target_symbol):
        min_vol = self.get_info(target_symbol, key='min_vol')
        map_vol = self.get_info(target_symbol, key='map_vol')

        return min_vol / map_vol

    def get_buy_vol_okx(self, target_symbol, position=None):
        target_coin = self.symbol_parser(target_symbol)
        
        lev = self.config['MAP_COIN_VOLUME'][target_coin]

        if position == 'short':
            return round(self.target_info[target_coin]['buy_vol'] * lev/2, 1)
        else:
            return round(self.target_info[target_coin]['buy_vol'] * lev, 1)

    def load_info(self):
        if os.path.exists(self.config['SAVE_PATH']):
            with open(self.config['SAVE_PATH'], 'r') as f:
                data = json.load(f)
            
            for k, v in data.items():
                try:
                    if k in self.get_target_symbols():
                        for k2, v2 in v.items():
                            self.target_info[k][k2] = v2
                    else:
                        setattr(self, k, v)
                except:
                    print(traceback.format_exc())
                    print('Error! ', k, v, k2, v2)

            print('Load info Success!')

    async def save_info(self):
        class NpEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, np.integer):
                    return int(obj)
                if isinstance(obj, np.floating):
                    return float(obj)
                if isinstance(obj, np.ndarray):
                    return obj.tolist()
                return super(NpEncoder, self).default(obj)
    
        data = {}

        data['user_name'] = self.user_name
        data['user_id'] = self.user_id
        data['balance'] = self.balance
        data['cum_profit'] = self.cum_profit
        data['cum_pnl'] = self.cum_pnl
        data['win_cnt'] = self.win_cnt
        data['tot_cnt'] = self.tot_cnt

        for t_coin in self.get_target_symbols():
            data[t_coin] = {}
            for k, v in self.data[t_coin].items():
                data[t_coin][k] = v
        
        async with asyncio.Lock():
            async with aiofiles.open(self.config['SAVE_PATH'], mode='w') as f:
                await f.write(json.dumps(data, indent=4, cls=NpEncoder))
                print('Save info Success!')

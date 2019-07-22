import time

from vnpy.trader.utility import round_to

from vnpy.app.cta_strategy import (
    CtaTemplate,
    TickData,
    TradeData,
    OrderData,
)
from vnpy.trader.constant import Status, Direction
from vnpy.trader.util_wx_ft import sendWxMsg

"""
币币交易区间网格策略
跌到区间下限清仓，上涨到区间上限无动作
区间内从baseline出发上涨height就平，下跌height就开，高抛低吸
"""
class GridTradeStrategy(CtaTemplate):
    """"""
    author = "czhu"

    # this is LTC example
    # parameter from setting,json
    quote = "usdt"
    input_ss = 0.1
    grid_up_line = 120
    grid_mid_line = 100
    grid_dn_line = 90
    grid_height = 4

    # variable in data.json
    base_line = 0
    buy_times = 0
    sell_times = 0
    roi = 0.0

    parameters = ["quote", "input_ss", "grid_up_line", "grid_mid_line", "grid_dn_line", "grid_height"]
    variables = ["base_line", "buy_times", "sell_times", "roi"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        """"""
        super(GridTradeStrategy, self).__init__(
            cta_engine, strategy_name, vt_symbol, setting
        )

        if self.base_line == 0:
            self.base_line = self.grid_mid_line

        dict = self.vt_symbol.partition(self.quote)  #vt_symbol = ltcusdt.HUOBI
        self.base = dict[0]         #ltc

        self.rate = 0.002           # huobi rate
        if dict[2] == '.BINANCE':
            self.rate = 0.001

        self.min_diff = 0.01        # LTC,BTC
        self.min_volumn = 0.001     # 0.001ETH, 0.001LTC
        if self.base == 'btc':
            self.min_volumn = 0.0001
        elif self.base == 'ht':
            self.min_diff = 0.0001
            self.min_volumn = 0.1

    def on_init(self):
        """
        Callback when strategy is inited.
        """
        self.write_log("策略初始化")

    def on_start(self):
        """
        Callback when strategy is started.
        """
        self.new_up = self.base_line * (1 + self.grid_height / 100)
        self.new_down = self.base_line / (1 + self.grid_height / 100)
        self.new_down = round_to(self.new_down, self.min_diff)

        self.entrust = 0
        self.__singleton1 = True
        self.__singleton2 = True

        self.write_log("策略启动")

    def on_stop(self):
        """
        Callback when strategy is stopped.
        """
        self.write_log("策略停止")


    def on_tick(self, tick: TickData):
        """
        Callback of new tick data update. run once one second
        """
        # 首先检查是否是实盘运行还是数据预处理阶段
        if not self.inited or not self.trading:
            return

        if tick.last_price > self.grid_up_line or tick.last_price < self.grid_dn_line:
            if (self.__singleton1):
                sendWxMsg(u'价格超出区间')
                self.__singleton1 = False
            return

        if self.entrust != 0:
            if (self.__singleton2):
                sendWxMsg(u'委托单未全部成交')
                self.__singleton2 = False
            time.sleep(60*1)
            return

        # 下限清仓
        if tick.last_price <= self.grid_dn_line + self.min_diff:
            base_pos = self.cta_engine.main_engine.get_account('.'.join([tick.exchange.value, self.base]))
            sell_volume = base_pos.balance
            sell_volume = round_to(sell_volume, self.min_volumn)
            if sell_volume >= self.min_volumn:
                price = tick.bid_price_1  # 买一价
                price= round_to(price, self.min_diff)
                ref = self.sell(price=price, volume=sell_volume)
                if ref is not None and len(ref) > 0:
                    self.entrust = -1
                    self.write_log(u'清仓委托卖出成功, 委托编号:{},委托价格:{},卖出数量{}'.format(ref, price, sell_volume))
                    sendWxMsg(u'清仓委托卖出成功' ,u'委托编号:{},委托价格:{},卖出数量{}'.format(ref, price, sell_volume) )
                else:
                    self.write_log(u'清仓委托卖出{}失败,价格:{},数量:{}'.format(self.vt_symbol, price, sell_volume))

        price= tick.last_price

        if price <= self.new_down:
            # 买入,开多
            account = self.cta_engine.main_engine.get_account('.'.join([tick.exchange.value, self.quote]))
            price = tick.ask_price_1  #卖一价
            price = round_to(price, self.min_diff)
            buy_volume = min(account.balance/price, float(self.input_ss))
            buy_volume = round_to(buy_volume, self.min_volumn)
            if buy_volume < self.min_volumn:
                return

            ref = self.buy(price=price, volume=buy_volume)
            if ref is not None and len(ref) > 0:
                self.entrust = 1
                self.write_log(u'开多委托单号{},委托价：{},数量{}'.format(ref, price, buy_volume ))
            else:
                self.write_log(u'开多委托单失败:价格:{},数量:{}'.format(price, buy_volume))

        elif price >= self.new_up:
            # 卖出，平多
            base_pos = self.cta_engine.main_engine.get_account('.'.join([tick.exchange.value, self.base]))
            price = tick.bid_price_1  #买一价
            price = round_to(price, self.min_diff)
            sell_volume = min(base_pos.balance, float(self.input_ss))
            sell_volume = round_to(sell_volume, self.min_volumn)
            if sell_volume < self.min_volumn:
                return
            ref = self.sell(price=price, volume=sell_volume)
            if ref is not None and len(ref) > 0:
                self.entrust = -1
                self.write_log(u'委托卖出成功, 委托编号:{},委托价格:{},卖出数量{}'.format(ref, price, sell_volume))
            else:
                self.write_log(u'委托卖出{}失败,价格:{},数量:{}'.format(self.vt_symbol, price, sell_volume))


    def on_order(self, order: OrderData):
        """
        Callback of new order data update.
        """
        msg = u'报单更新,委托编号:{},合约:{},方向:{},价格:{},委托:{},成交:{},状态:{}'.format(order.orderid, order.symbol,
                                 order.direction, order.price,
                                 order.volume,order.traded,
                                 order.status)
        self.write_log(msg)

        if order.volume == order.traded or order.status == Status.ALLTRADED:
            # 开仓，平仓委托单全部成交
            # 计算收益
            if order.direction == Direction.LONG:
                self.buy_times = self.buy_times + 1
                if self.buy_times <= self.sell_times:
                    self.roi = self.roi + (self.base_line - order.price - order.price * self.rate) * order.volume
                else:
                    self.roi = self.roi - order.price * order.volume * self.rate
            else:
                self.sell_times = self.sell_times + 1
                if self.sell_times <= self.buy_times:
                    self.roi = self.roi + (order.price - self.base_line  - order.price * self.rate) * order.volume
                else:
                    self.roi = self.roi - order.price * order.volume * self.rate

            self.base_line = order.price
            self.new_up = self.base_line * (1 + self.grid_height / 100)
            self.new_down = self.base_line / (1 + self.grid_height / 100)
            self.new_down = round_to(self.new_down, self.min_diff)
            self.entrust = 0

            sub = u'{}, {}'.format(order.direction, order.price)
            self.roi = round_to(self.roi, 0.0001)
            msg2 = u'{},\n低吸次数:{},高抛次数:{},套利:{} {}'.format(msg, self.buy_times, self.sell_times, self.roi,self.quote)
            self.send_email(msg2)
            sendWxMsg(sub, msg2)
        elif order.status in [Status.CANCELLED,Status.REJECTED]:
            self.entrust = 0

        self.put_event()

    def on_trade(self, trade: TradeData):
        """
        Callback of new trade data update.
        """
        self.put_event()
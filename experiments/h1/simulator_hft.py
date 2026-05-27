"""
simulator_hft.py — версия с front-running механизмом
=====================================================
Ключевое изменение:

1. Медленные агенты вызываются первыми в "режиме перехвата" —
   их заявки НЕ исполняются сразу, а накапливаются в pending_orders.

2. Быстрые агенты видят pending_orders медленных и могут
   вставить свои заявки ПЕРЕД ними (front-run).

3. После этого pending_orders медленных исполняются —
   но рынок уже сдвинулся из-за действий быстрых.

Это реализует классический HFT front-running:
   медленный хочет купить по ask → быстрый покупает первым →
   ask сдвигается вверх → медленный платит больше или не исполняется.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from AgentBasedModel.agents import ExchangeAgent, Universalist, Chartist, Fundamentalist, MarketMaker
from AgentBasedModel.utils import Order
from AgentBasedModel.utils.math import mean, std, rolling
import random
from tqdm import tqdm


class InterceptingExchange:
    """
    Обёртка вокруг ExchangeAgent которая перехватывает заявки
    и складывает их в pending_orders вместо немедленного исполнения.
    """
    def __init__(self, exchange: ExchangeAgent):
        self.exchange = exchange
        self.pending_orders = []   # список (order, method)
        self.intercepting = False  # режим перехвата вкл/выкл

    def __getattr__(self, name):
        return getattr(self.exchange, name)

    def limit_order(self, order: Order):
        if self.intercepting:
            self.pending_orders.append((order, 'limit'))
        else:
            self.exchange.limit_order(order)

    def market_order(self, order: Order) -> Order:
        if self.intercepting:
            self.pending_orders.append((order, 'market'))
            return order  # возвращаем как будто не исполнено
        else:
            return self.exchange.market_order(order)

    def cancel_order(self, order: Order):
        self.exchange.cancel_order(order)

    def flush_pending(self):
        """Исполняем все накопленные заявки медленных агентов."""
        for order, method in self.pending_orders:
            if method == 'limit':
                self.exchange.limit_order(order)
            else:
                self.exchange.market_order(order)
        self.pending_orders.clear()


class Simulator:
    """
    Simulator с front-running механизмом.

    Порядок внутри итерации:
    1. Медленные агенты в режиме перехвата — заявки в pending
    2. Быстрые агенты видят pending и front-run — заявки исполняются сразу
    3. Pending медленных исполняются — рынок уже сдвинулся
    """

    def __init__(self, exchange: ExchangeAgent = None, traders: list = None, events: list = None):
        self.exchange = exchange
        self.events = [event.link(self) for event in events] if events else None
        self.traders = traders
        self.info = SimulatorInfo(self.exchange, self.traders)

        # Создаём intercepting обёртку и подключаем агентов к ней
        self._ix = InterceptingExchange(exchange)
        for trader in self.traders:
            trader.market = self._ix

    def _payments(self):
        for trader in self.traders:
            trader.cash += trader.assets * self.exchange.dividend()
            trader.cash += trader.cash * self.exchange.risk_free

    def simulate(self, n_iter: int, silent=False,
                 fast_extra_call=True,
                 front_running=True) -> object:
        ix = self._ix

        for it in tqdm(range(n_iter), desc='Simulation', disable=silent):
            if self.events:
                for event in self.events:
                    event.call(it)

            self.info.capture()

            for trader in self.traders:
                if type(trader) == Universalist:
                    trader.change_strategy(self.info)
                elif type(trader) == Chartist:
                    trader.change_sentiment(self.info)

            fast = [t for t in self.traders if getattr(t, 'speed', 'slow') == 'fast']
            slow = [t for t in self.traders if getattr(t, 'speed', 'slow') != 'fast']

            if front_running and fast:
                # Шаг 1: медленные → pending
                ix.intercepting = True
                random.shuffle(slow)
                for trader in slow:
                    trader.call()
                ix.intercepting = False

                # Шаг 2: быстрые front-run
                random.shuffle(fast)
                for trader in fast:
                    trader.call()
                if fast_extra_call:
                    random.shuffle(fast)
                    for trader in fast:
                        trader.call()

                # Шаг 3: исполняем pending медленных
                ix.flush_pending()

            else:
                # Без front-running
                all_traders = fast + slow
                random.shuffle(all_traders)
                for trader in all_traders:
                    trader.call()

            self._payments()
            self.exchange.generate_dividend()

        return self


class SimulatorInfo:
    def __init__(self, exchange: ExchangeAgent = None, traders: list = None):
        self.exchange = exchange
        self.traders = {t.id: t for t in traders}

        self.prices = list()
        self.spreads = list()
        self.dividends = list()
        self.orders = list()
        self.equities = list()
        self.cash = list()
        self.assets = list()
        self.types = list()
        self.sentiments = list()
        self.returns = [{tr_id: 0 for tr_id in self.traders.keys()}]
        self.mm_panic = []

    def capture(self):
        self.prices.append(self.exchange.price())
        self.spreads.append(self.exchange.spread())
        self.dividends.append(self.exchange.dividend())
        self.orders.append({
            'quantity': {
                'bid': len(self.exchange.order_book['bid']),
                'ask': len(self.exchange.order_book['ask'])
            },
        })
        self.equities.append({t_id: t.equity() for t_id, t in self.traders.items()})
        self.cash.append({t_id: t.cash for t_id, t in self.traders.items()})
        self.assets.append({t_id: t.assets for t_id, t in self.traders.items()})
        self.types.append({t_id: t.type for t_id, t in self.traders.items()})
        self.sentiments.append({
            t_id: t.sentiment
            for t_id, t in self.traders.items()
            if t.type == 'Chartist'
        })
        if len(self.equities) > 1:
            self.returns.append({
                tr_id: (self.equities[-1][tr_id] - self.equities[-2][tr_id]) / self.equities[-2][tr_id]
                for tr_id in self.traders.keys()
            })
        self.mm_panic.append({
            t_id: getattr(t, 'panic', False)
            for t_id, t in self.traders.items()
            if type(t) == MarketMaker
        })

    def mm_panic_ratio(self, from_it: int = 0) -> float:
        subset = self.mm_panic[from_it:]
        if not subset:
            return 0.0
        return sum(1 for snap in subset if any(snap.values())) / len(subset)

    def price_volatility(self, window: int = None):
        if window is None:
            return std(self.prices)
        return [std(self.prices[i:i+window]) for i in range(len(self.prices) - window)]

    def stock_returns(self, roll: int = None):
        p = self.prices
        div = self.dividends
        r = [(p[i+1] - p[i]) / p[i] + div[i] / p[i] for i in range(len(p) - 1)]
        return rolling(r, roll) if roll else mean(r)

    def abnormal_returns(self, roll: int = None):
        rf = self.exchange.risk_free
        r = [r - rf for r in self.stock_returns()]
        return rolling(r, roll) if roll else r

    def return_volatility(self, window: int = None):
        if window is None:
            return std(self.stock_returns())
        n = len(self.stock_returns(1))
        return [std(self.stock_returns(1)[i:i+window]) for i in range(n - window)]

    def liquidity(self, roll: int = None):
        n = len(self.prices)
        spreads = [el['ask'] - el['bid'] for el in self.spreads]
        liq = [spreads[i] / self.prices[i] for i in range(n)]
        return rolling(liq, roll) if roll else mean(liq)

    def fundamental_value(self, access: int = 1) -> list:
        divs = self.dividends.copy()
        n = len(divs)
        divs.extend(self.exchange.dividend(access)[1:access])
        r = self.exchange.risk_free
        return [Fundamentalist.evaluate(divs[i:i+access], r) for i in range(n)]

from AgentBasedModel.agents import ExchangeAgent, Universalist, Chartist, Fundamentalist, MarketMaker
from AgentBasedModel.utils.math import mean, std, difference, rolling
import random
from tqdm import tqdm


class Simulator:
    """
    Simulator is responsible for launching agents' actions and executing scenarios.

    H1 modification: supports fast/slow agent split via `speed` attribute on traders.
    Fast agents act first each iteration, and optionally get an extra call.
    Set trader.speed = 'fast' before calling simulate().
    Control extra call via fast_extra_call parameter in simulate().
    """
    def __init__(self, exchange: ExchangeAgent = None, traders: list = None, events: list = None):
        self.exchange = exchange
        self.events = [event.link(self) for event in events] if events else None
        self.traders = traders
        self.info = SimulatorInfo(self.exchange, self.traders)

    def _payments(self):
        for trader in self.traders:
            trader.cash += trader.assets * self.exchange.dividend()
            trader.cash += trader.cash * self.exchange.risk_free

    def simulate(self, n_iter: int, silent=False, fast_extra_call=False, speed_multiplier=1) -> object:
        """
        :param n_iter: number of iterations
        :param silent: suppress progress bar
        :param fast_extra_call: if True, fast agents get an additional call per iteration
                                (H1: simulates shorter reaction latency)
        :param speed_multiplier: fast agents trade this many times per iteration (1 = same as slow)
        """
        for it in tqdm(range(n_iter), desc='Simulation', disable=silent):
            # Call scenario events
            if self.events:
                for event in self.events:
                    event.call(it)

            # Record order book state for delayed information
            self.exchange.record_state()

            # Capture current state BEFORE trading
            self.info.capture()

            # Update strategies / sentiments
            for trader in self.traders:
                if type(trader) == Universalist:
                    trader.change_strategy(self.info)
                elif type(trader) == Chartist:
                    trader.change_sentiment(self.info)

            # ── H1: fast / slow split ──────────────────────────────────────
            fast = [t for t in self.traders if getattr(t, 'speed', 'slow') == 'fast']
            slow = [t for t in self.traders if getattr(t, 'speed', 'slow') != 'fast']

            # Fast agents act first, speed_multiplier times
            for _ in range(speed_multiplier):
                random.shuffle(fast)
                for trader in fast:
                    trader.call()

            # Extra call for fast agents (legacy, kept for backward compat)
            if fast_extra_call and fast:
                random.shuffle(fast)
                for trader in fast:
                    trader.call()

            # Slow agents act after
            random.shuffle(slow)
            for trader in slow:
                trader.call()
            # ──────────────────────────────────────────────────────────────

            # Payments and dividends
            self._payments()
            self.exchange.generate_dividend()

        return self


class SimulatorInfo:
    """
    SimulatorInfo is responsible for capturing data during simulating.

    H1 modification: added mm_panic list to track MarketMaker panic state each iteration.
    """

    def __init__(self, exchange: ExchangeAgent = None, traders: list = None):
        self.exchange = exchange
        self.traders = {t.id: t for t in traders}

        # Market Statistics
        self.prices = list()
        self.spreads = list()
        self.dividends = list()
        self.orders = list()

        # Agent statistics
        self.equities = list()
        self.cash = list()
        self.assets = list()
        self.types = list()
        self.sentiments = list()
        self.returns = [{tr_id: 0 for tr_id in self.traders.keys()}]

        # H1: MarketMaker panic state per iteration
        # Each entry: {trader_id: True/False} for all MarketMaker agents
        self.mm_panic = []

    def capture(self):
        # Market Statistics
        try:
            price = self.exchange.price()
        except Exception:
            price = self.prices[-1] if self.prices else 0
        self.prices.append(price)
        self.spreads.append(self.exchange.spread())
        self.dividends.append(self.exchange.dividend())
        self.orders.append({
            'quantity': {
                'bid': len(self.exchange.order_book['bid']),
                'ask': len(self.exchange.order_book['ask'])
            },
        })

        # Trader Statistics
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

        # H1: record MarketMaker panic state
        self.mm_panic.append({
            t_id: getattr(t, 'panic', False)
            for t_id, t in self.traders.items()
            if type(t) == MarketMaker
        })

    def fundamental_value(self, access: int = 1) -> list:
        divs = self.dividends.copy()
        n = len(divs)
        divs.extend(self.exchange.dividend(access)[1:access])
        r = self.exchange.risk_free
        return [Fundamentalist.evaluate(divs[i:i+access], r) for i in range(n)]

    def stock_returns(self, roll: int = None) -> list or float:
        p = self.prices
        div = self.dividends
        r = [(p[i+1] - p[i]) / p[i] + div[i] / p[i] for i in range(len(p) - 1)]
        return rolling(r, roll) if roll else mean(r)

    def abnormal_returns(self, roll: int = None) -> list:
        rf = self.exchange.risk_free
        r = [r - rf for r in self.stock_returns()]
        return rolling(r, roll) if roll else r

    def return_volatility(self, window: int = None) -> list or float:
        if window is None:
            return std(self.stock_returns())
        n = len(self.stock_returns(1))
        return [std(self.stock_returns(1)[i:i+window]) for i in range(n - window)]

    def price_volatility(self, window: int = None) -> list or float:
        if window is None:
            return std(self.prices)
        return [std(self.prices[i:i+window]) for i in range(len(self.prices) - window)]

    def liquidity(self, roll: int = None) -> list or float:
        n = len(self.prices)
        spreads = [el['ask'] - el['bid'] for el in self.spreads]
        prices = self.prices
        liq = [spreads[i] / prices[i] for i in range(n)]
        return rolling(liq, roll) if roll else mean(liq)

    def mm_panic_ratio(self, from_it: int = 0) -> float:
        """
        Fraction of iterations (from_it onwards) where ANY MarketMaker was in panic.
        Convenience method for H1 analysis.
        """
        subset = self.mm_panic[from_it:]
        if not subset:
            return 0.0
        panic_count = sum(1 for snap in subset if any(snap.values()))
        return panic_count / len(subset)
"""Eén zelflerende bot per munt.

Per afgesloten candle:
  1. stop-loss controleren
  2. elke strategie belonen voor wat ze virtueel verdiende (na kosten)
  3. het model laten leren van voorspellingen waarvan de uitkomst nu bekend is
  4. nieuwe signalen en een nieuwe voorspelling maken
  5. om de paar candles via de strategiekiezer bepalen welke strategie de bot volgt
  6. de risicoregels toepassen en (paper) traden
"""
import math
import random
from collections import deque

from .bandit import DiscountedThompson
from .config import NAMES
from .features import FeatureEngine
from .model import OnlineLogReg
from .portfolio import Portfolio
from .risk import RiskManager
from .strategies import KEYS, STRATEGIES

VERSION = 2


class TradingBot:
    def __init__(self, symbol, settings, use_ref=False, seed=None):
        self.version = VERSION
        self.symbol = symbol
        self.s = settings
        self.engine = FeatureEngine(use_ref)
        self.model = OnlineLogReg(len(self.engine.names), settings.learning_rate, settings.l2)
        self.bandit = DiscountedThompson(KEYS, settings.bandit_discount)
        self.virt = {k: 0.0 for k in KEYS}        # virtuele blootstelling per strategie
        self.virt_cost = {k: 0.0 for k in KEYS}
        self.active = None
        self.last_decision = -10 ** 9
        self.active_counts = {k: 0 for k in KEYS}
        self.portfolio = Portfolio(settings.start_capital)
        self.risk = RiskManager(settings)
        self.risk_note = ""
        self.pending = deque()
        self.index = 0
        self.last_t = None
        self.prev_close = None
        self.last_price = None
        self.p = None
        self.start_price = None
        self.start_t = None
        self.history = deque(maxlen=3000)
        self.peak_equity = 0.0
        self.max_dd = 0.0

    # ------------------------------------------------------------------ leren
    def step(self, k, ref=None, trade=True):
        """Verwerk een afgesloten candle. trade=False: alleen leren (opwarmen/inhalen)."""
        if self.last_t is not None and k["t"] <= self.last_t:
            return None
        self.last_t = k["t"]
        self.index += 1
        c = k["c"]
        self.last_price = c
        pf = self.portfolio

        if trade:
            self._check_exits(k["o"], k["l"], k["t"])
            pf.charge_funding(c, self.s.funding_per_candle)

        if self.prev_close:
            ret = math.log(c / self.prev_close)
            fund = self.s.funding_per_candle
            self.bandit.update({a: 1e4 * (self.virt[a] * (ret - fund) - self.virt_cost[a]) for a in KEYS})
        self.virt_cost = {a: 0.0 for a in KEYS}
        self.prev_close = c

        feats = self.engine.update(k, ref)
        if feats is None:
            if trade:
                self._record(k["t"], c)
            return None

        threshold = 2 * self.s.cost  # stijging moet koop- en verkoopkosten dekken
        while self.pending and self.pending[0][0] + self.s.horizon <= self.index:
            _, x_old, c_old = self.pending.popleft()
            self.model.update(x_old, 1 if math.log(c / c_old) > threshold else 0)

        x = feats["x"]
        self.model.observe(x)
        self.p = self.model.predict(x) if self.model.updates >= self.s.min_model_updates else None
        self.pending.append((self.index, x, c))

        for a in KEYS:
            new = STRATEGIES[a][1](feats["ind"], self.virt[a], self.p, self.model.base_rate)
            self.virt_cost[a] = self.s.cost * abs(new - self.virt[a])
            self.virt[a] = new

        if self.active is None or self.index - self.last_decision >= self.s.decision_every:
            self._choose()

        if trade:
            self._trade(k)
            self._record(k["t"], c)
        return feats

    def _choose(self):
        """Kies een strategie. Wissel alleen als de verwachte winst de wisselkosten dekt."""
        self.last_decision = self.index
        pick = self.bandit.choose(self.s.confidence)
        if self.active is None or pick == self.active:
            self.active = pick
            return
        switch_bps = 1e4 * self.s.cost * abs(self.virt[pick] - self.virt[self.active])
        gain_bps = self.bandit.posterior(pick)[0] - self.bandit.posterior(self.active)[0]
        if gain_bps * self.s.decision_every > switch_bps:
            self.active = pick

    # ---------------------------------------------------------------- traden
    def _trade(self, k):
        pf, price = self.portfolio, k["c"]
        if self.start_price is None:
            self.start_price, self.start_t = price, k["t"]
        self.risk.on_candle(k["t"], pf.equity(price))
        self.active_counts[self.active] += 1
        target, self.risk_note = self.risk.filter(self.virt[self.active] * self.s.max_exposure, self.index)
        cur = pf.exposure(price)
        if (target <= 0 and pf.qty > 0) or abs(target - cur) >= self.s.min_rebalance * self.s.max_exposure:
            reason = self.risk_note or STRATEGIES[self.active][0]
            pf.rebalance(target, price, k["t"], reason, self.active, self.s.fee_rate, self.s.slippage)

    def _sell_all(self, price, t, reason):
        self.portfolio.rebalance(0.0, price, t, reason, self.active, self.s.fee_rate, self.s.slippage)

    def _check_exits(self, open_, low, t):
        """Stop-loss en liquidatie. De koers loopt van open naar low; wat eerst geraakt wordt telt."""
        pf = self.portfolio
        if pf.qty <= 0:
            return
        sp = self.risk.stop_price(pf.entry)
        liq = pf.liquidation_price(self.s.maintenance_margin)
        if liq is not None and liq >= sp:      # positie zo groot dat liquidatie eerder komt
            sp = None
        if liq is not None and open_ <= liq:
            pf.liquidate(open_, t, self.active, self.s.maintenance_margin)
        elif sp is not None and open_ <= sp:
            self._sell_all(open_, t, "stop-loss")
            self.risk.trigger_stop(self.index)
        elif sp is not None and low <= sp:
            self._sell_all(sp, t, "stop-loss")
            self.risk.trigger_stop(self.index)
        elif liq is not None and low <= liq:
            pf.liquidate(liq, t, self.active, self.s.maintenance_margin)

    def _loss_at_stop(self):
        """Wat de open positie kost (t.o.v. de instap) als de stop-loss geraakt wordt."""
        pf = self.portfolio
        if pf.qty <= 0:
            return 0.0
        exit_price = self.risk.stop_price(pf.entry) * (1 - self.s.slippage)
        return pf.qty * (pf.entry - exit_price) + pf.qty * exit_price * self.s.fee_rate

    def tick(self, price, t):
        """Live koers tussen candles door: stop-loss en liquidatie direct uitvoeren."""
        self.last_price = price
        self._check_exits(price, price, t)

    def pause(self, t):
        self.risk.paused = True
        if self.portfolio.qty > 0 and self.last_price:
            self._sell_all(self.last_price, t, "handmatig gepauzeerd")

    def resume(self):
        self.risk.resume(self.portfolio.equity(self.last_price or 0))

    def _record(self, t, price):
        eq = self.portfolio.equity(price)
        self.history.append((t, eq, price))
        self.peak_equity = max(self.peak_equity, eq)
        if self.peak_equity > 0:
            self.max_dd = max(self.max_dd, 1 - eq / self.peak_equity)

    # ---------------------------------------------------------------- status
    def status(self, chart_points=600):
        pf = self.portfolio
        price = self.last_price or 0.0
        eq = pf.equity(price)
        probs = self.bandit.probabilities(random.Random(self.index))
        total_active = sum(self.active_counts.values()) or 1
        strategies = []
        for a in KEYS:
            mean, sd = self.bandit.posterior(a)
            strategies.append({
                "key": a, "label": STRATEGIES[a][0], "prob": probs[a],
                "mean_bps": mean, "sd_bps": sd,
                "lower_bps": mean - self.s.confidence * sd,
                "virtual_return_pct": (math.exp(self.bandit.total[a]) - 1) * 100,
                "position": self.virt[a],
                "used_pct": self.active_counts[a] / total_active * 100,
            })
        hist = list(self.history)
        step = max(1, len(hist) // chart_points)
        chart = hist[::step]
        if hist and chart[-1] != hist[-1]:
            chart.append(hist[-1])
        sp = self.risk.stop_price(pf.entry)
        if self.risk.paused or self.risk.killed:
            state = "gestopt"
        elif self.risk_note:
            state = "geblokkeerd"
        else:
            state = "actief"
        return {
            "symbol": self.symbol,
            "interval": self.s.interval,
            "name": NAMES.get(self.symbol, self.symbol),
            "price": price,
            "last_candle": self.last_t,
            "candles_seen": self.index,
            "equity": eq,
            "start_capital": pf.start,
            "pnl": eq - pf.start,
            "pnl_pct": (eq / pf.start - 1) * 100,
            "buy_hold_pct": (price / self.start_price - 1) * 100 if self.start_price else 0.0,
            "trading_since": self.start_t,
            "balance": pf.balance,
            "qty": pf.qty,
            "entry": pf.entry,
            "leverage": self.s.leverage,
            "max_exposure": self.s.max_exposure,
            "risk_per_trade": self.s.risk_per_trade,
            "loss_at_stop": self._loss_at_stop(),
            "exposure": pf.exposure(price) if price else 0.0,
            "notional": pf.notional(price),
            "unrealized": pf.unrealized(price),
            "unrealized_pct": (price / pf.entry - 1) * 100 if pf.entry else 0.0,
            "stop_price": sp,
            "liquidation_price": pf.liquidation_price(self.s.maintenance_margin),
            "fees": pf.fees,
            "funding": pf.funding,
            "liquidations": pf.liquidations,
            "n_trades": pf.n_trades,
            "max_drawdown_pct": self.max_dd * 100,
            "active_strategy": self.active,
            "active_label": STRATEGIES[self.active][0] if self.active else None,
            "strategies": strategies,
            "model": {
                "updates": self.model.updates,
                "ready": self.p is not None,
                "p": self.p,
                "base_rate": self.model.base_rate,
                "metrics": self.model.metrics(),
                "top_weights": self.model.top_weights(self.engine.names),
            },
            "risk": {"state": state, "note": self.risk_note, "paused": self.risk.paused,
                     "killed": self.risk.killed},
            "trades": list(pf.trades)[-25:][::-1],
            "chart": chart,
        }

"""Eén zelflerende bot per munt.

Per afgesloten candle:
  1. stop-loss en liquidatie controleren
  2. elke strategie belonen voor wat ze virtueel verdiende (na kosten)
  3. het model laten leren van voorspellingen waarvan de uitkomst nu bekend is
  4. nieuwe signalen en een nieuwe voorspelling maken
  5. om de paar candles via de strategiekiezer bepalen welke strategie de bot volgt
  6. de risicoregels toepassen en (paper) traden: long, short of niets,
     met hoogstens één positie tegelijk
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

VERSION = 5


class TradingBot:
    def __init__(self, symbol, settings, use_ref=False, seed=None):
        self.version = VERSION
        self.symbol = symbol
        self.s = settings
        self.engine = FeatureEngine(use_ref, settings.funding_features)
        n = len(self.engine.names)
        self.model_up = OnlineLogReg(n, settings.learning_rate, settings.l2)    # kans op stijging
        self.model_down = OnlineLogReg(n, settings.learning_rate, settings.l2)  # kans op daling
        self.bandit = DiscountedThompson(KEYS, settings.bandit_discount)
        # Virtuele positie per strategie, met dezelfde regels als echte trades:
        # richting (+1, 0, -1), grootte (x eigen geld), stop-loss koers en afkoelen na een stop.
        self.virt = {k: 0 for k in KEYS}
        self.vsize = {k: 0.0 for k in KEYS}
        self.vstop = {k: None for k in KEYS}
        self.vcool = {k: -1 for k in KEYS}
        self.vdist = {k: None for k in KEYS}      # stop-afstand bij openen (voor de trailing stop)
        self.virt_cost = {k: 0.0 for k in KEYS}
        self.stop_dist = None                      # huidige stop-afstand (op basis van beweeglijkheid)
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
        self.book = None                           # RiskBook: totaalrisico over alle bots
        self.last_f = None                         # laatst bekende funding rate
        self.daily = deque(maxlen=max(1, settings.trend_days))  # slotkoersen per dag
        self.cur_day = None
        self.day_close = None
        self.trend = 0                             # +1 boven, -1 onder het daggemiddelde, 0 onbekend

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

        if k.get("f") is not None:
            self.last_f = k["f"]
        self._update_trend(k)
        fund, signed = self._funding_rate()
        if trade:
            self._check_exits(k["o"], k["h"], k["l"], k["t"])
            pf.charge_funding(c, fund, signed)

        if self.prev_close:
            self.bandit.update(self._virtual_rewards(k))
        self.virt_cost = {a: 0.0 for a in KEYS}
        self.prev_close = c

        feats = self.engine.update(k, ref)
        if feats is None:
            if trade:
                self._record(k["t"], c)
            return None

        threshold = 2 * self.s.cost  # beweging moet in- en uitstapkosten dekken
        while self.pending and self.pending[0][0] + self.s.horizon <= self.index:
            _, x_old, c_old = self.pending.popleft()
            move = math.log(c / c_old)
            self.model_up.update(x_old, 1 if move > threshold else 0)
            self.model_down.update(x_old, 1 if move < -threshold else 0)

        x = feats["x"]
        self.model_up.observe(x)
        self.model_down.observe(x)
        ready = min(self.model_up.updates, self.model_down.updates) >= self.s.min_model_updates
        self.p = (self.model_up.predict(x), self.model_down.predict(x)) if ready else None
        self.pending.append((self.index, x, c))
        base = (self.model_up.base_rate, self.model_down.base_rate)

        self.stop_dist = self.s.stop_distance(feats["ind"]["vol48"])
        size = self.s.size_for(self.stop_dist)
        for a in KEYS:
            old = self.virt[a]
            new = STRATEGIES[a][1](feats["ind"], old, self.p, base)
            if not self.s.allow_short:
                new = max(new, 0)
            if self.s.trend_days and new * self.trend <= 0:   # alleen mee met de dagtrend
                new = 0
            if self.index < self.vcool[a]:      # afkoelen na een virtuele stop-loss
                new = 0
            if new != old:
                self.virt_cost[a] = self.s.cost * (self.vsize[a] * abs(old) + size * abs(new))
                self.virt[a] = new
                self.vsize[a] = size if new else 0.0
                self.vstop[a] = c * (1 - new * self.stop_dist) if new else None
                self.vdist[a] = self.stop_dist if new else None
            elif new and self.s.trailing_stop:  # trailing stop voor de virtuele positie
                trail = c * (1 - new * self.vdist[a])
                self.vstop[a] = max(self.vstop[a], trail) if new > 0 else min(self.vstop[a], trail)

        if self.active is None or self.index - self.last_decision >= self.s.decision_every:
            self._choose()

        if trade:
            if self.s.trailing_stop:
                pf.trail(c)
            self._trade(k)
            self._record(k["t"], c)
        return feats

    def _update_trend(self, k):
        """Dagtrend: staat de koers boven het gemiddelde van de laatste `trend_days` dagslotkoersen?"""
        day = k["t"] // 86_400_000
        if self.cur_day is not None and day != self.cur_day:
            self.daily.append(self.day_close)
        self.cur_day, self.day_close = day, k["c"]
        if self.s.trend_days and len(self.daily) >= self.s.trend_days:
            avg = sum(self.daily) / len(self.daily)
            self.trend = 1 if k["c"] > avg else -1
        else:
            self.trend = 0

    def _funding_rate(self):
        """(rate per candle, signed). Echte rate als die bekend is, anders de voorzichtige schatting."""
        if self.s.real_funding and self.last_f is not None:
            return self.last_f * self.s.interval_ms / 28_800_000, True
        return self.s.funding_per_candle, False

    def open_risk(self):
        """Wat deze bot vanaf de huidige koers verliest als de stop-loss geraakt wordt (in $, minstens 0)."""
        pf = self.portfolio
        if pf.qty == 0 or pf.stop is None or not self.last_price:
            return 0.0
        d = 1 if pf.qty > 0 else -1
        exit_price = pf.stop * (1 - self.s.slippage * d)
        return max(0.0, pf.qty * (self.last_price - exit_price)) + abs(pf.qty) * exit_price * self.s.fee_rate

    def _virtual_rewards(self, k):
        """Wat elke strategie deze candle verdiende, in bps van haar geld, na kosten, funding en stop-loss.

        Precies dezelfde regels als de echte trades: raakt de koers de stop, dan sluit de
        virtuele positie op de stop (of op de open bij een gat) en volgt afkoeltijd.
        """
        p0, c = self.prev_close, k["c"]
        fund, signed = self._funding_rate()
        rewards = {}
        for a in KEYS:
            r = -self.virt_cost[a]
            d = self.virt[a]
            if d:
                size, stop = self.vsize[a], self.vstop[a]
                worst = k["l"] if d > 0 else k["h"]
                if (k["o"] - stop) * d <= 0:
                    exit_price = k["o"]
                elif (worst - stop) * d <= 0:
                    exit_price = stop
                else:
                    exit_price = None
                end = c if exit_price is None else exit_price
                r += size * (d * (end / p0 - 1) - (d * fund if signed else fund))
                if exit_price is not None:
                    r -= size * self.s.cost
                    self.virt[a], self.vsize[a], self.vstop[a] = 0, 0.0, None
                    self.vcool[a] = self.index + self.s.stop_cooldown
            rewards[a] = 1e4 * r
        return rewards

    def _choose(self):
        """Kies een strategie. Wissel alleen als de verwachte winst de wisselkosten dekt."""
        self.last_decision = self.index
        pick = self.bandit.choose(self.s.confidence)
        if self.active is None or pick == self.active:
            self.active = pick
            return
        switch_bps = 1e4 * self.s.cost * abs(self.virt[pick] * self.vsize[pick]
                                             - self.virt[self.active] * self.vsize[self.active])
        gain_bps = self.bandit.posterior(pick)[0] - self.bandit.posterior(self.active)[0]
        if gain_bps * self.s.decision_every > switch_bps:
            self.active = pick

    # ---------------------------------------------------------------- traden
    def _trade(self, k):
        """Eén positie tegelijk: openen, aanhouden of sluiten. Nooit bijkopen of half afbouwen."""
        pf, price = self.portfolio, k["c"]
        if self.start_price is None:
            self.start_price, self.start_t = price, k["t"]
        self.risk.on_candle(k["t"], pf.equity(price))
        self.active_counts[self.active] += 1
        want, self.risk_note = self.risk.filter(self.virt[self.active], self.index)
        want = (want > 0) - (want < 0)
        have = (pf.qty > 0) - (pf.qty < 0)
        reason = self.risk_note or STRATEGIES[self.active][0]
        if have and want != have:
            self._close(price, k["t"], reason)
            have = 0
        if want and not have:
            self._open(want, price, k["t"], reason)

    def _open(self, direction, price, t, reason):
        pf, dist = self.portfolio, self.stop_dist
        size = self.s.size_for(dist)
        if self.book is not None and self.s.max_total_risk:
            wanted = size * pf.equity(price) * (dist + 2 * self.s.cost)   # risico van deze trade in $
            allowed = self.book.available(self)
            if allowed < wanted:
                size *= allowed / wanted
                reason += " (verkleind: totaalrisico)"
            if size * pf.equity(price) < 10:   # te klein om te openen
                self.risk_note = "totaalrisico vol"
                return None
        return pf.open(direction, size, price, t, reason, self.active, self.s.fee_rate, self.s.slippage, dist)

    def _close(self, price, t, reason):
        self.portfolio.close(price, t, reason, self.active, self.s.fee_rate, self.s.slippage)

    def _check_exits(self, open_, high, low, t):
        """Stop-loss en liquidatie. De koers loopt van open naar het slechtste punt; wat eerst geraakt wordt telt."""
        pf = self.portfolio
        if pf.qty == 0:
            return
        d = 1 if pf.qty > 0 else -1
        worst = low if d > 0 else high
        hit = lambda level, price: (price - level) * d <= 0   # koers voorbij niveau, tegen de positie in
        sp = pf.stop
        liq = pf.liquidation_price(self.s.maintenance_margin)
        mm = self.s.maintenance_margin
        if liq is not None and hit(liq, sp):     # positie zo groot dat liquidatie eerder komt
            sp = None
        if liq is not None and hit(liq, open_):
            pf.liquidate(open_, t, self.active, mm)
        elif sp is not None and hit(sp, open_):
            self._close(open_, t, "stop-loss")
            self.risk.trigger_stop(self.index)
        elif sp is not None and hit(sp, worst):
            self._close(sp, t, "stop-loss")
            self.risk.trigger_stop(self.index)
        elif liq is not None and hit(liq, worst):
            pf.liquidate(liq, t, self.active, mm)

    def _loss_at_stop(self):
        """Wat de open positie kost (t.o.v. de instap) als de stop-loss geraakt wordt."""
        pf = self.portfolio
        if pf.qty == 0:
            return 0.0
        d = 1 if pf.qty > 0 else -1
        exit_price = pf.stop * (1 - self.s.slippage * d)
        return -pf.qty * (exit_price - pf.entry) + abs(pf.qty) * exit_price * self.s.fee_rate

    def tick(self, price, t):
        """Live koers tussen candles door: stop-loss en liquidatie direct uitvoeren."""
        self.last_price = price
        self._check_exits(price, price, price, t)

    def pause(self, t):
        self.risk.paused = True
        if self.portfolio.qty != 0 and self.last_price:
            self._close(self.last_price, t, "handmatig gepauzeerd")

    def resume(self):
        self.risk.resume(self.portfolio.equity(self.last_price or 0))

    def _record(self, t, price):
        eq = self.portfolio.equity(price)
        self.history.append((t, eq, price))
        self.peak_equity = max(self.peak_equity, eq)
        if self.peak_equity > 0:
            self.max_dd = max(self.max_dd, 1 - eq / self.peak_equity)

    # ---------------------------------------------------------------- status
    def _model_status(self, m, i):
        return {"updates": m.updates, "p": self.p[i] if self.p else None, "base_rate": m.base_rate,
                "metrics": m.metrics(), "top_weights": m.top_weights(self.engine.names)}

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
            "side": pf.side,
            "opened": pf.opened_t,
            "wins": pf.wins,
            "losses": pf.losses,
            "entry": pf.entry,
            "leverage": self.s.leverage,
            "allow_short": self.s.allow_short,
            "risk_per_trade": self.s.risk_per_trade,
            "loss_at_stop": self._loss_at_stop(),
            "exposure": pf.exposure(price) if price else 0.0,
            "notional": pf.notional(price),
            "unrealized": pf.unrealized(price),
            "unrealized_pct": (price / pf.entry - 1) * 100 if pf.entry else 0.0,
            "stop_price": pf.stop,
            "stop_distance_now": self.stop_dist,
            "trend": self.trend,
            "trend_days": self.s.trend_days,
            "trailing_stop": self.s.trailing_stop,
            "funding_rate": self.last_f,
            "open_risk": self.open_risk(),
            "total_risk_pct": self.book.used_pct() if self.book else None,
            "max_total_risk": self.s.max_total_risk,
            "size_now": self.s.size_for(self.stop_dist) if self.stop_dist else None,
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
                "ready": self.p is not None,
                "up": self._model_status(self.model_up, 0),
                "down": self._model_status(self.model_down, 1),
            },
            "risk": {"state": state, "note": self.risk_note, "paused": self.risk.paused,
                     "killed": self.risk.killed},
            "trades": list(pf.trades)[-25:][::-1],
            "chart": chart,
        }

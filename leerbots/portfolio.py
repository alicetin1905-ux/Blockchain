"""Nep-portemonnee (paper trading) met hefboom, zoals een Binance USDT-futures account.

- balance: je inleg plus gerealiseerde winst/verlies, min fees en funding
- qty/entry: de open long-positie in de munt
- equity: balance plus open winst/verlies
- exposure: positiegrootte gedeeld door equity (1.0 = 1x, 5.0 = 5x hefboom)
Met hefboom 1 gedraagt dit zich als gewoon kopen en verkopen.
"""
from collections import deque


class Portfolio:
    def __init__(self, cash):
        self.start = cash
        self.balance = cash
        self.qty = 0.0
        self.entry = 0.0
        self.fees = 0.0
        self.funding = 0.0
        self.n_trades = 0
        self.liquidations = 0
        self.trades = deque(maxlen=300)

    def equity(self, price):
        return self.balance + self.qty * (price - self.entry)

    def notional(self, price):
        return self.qty * price

    def exposure(self, price):
        eq = self.equity(price)
        return self.qty * price / eq if eq > 0 else 0.0

    def unrealized(self, price):
        return self.qty * (price - self.entry)

    def liquidation_price(self, mm):
        """Koers waarop equity gelijk is aan de onderhoudsmarge (None = kan niet geliquideerd worden)."""
        if self.qty <= 0:
            return None
        p = (self.qty * self.entry - self.balance) / (self.qty * (1 - mm))
        return p if p > 0 else None

    def _log(self, trade):
        self.n_trades += 1
        self.trades.append(trade)
        return trade

    def rebalance(self, target, price, t, reason, strategy, fee, slip):
        """Breng de blootstelling naar `target` (0 = geen positie, 5 = 5x). Geeft de trade terug of None."""
        eq = self.equity(price)
        if eq <= 0:
            return None
        cur = self.exposure(price)
        if target > cur:
            add = (target - cur) * eq
            if add < 1:
                return None
            fill = price * (1 + slip)
            qty = add / fill
            paid = add * fee
            self.entry = (self.entry * self.qty + fill * qty) / (self.qty + qty)
            self.qty += qty
            self.balance -= paid
            self.fees += paid
            return self._log({"t": t, "side": "KOOP", "price": fill, "qty": qty, "usd": add,
                              "fee": paid, "reason": reason, "strategy": strategy, "pnl": None})
        if target < cur and self.qty > 0:
            qty = self.qty if target <= 0 else min(self.qty, (cur - target) * eq / price)
            fill = price * (1 - slip)
            gross = qty * fill
            paid = gross * fee
            pnl = qty * (fill - self.entry) - paid
            self.balance += pnl
            self.fees += paid
            self.qty -= qty
            if self.qty * price < 1e-6:
                self.qty, self.entry = 0.0, 0.0
            return self._log({"t": t, "side": "VERKOOP", "price": fill, "qty": qty, "usd": gross,
                              "fee": paid, "reason": reason, "strategy": strategy, "pnl": pnl})
        return None

    def charge_funding(self, price, rate):
        if self.qty > 0 and rate:
            cost = self.qty * price * rate
            self.balance -= cost
            self.funding += cost

    def liquidate(self, price, t, strategy, mm):
        """Gedwongen sluiting door de beurs. De resterende marge gaat verloren."""
        eq = self.equity(price)
        pnl = eq - self.balance - self.qty * price * mm
        trade = {"t": t, "side": "LIQUIDATIE", "price": price, "qty": self.qty, "usd": self.qty * price,
                 "fee": 0.0, "reason": "geliquideerd", "strategy": strategy, "pnl": pnl}
        self.balance = max(0.0, eq - self.qty * price * mm)
        self.qty, self.entry = 0.0, 0.0
        self.liquidations += 1
        return self._log(trade)

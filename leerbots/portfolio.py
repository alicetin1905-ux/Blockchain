"""Nep-portemonnee (paper trading) met fees en slippage."""
from collections import deque


class Portfolio:
    def __init__(self, cash):
        self.start = cash
        self.cash = cash
        self.qty = 0.0
        self.entry = 0.0
        self.fees = 0.0
        self.n_trades = 0
        self.trades = deque(maxlen=300)

    def equity(self, price):
        return self.cash + self.qty * price

    def exposure(self, price):
        eq = self.equity(price)
        return self.qty * price / eq if eq > 0 else 0.0

    def rebalance(self, target, price, t, reason, strategy, fee, slip):
        """Breng de blootstelling naar `target` (0..1). Geeft de trade terug of None."""
        eq = self.equity(price)
        cur = self.exposure(price)
        if target > cur:
            usd = min((target - cur) * eq, self.cash)
            if usd < 1:
                return None
            fill = price * (1 + slip)
            qty = usd * (1 - fee) / fill
            self.entry = (self.entry * self.qty + fill * qty) / (self.qty + qty)
            self.qty += qty
            self.cash -= usd
            paid = usd * fee
            trade = {"t": t, "side": "KOOP", "price": fill, "qty": qty, "usd": usd,
                     "fee": paid, "reason": reason, "strategy": strategy, "pnl": None}
        elif target < cur and self.qty > 0:
            qty = self.qty if target <= 0 else min(self.qty, (cur - target) * eq / price)
            fill = price * (1 - slip)
            gross = qty * fill
            paid = gross * fee
            pnl = gross - paid - qty * self.entry
            self.cash += gross - paid
            self.qty -= qty
            if self.qty * price < 1e-6:
                self.qty, self.entry = 0.0, 0.0
            trade = {"t": t, "side": "VERKOOP", "price": fill, "qty": qty, "usd": gross,
                     "fee": paid, "reason": reason, "strategy": strategy, "pnl": pnl}
        else:
            return None
        self.fees += paid
        self.n_trades += 1
        self.trades.append(trade)
        return trade

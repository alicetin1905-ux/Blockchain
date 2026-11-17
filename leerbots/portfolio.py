"""Nep-portemonnee (paper trading) zoals een Binance USDT-futures account.

- Eén positie tegelijk: long (qty > 0) of short (qty < 0). Geen bijkopen of
  gedeeltelijk afbouwen: een positie wordt in één keer geopend en in één keer gesloten.
- balance: inleg plus gerealiseerde winst/verlies, min fees en funding
- equity: balance plus open winst/verlies
- exposure: positiegrootte / equity, met teken (+4.7 = long 4.7x, -4.7 = short 4.7x)
"""
from collections import deque


def side_of(qty):
    return "LONG" if qty > 0 else "SHORT" if qty < 0 else None


class Portfolio:
    def __init__(self, cash):
        self.start = cash
        self.balance = cash
        self.qty = 0.0
        self.entry = 0.0
        self.opened_t = None
        self.fees = 0.0
        self.funding = 0.0
        self.n_trades = 0
        self.liquidations = 0
        self.wins = 0
        self.losses = 0
        self.trades = deque(maxlen=300)

    @property
    def side(self):
        return side_of(self.qty)

    def equity(self, price):
        return self.balance + self.qty * (price - self.entry)

    def notional(self, price):
        return abs(self.qty) * price

    def exposure(self, price):
        eq = self.equity(price)
        return self.qty * price / eq if eq > 0 else 0.0

    def unrealized(self, price):
        return self.qty * (price - self.entry)

    def liquidation_price(self, mm):
        """Koers waarop equity gelijk is aan de onderhoudsmarge (None = geen positie of onmogelijk)."""
        if self.qty == 0:
            return None
        p = (self.qty * self.entry - self.balance) / (self.qty - mm * abs(self.qty))
        return p if p > 0 else None

    def _log(self, trade):
        self.n_trades += 1
        self.trades.append(trade)
        return trade

    def open(self, direction, size, price, t, reason, strategy, fee, slip):
        """Open een positie van `size` x equity. direction: +1 long, -1 short."""
        if self.qty != 0 or direction == 0:
            return None
        eq = self.equity(price)
        notional = size * eq
        if eq <= 0 or notional < 1:
            return None
        fill = price * (1 + slip * direction)       # slippage altijd in je nadeel
        paid = notional * fee
        self.qty = direction * notional / fill
        self.entry = fill
        self.opened_t = t
        self.balance -= paid
        self.fees += paid
        self._open_fee = paid
        return self._log({"t": t, "side": "OPEN " + self.side, "price": fill, "qty": abs(self.qty),
                          "usd": notional, "fee": paid, "reason": reason, "strategy": strategy, "pnl": None})

    def close(self, price, t, reason, strategy, fee, slip):
        if self.qty == 0:
            return None
        side = self.side
        direction = 1 if self.qty > 0 else -1
        fill = price * (1 - slip * direction)
        gross = abs(self.qty) * fill
        paid = gross * fee
        pnl = self.qty * (fill - self.entry) - paid
        self.balance += pnl
        self.fees += paid
        net = pnl - getattr(self, "_open_fee", 0.0)   # resultaat van de hele trade incl. openingsfee
        self.wins += net > 0
        self.losses += net <= 0
        self.qty, self.entry, self.opened_t = 0.0, 0.0, None
        return self._log({"t": t, "side": "SLUIT " + side, "price": fill, "qty": gross / fill, "usd": gross,
                          "fee": paid, "reason": reason, "strategy": strategy, "pnl": net})

    def charge_funding(self, price, rate):
        """Funding over de positiegrootte. Voorzichtig gerekend: long én short betalen."""
        if self.qty != 0 and rate:
            cost = abs(self.qty) * price * rate
            self.balance -= cost
            self.funding += cost

    def liquidate(self, price, t, strategy, mm):
        """Gedwongen sluiting door de beurs. De resterende marge gaat verloren."""
        side = self.side
        eq = self.equity(price)
        after = max(0.0, eq - abs(self.qty) * price * mm)
        trade = {"t": t, "side": "LIQUIDATIE " + side, "price": price, "qty": abs(self.qty),
                 "usd": abs(self.qty) * price, "fee": 0.0, "reason": "geliquideerd",
                 "strategy": strategy, "pnl": after - self.balance - getattr(self, "_open_fee", 0.0)}
        self.balance = after
        self.qty, self.entry, self.opened_t = 0.0, 0.0, None
        self.liquidations += 1
        self.losses += 1
        return self._log(trade)

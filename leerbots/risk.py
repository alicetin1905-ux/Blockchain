"""Vaste risicoregels. Staan buiten het lerende deel, dus de bot kan ze niet wegleren."""
import datetime as dt


class RiskManager:
    def __init__(self, s):
        self.s = s
        self.paused = False
        self.killed = False
        self.cooldown_until = -1
        self.day = None
        self.day_start = None
        self.day_blocked = False
        self.peak = None

    def on_candle(self, t, equity):
        day = dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).date().isoformat()
        if day != self.day:
            self.day, self.day_start, self.day_blocked = day, equity, False
        self.peak = equity if self.peak is None else max(self.peak, equity)
        if equity <= 0:
            self.killed = True
        if equity < self.day_start * (1 - self.s.daily_loss_limit):
            self.day_blocked = True
        if equity < self.peak * (1 - self.s.max_drawdown):
            self.killed = True

    def filter(self, target, index):
        """Geeft (toegestane blootstelling, reden) terug."""
        if self.paused:
            return 0.0, "handmatig gepauzeerd"
        if self.killed:
            return 0.0, f"max drawdown {self.s.max_drawdown:.0%} bereikt"
        if self.day_blocked:
            return 0.0, f"daglimiet {self.s.daily_loss_limit:.0%} verlies bereikt"
        if index < self.cooldown_until:
            return 0.0, "afkoelen na stop-loss"
        return target, ""

    def trigger_stop(self, index):
        self.cooldown_until = index + self.s.stop_cooldown

    def resume(self, equity):
        self.paused = False
        self.killed = False
        self.peak = equity


class RiskBook:
    """Bewaakt het open risico van alle bots samen.

    BTC, ETH en SOL bewegen meestal samen. Drie posities van elk 5% risico zijn dan
    eigenlijk één weddenschap van 15%. Een nieuwe positie wordt verkleind als het totale
    open risico anders boven `max_total_risk` van al het geld zou komen.
    """

    def __init__(self, bots, max_total_risk):
        self.bots = bots
        self.cap = max_total_risk
        for b in bots.values():
            b.book = self

    def available(self, me):
        """Hoeveel risico (in $) `me` nog mag nemen."""
        total = sum(b.portfolio.equity(b.last_price or 0.0) for b in self.bots.values())
        used = sum(b.open_risk() for b in self.bots.values() if b is not me)
        return max(0.0, self.cap * total - used)

    def used_pct(self):
        total = sum(b.portfolio.equity(b.last_price or 0.0) for b in self.bots.values())
        used = sum(b.open_risk() for b in self.bots.values())
        return used / total * 100 if total > 0 else 0.0

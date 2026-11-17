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

    def stop_price(self, entry):
        return entry * (1 - self.s.stop_loss) if entry > 0 else None

    def trigger_stop(self, index):
        self.cooldown_until = index + self.s.stop_cooldown

    def resume(self, equity):
        self.paused = False
        self.killed = False
        self.peak = equity

"""Zet candles om in signalen (features) voor het model en de strategieën.

Alles wordt per candle bijgewerkt, zonder naar de toekomst te kijken.
"""
import math
from collections import deque

BASE_NAMES = [
    "r1", "r3", "r12", "r48",          # koersverandering over 1, 3, 12, 48 candles
    "vol12", "vol48",                 # beweeglijkheid
    "rsi", "d_ema20", "d_ema50", "ema_spread",
    "vol_z", "body", "range",
    "hour_sin", "hour_cos",
]
REF_NAMES = ["btc_r3", "btc_r12"]
FUND_NAMES = ["fund", "fund_avg"]     # funding rate nu en gemiddeld (in bps)
WARMUP = 50


def _std(values):
    n = len(values)
    if n < 2:
        return 0.0
    m = sum(values) / n
    return math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1))


class FeatureEngine:
    def __init__(self, use_ref=False, use_funding=False):
        self.use_ref = use_ref
        self.use_funding = use_funding
        self.funds = deque(maxlen=72)
        self.last_f = None
        self.closes = deque(maxlen=60)
        self.highs = deque(maxlen=48)   # vorige 48 candles (zonder de huidige)
        self.lows = deque(maxlen=48)    # vorige 48 candles
        self.vols = deque(maxlen=48)
        self.rets = deque(maxlen=48)
        self.ema20 = None
        self.ema50 = None
        self.avg_gain = None
        self.avg_loss = None
        self._rsi_seed = []
        self.count = 0

    @property
    def names(self):
        return BASE_NAMES + (REF_NAMES if self.use_ref else []) + (FUND_NAMES if self.use_funding else [])

    def _rsi_update(self, change):
        g, l = max(change, 0.0), max(-change, 0.0)
        if self.avg_gain is None:
            self._rsi_seed.append((g, l))
            if len(self._rsi_seed) == 14:
                self.avg_gain = sum(x[0] for x in self._rsi_seed) / 14
                self.avg_loss = sum(x[1] for x in self._rsi_seed) / 14
        else:
            self.avg_gain = (self.avg_gain * 13 + g) / 14
            self.avg_loss = (self.avg_loss * 13 + l) / 14

    def update(self, k, ref=None):
        """Verwerk een afgesloten candle. Geeft None terug tijdens het opwarmen."""
        c, o, h, l, v = k["c"], k["o"], k["h"], k["l"], k["v"]
        if k.get("f") is not None:
            self.last_f = k["f"]
        if self.last_f is not None:
            self.funds.append(self.last_f)
        prev = self.closes[-1] if self.closes else None

        high48 = max(self.highs) if len(self.highs) == 48 else None
        low48 = min(self.lows) if len(self.lows) == 48 else None
        high12 = max(list(self.highs)[-12:]) if len(self.highs) >= 12 else None
        low12 = min(list(self.lows)[-12:]) if len(self.lows) >= 12 else None
        vol_mean = sum(self.vols) / len(self.vols) if self.vols else 0.0
        vol_sd = _std(self.vols)

        r1 = math.log(c / prev) if prev else 0.0
        if prev:
            self._rsi_update(c - prev)
            self.rets.append(r1)

        def ret(n):
            return math.log(c / self.closes[-n]) if len(self.closes) >= n else 0.0

        r3, r12, r48 = ret(3), ret(12), ret(48)
        self.ema20 = c if self.ema20 is None else self.ema20 + (2 / 21) * (c - self.ema20)
        self.ema50 = c if self.ema50 is None else self.ema50 + (2 / 51) * (c - self.ema50)

        self.closes.append(c)
        self.highs.append(h)
        self.lows.append(l)
        self.vols.append(v)
        self.count += 1

        if self.count < WARMUP or self.avg_gain is None or high48 is None or low48 is None:
            return None

        rsi = 100.0 if self.avg_loss == 0 else 100 - 100 / (1 + self.avg_gain / self.avg_loss)
        rets = list(self.rets)
        angle = (k["t"] / 1000 % 86400) / 86400 * 2 * math.pi
        x = [
            r1, r3, r12, r48,
            _std(rets[-12:]), _std(rets),
            (rsi - 50) / 50, c / self.ema20 - 1, c / self.ema50 - 1, self.ema20 / self.ema50 - 1,
            (v - vol_mean) / vol_sd if vol_sd > 0 else 0.0,
            (c - o) / o, (h - l) / o,
            math.sin(angle), math.cos(angle),
        ]
        if self.use_ref:
            x += [ref["r3"], ref["r12"]] if ref else [0.0, 0.0]
        if self.use_funding:
            f = self.last_f or 0.0
            x += [f * 1e4, (sum(self.funds) / len(self.funds) * 1e4) if self.funds else 0.0]
        ind = {"close": c, "rsi": rsi, "ema20": self.ema20, "ema50": self.ema50, "vol48": x[5],
               "high48": high48, "low48": low48, "high12": high12, "low12": low12}
        return {"t": k["t"], "x": x, "ind": ind, "r3": r3, "r12": r12}

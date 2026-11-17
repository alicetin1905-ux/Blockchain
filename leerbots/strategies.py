"""Strategieën. Elke strategie geeft een richting: +1 (long), -1 (short) of 0 (geen positie).

Hoe groot de positie wordt, bepaalt het risico per trade, niet de strategie.
Argumenten: ind = indicatoren, prev = vorige richting van deze strategie,
p = (kans op stijging, kans op daling) uit de modellen, of None zolang ze nog te weinig weten,
base = (normale kans op stijging, normale kans op daling).
"""


def trend(ind, prev, p, base):
    up = ind["ema20"] > ind["ema50"]
    if prev > 0:
        return 1 if up else 0
    if prev < 0:
        return -1 if not up else 0
    if up and ind["close"] > ind["ema20"]:
        return 1
    if not up and ind["close"] < ind["ema20"]:
        return -1
    return 0


def reversion(ind, prev, p, base):
    rsi = ind["rsi"]
    if prev > 0:
        return 0 if rsi > 55 else 1
    if prev < 0:
        return 0 if rsi < 45 else -1
    if rsi < 30:
        return 1
    if rsi > 70:
        return -1
    return 0


def breakout(ind, prev, p, base):
    c = ind["close"]
    if c > ind["high48"]:
        return 1
    if c < ind["low48"]:
        return -1
    if prev > 0 and c < ind["low12"]:
        return 0
    if prev < 0 and c > ind["high12"]:
        return 0
    return prev


def model(ind, prev, p, base):
    if p is None:
        return 0
    (pu, pd), (bu, bd) = p, base
    up, down = pu > bu + 0.10, pd > bd + 0.10
    if up and not down:
        return 1
    if down and not up:
        return -1
    if prev > 0 and pu >= bu:
        return 1
    if prev < 0 and pd >= bd:
        return -1
    return 0


def cash(ind, prev, p, base):
    return 0


STRATEGIES = {
    "trend": ("Trend volgen", trend),
    "reversion": ("Terugveren", reversion),
    "breakout": ("Uitbraak", breakout),
    "model": ("Model (ML)", model),
    "cash": ("Cash", cash),
}
KEYS = list(STRATEGIES)

"""Strategieën. Elke strategie geeft een doel-blootstelling tussen 0 (cash) en 1 (alles in de munt).

Alleen long (kopen en verkopen), geen shorten en geen hefboom.
Argumenten: ind = indicatoren, prev = vorige blootstelling van deze strategie,
p = kans uit het model (None zolang het model nog niet genoeg weet),
base = hoe vaak de koers historisch genoeg steeg.
"""


def trend(ind, prev, p, base):
    if prev > 0:
        return 1.0 if ind["ema20"] > ind["ema50"] else 0.0
    return 1.0 if ind["ema20"] > ind["ema50"] and ind["close"] > ind["ema20"] else 0.0


def reversion(ind, prev, p, base):
    if prev > 0:
        return 0.0 if ind["rsi"] > 55 else prev
    return 1.0 if ind["rsi"] < 30 else 0.0


def breakout(ind, prev, p, base):
    if ind["close"] > ind["high48"]:
        return 1.0
    if prev > 0 and ind["close"] < ind["low12"]:
        return 0.0
    return prev


def model(ind, prev, p, base):
    if p is None:
        return 0.0
    if p > base + 0.10:
        return 1.0
    if p < base:
        return 0.0
    return prev


def cash(ind, prev, p, base):
    return 0.0


STRATEGIES = {
    "trend": ("Trend volgen", trend),
    "reversion": ("Terugveren", reversion),
    "breakout": ("Uitbraak", breakout),
    "model": ("Model (ML)", model),
    "cash": ("Cash", cash),
}
KEYS = list(STRATEGIES)

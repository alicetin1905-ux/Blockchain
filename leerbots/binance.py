"""Publieke Binance-marktdata. Geen API-sleutels nodig."""
import json
import time
import urllib.parse
import urllib.request

# data-api.binance.vision is Binance's eigen adres voor alleen marktdata.
# api.binance.com is in sommige landen/datacenters geblokkeerd (HTTP 451).
HOSTS = ["https://data-api.binance.vision", "https://api.binance.com"]


class BinanceError(RuntimeError):
    pass


def _get(path, params):
    query = urllib.parse.urlencode(params)
    last = None
    for host in HOSTS:
        url = f"{host}{path}?{query}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "leerbots/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # probeer het volgende adres
            last = e
    raise BinanceError(f"Binance niet bereikbaar: {last}")


def _row(k):
    return {"t": int(k[0]), "o": float(k[1]), "h": float(k[2]), "l": float(k[3]),
            "c": float(k[4]), "v": float(k[5]), "ct": int(k[6])}


def klines(symbol, interval, limit=500, end_time=None):
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if end_time is not None:
        params["endTime"] = end_time
    return [_row(k) for k in _get("/api/v3/klines", params)]


def closed_klines(symbol, interval, limit=3):
    """Alleen afgesloten candles (de lopende candle telt niet)."""
    now = int(time.time() * 1000)
    return [k for k in klines(symbol, interval, limit) if k["ct"] < now]


def history(symbol, interval, n):
    """De laatste n afgesloten candles, in blokken van 1000 opgehaald."""
    out = []
    end = None
    while len(out) < n:
        batch = klines(symbol, interval, min(1000, n - len(out) + 1), end)
        if not batch:
            break
        out = batch + out
        end = batch[0]["t"] - 1
        if len(batch) < 2:
            break
    now = int(time.time() * 1000)
    seen, uniq = set(), []
    for k in out:
        if k["t"] not in seen and k["ct"] < now:
            seen.add(k["t"])
            uniq.append(k)
    uniq.sort(key=lambda k: k["t"])
    return uniq[-n:]


def prices(symbols):
    data = _get("/api/v3/ticker/price", {"symbols": json.dumps(symbols, separators=(",", ":"))})
    return {d["symbol"]: float(d["price"]) for d in data}

"""Funding rates van Binance USDT-futures.

Funding is een kleine betaling tussen longs en shorts, elke 8 uur. Is de rate positief,
dan betalen longs aan shorts. Een hoge positieve rate betekent dat veel handelaren long
zitten met hefboom.

Geschiedenis komt uit Binance's maandarchieven (data.binance.vision), de laatste weken
uit de live API (fapi.binance.com). Die live API is in sommige landen en datacenters
geblokkeerd; dan wordt de laatst bekende rate gebruikt.
"""
import csv
import datetime as dt
import io
import json
import os
import urllib.error
import urllib.request
import zipfile

ARCHIVE = "https://data.binance.vision/data/futures/um/monthly/fundingRate/{s}/{s}-fundingRate-{y:04d}-{m:02d}.zip"
LIVE = "https://fapi.binance.com/fapi/v1/fundingRate?symbol={s}&limit={n}"
EIGHT_HOURS = 8 * 3_600_000


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "leerbots/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def month(symbol, year, mon):
    """Alle funding-momenten van één maand als [(tijd_ms, rate)]. Leeg als het archief (nog) niet bestaat."""
    try:
        raw = _get(ARCHIVE.format(s=symbol, y=year, m=mon))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        text = z.read(z.namelist()[0]).decode()
    rows = []
    for row in csv.reader(text.splitlines()):
        if not row or not row[0].isdigit():
            continue  # kopregel
        rows.append((int(row[0]), float(row[-1])))
    return rows


def _months(start_ms, end_ms):
    d = dt.datetime.fromtimestamp(start_ms / 1000, dt.timezone.utc).replace(day=1)
    end = dt.datetime.fromtimestamp(end_ms / 1000, dt.timezone.utc)
    while d <= end:
        yield d.year, d.month
        d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def history(symbol, start_ms, end_ms, cache_dir=None):
    """Funding tussen start en eind uit de maandarchieven, met een cache per afgesloten maand."""
    now = dt.datetime.now(dt.timezone.utc)
    out = []
    for y, m in _months(start_ms, end_ms):
        path = os.path.join(cache_dir, f"{symbol}-{y:04d}-{m:02d}.json") if cache_dir else None
        if path and os.path.exists(path):
            with open(path) as f:
                rows = [tuple(r) for r in json.load(f)]
        else:
            try:
                rows = month(symbol, y, m)
            except Exception:
                rows = []
            finished = (y, m) < (now.year, now.month)
            if path and rows and finished:
                os.makedirs(cache_dir, exist_ok=True)
                with open(path, "w") as f:
                    json.dump(rows, f)
        out += [r for r in rows if start_ms <= r[0] <= end_ms]
    return out


def recent(symbol, n=100):
    """De laatste funding-momenten uit de live API. Leeg als die niet bereikbaar is."""
    try:
        data = json.loads(_get(LIVE.format(s=symbol, n=n), timeout=10).decode())
        return [(int(d["fundingTime"]), float(d["fundingRate"])) for d in data]
    except Exception:
        return []


def merge(*series):
    seen = {}
    for s in series:
        for t, r in s:
            seen[t] = r
    return sorted(seen.items())


def attach(candles, funding):
    """Zet bij elke candle de laatst bekende funding rate (k["f"]), zonder vooruit te kijken.

    Een rate telt pas mee als hij vóór het sluiten van de candle bekend was.
    """
    j, last = 0, None
    funding = sorted(funding)
    for k in candles:
        while j < len(funding) and funding[j][0] <= k["ct"]:
            last = funding[j][1]
            j += 1
        if last is not None:
            k["f"] = last
    return candles

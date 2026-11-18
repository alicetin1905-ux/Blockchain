#!/usr/bin/env python3
"""Eenvoudige dagtrend-regel, ter vergelijking met de zelflerende bots.

Regel (vooraf vastgelegd): staat de dagslotkoers boven het gemiddelde van de laatste
N dagslotkoersen (standaard 50), dan long met 1x het eigen geld. Anders geen positie.
Eén beslissing per dag, op het slot. Geen model, geen strategiekiezer, geen stop-loss.

Kosten zoals bij de bots: futures-fee + slippage per trade en de echte funding rates.

    python3 simple_trend.py                   # 2020 tot nu, gemiddelde van 50 dagen
    python3 simple_trend.py --sma 20,50,100,200
"""
import argparse
import datetime as dt
import json
import os

from leerbots import binance, funding
from leerbots.config import NAMES, SYMBOLS, Settings

DAY = 86_400_000


def load_daily(start_year, cache_dir="data"):
    """Dagcandles vanaf een jaar vóór start_year (voor het gemiddelde) tot nu, met funding per dag."""
    start = int(dt.datetime(start_year - 1, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    end = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    os.makedirs(cache_dir, exist_ok=True)
    out = {}
    for sym in SYMBOLS:
        path = os.path.join(cache_dir, f"{sym}_1d_{start_year - 1}-now.json")
        if os.path.exists(path) and os.path.getmtime(path) > end / 1000 - 6 * 3600:
            with open(path) as f:
                out[sym] = json.load(f)
            continue
        ks = binance.history_range(sym, "1d", start, end)
        rates = funding.history(sym, start, end, cache_dir=os.path.join(cache_dir, "funding"))
        rates += funding.recent(sym)
        rates = funding.merge(rates)
        # funding die betaald wordt terwijl je de positie van dag d naar d+1 vasthoudt
        j = 0
        for k in ks:
            total, n = 0.0, 0
            while j < len(rates) and rates[j][0] <= k["ct"]:
                if rates[j][0] > k["ct"] - DAY:
                    total += rates[j][1]
                    n += 1
                j += 1
            k["fund"] = total if n else None   # som van de rates in deze dag (None = onbekend)
        with open(path, "w") as f:
            json.dump(ks, f)
        out[sym] = ks
    return out


def simulate(ks, sma, s, start_ms):
    """Dagelijkse resultaten [(dag_ms, rendement_bot, rendement_kopen_en_houden)] vanaf start_ms."""
    cost = s.fee_rate + s.slippage
    default_fund = s.funding_8h * 3
    closes, pos, rows, trades, pending = [], 0, [], 0, 0.0
    for i, k in enumerate(ks):
        if i > 0 and k["t"] >= start_ms and len(closes) >= sma:
            r = k["c"] / ks[i - 1]["c"] - 1
            fund = k["fund"] if k.get("fund") is not None else default_fund
            rows.append([k["t"], pos * (r - fund) - pending, r])
            pending = 0.0
        closes.append(k["c"])
        if k["t"] < start_ms or len(closes) < sma:
            continue                           # vóór de start of te weinig geschiedenis: geen positie
        new = 1 if k["c"] > sum(closes[-sma:]) / sma else 0
        if new != pos:                         # trade op het slot van vandaag
            if rows:
                rows[-1][1] -= cost
            else:
                pending += cost
            trades += 1
            pos = new
    return rows, trades


def stats(rows, col):
    eq, peak, dd = 1.0, 1.0, 0.0
    for row in rows:
        eq *= 1 + row[col]
        peak = max(peak, eq)
        dd = max(dd, 1 - eq / peak)
    return eq - 1, dd


def year_of(t):
    return dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).year


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="first", type=int, default=2020)
    ap.add_argument("--sma", default="50", help="lengte(s) van het gemiddelde in dagen, bijv. 20,50,100,200")
    args = ap.parse_args()
    s = Settings()
    data = load_daily(args.first)
    start = int(dt.datetime(args.first, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    last_year = year_of(max(ks[-1]["t"] for ks in data.values()))
    years = list(range(args.first, last_year + 1))

    for sma in [int(x) for x in args.sma.split(",")]:
        print("=" * 92)
        print(f"DAGTREND: long (1x) boven het {sma}-daags gemiddelde, anders cash."
              f" Fee {s.fee_rate:.2%} + slippage {s.slippage:.2%}, echte funding.")
        print("=" * 92)
        print(f"{'Jaar':8}" + "".join(f"{sym[:-4]:>22}" for sym in SYMBOLS) + f"{'Samen':>9}{'Kopen+houden':>14}")
        per_sym = {}
        for sym in SYMBOLS:
            rows, trades = simulate(data[sym], sma, s, start)
            per_sym[sym] = (rows, trades)
        for y in years:
            cells, bot_sum, hh_sum, n = [], 0.0, 0.0, 0
            for sym in SYMBOLS:
                yr = [r for r in per_sym[sym][0] if year_of(r[0]) == y]
                if not yr:
                    cells.append("geen data")
                    continue
                b, _ = stats(yr, 1)
                h, _ = stats(yr, 2)
                bot_sum, hh_sum, n = bot_sum + b, hh_sum + h, n + 1
                cells.append(f"{b * 100:+7.1f}% (hh {h * 100:+5.0f}%)")
            print(f"{y:<8}" + "".join(f"{c:>22}" for c in cells)
                  + f"{bot_sum / n * 100:+8.1f}%{hh_sum / n * 100:+13.1f}%")
        print("\nHele periode (doorlopend, zonder elk jaar opnieuw te beginnen):")
        for sym in SYMBOLS:
            rows, trades = per_sym[sym]
            b, bdd = stats(rows, 1)
            h, hdd = stats(rows, 2)
            first = dt.datetime.fromtimestamp(rows[0][0] / 1000, dt.timezone.utc).strftime("%b %Y")
            print(f"  {NAMES[sym]:9} vanaf {first}: regel {b * 100:+8.0f}% (grootste daling {bdd * 100:4.0f}%,"
                  f" {trades} trades)   kopen en houden {h * 100:+8.0f}% (grootste daling {hdd * 100:4.0f}%)")
        print()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Test de bots op echte Binance-geschiedenis.

De bots leren tijdens de test gewoon door en zien nooit de toekomst: elke
beslissing gebruikt alleen candles van vóór dat moment (walk-forward).

    python3 backtest.py                    # 180 dagen traden na 60 dagen opwarmen (1h-candles)
    python3 backtest.py --periods 4        # 4 aparte periodes van 180 dagen: is het resultaat stabiel?
    python3 backtest.py --risk 5 --leverage 3
    python3 backtest.py --from 2020 --to 2026   # elk kalenderjaar apart, met verse bots
    python3 backtest.py --no-short              # alleen long
    python3 backtest.py --offline          # gebruik eerder opgehaalde data in data/
"""
import argparse
import datetime as dt
import json
import os

from leerbots import binance
from leerbots.app import feed
from leerbots.bot import TradingBot
from leerbots.config import INTERVAL_MS, REFERENCE, SYMBOLS, Settings


def load_candles(interval, n, offline, cache_dir="data"):
    os.makedirs(cache_dir, exist_ok=True)
    out = {}
    for sym in SYMBOLS:
        path = os.path.join(cache_dir, f"{sym}_{interval}.json")
        if offline:
            with open(path) as f:
                data = json.load(f)
            if len(data) < n:
                raise SystemExit(f"{path} heeft {len(data)} candles, nodig: {n}. Draai eerst zonder --offline.")
            out[sym] = data[-n:]
        else:
            print(f"Ophalen {sym}: {n} candles...")
            out[sym] = binance.history(sym, interval, n)
            with open(path, "w") as f:
                json.dump(out[sym], f)
    return out


def run(candles, days, settings):
    bots = {sym: TradingBot(sym, settings, use_ref=sym != REFERENCE) for sym in SYMBOLS}
    ref = candles[REFERENCE]
    per_day = 86_400_000 // settings.interval_ms
    trade_from = ref[max(0, len(ref) - days * per_day)]["t"]
    feed(bots, candles, trade_from)
    return bots


def header(s):
    print("=" * 84)
    sides = "long en short" if s.allow_short else "alleen long"
    print(f"PAPER-TRADING BACKTEST {s.interval}, ${s.start_capital:,.0f} per bot, {sides}, 1 positie per munt,")
    print(f"max {s.leverage:g}x hefboom, max {s.risk_per_trade:.0%} risico per trade,"
          f" stop-loss {s.stop_vol_mult:g}x de dagbeweging ({s.stop_min:.0%}-{s.stop_max:.0%})")
    print(f"(fee {s.fee_rate:.2%} + slippage {s.slippage:.2%} per trade, funding {s.funding_8h:.2%}/8u meegerekend)")
    print("=" * 84)


def _skill(m):
    return f"{m['skill']:+.3f}" if m.get("samples") else "-"


def report(bots):
    header(next(iter(bots.values())).s)
    total_start = total_eq = 0.0
    for sym, bot in bots.items():
        st = bot.status()
        total_start += st["start_capital"]
        total_eq += st["equity"]
        closed = st["wins"] + st["losses"]
        print(f"\n{st['name']} ({sym})")
        print(f"  Resultaat bot     {st['pnl_pct']:+7.2f}%   (${st['pnl']:+,.2f})"
              + ("   NOODSTOP geraakt" if st["risk"]["killed"] else ""))
        print(f"  Kopen en houden   {st['buy_hold_pct']:+7.2f}%   (1x, zonder hefboom)")
        print(f"  Max drawdown      {st['max_drawdown_pct']:7.2f}%")
        print(f"  Trades            {closed:7d}    gewonnen {st['wins']}, verloren {st['losses']}"
              f"   fees ${st['fees']:,.2f}   funding ${st['funding']:,.2f}   liquidaties {st['liquidations']}")
        print(f"  Modelscore        stijging {_skill(st['model']['up']['metrics'])},"
              f" daling {_skill(st['model']['down']['metrics'])}  (>0 = beter dan gokken)")
        used = ", ".join(f"{s['label']} {s['used_pct']:.0f}%" for s in st["strategies"] if s["used_pct"] >= 0.5)
        print(f"  Gebruikt          {used}")
        best = ", ".join(f"{s['label']} {s['virtual_return_pct']:+.1f}%" for s in st["strategies"])
        print(f"  Virtueel (1x)     {best}  (hele periode incl. opwarmen)")
    print("\n" + "-" * 84)
    print(f"Totaal: ${total_start:,.0f} -> ${total_eq:,.2f}  ({(total_eq / total_start - 1) * 100:+.2f}%)")
    print("Let op: resultaten uit het verleden zeggen weinig over de toekomst.")


def run_periods(candles, periods, days, warmup_days, settings):
    """Test dezelfde instellingen op meerdere aparte periodes na elkaar."""
    per_day = 86_400_000 // settings.interval_ms
    warm, span = warmup_days * per_day, days * per_day
    header(settings)
    print(f"\n{'Periode':21}" + "".join(f"{s.replace('USDT', ''):>20}" for s in SYMBOLS) + f"{'Totaal':>10}")
    totals, stops = [], 0
    for i in range(periods):
        window = {s: ks[i * span:i * span + warm + span] for s, ks in candles.items()}
        bots = run(window, days, settings)
        ref = window[REFERENCE]
        fmt = lambda t: dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).strftime("%b %Y")
        row, eq = f"{fmt(ref[warm]['t'])} - {fmt(ref[-1]['t'])}", 0.0
        cells = []
        for sym in SYMBOLS:
            st = bots[sym].status()
            eq += st["equity"]
            stops += st["risk"]["killed"]
            cells.append(f"{st['pnl_pct']:+6.1f}% (hh {st['buy_hold_pct']:+4.0f}%)" + ("!" if st["risk"]["killed"] else " "))
        total = (eq / (len(SYMBOLS) * settings.start_capital) - 1) * 100
        totals.append(total)
        print(f"{row:21}" + "".join(f"{c:>20}" for c in cells) + f"{total:+9.1f}%")
    print(f"\nGemiddeld per periode: {sum(totals) / len(totals):+.1f}%   Noodstop geraakt: {stops} van "
          f"{periods * len(SYMBOLS)} keer")
    print("hh = kopen en houden (1x).  ! = noodstop geraakt (te ver onder de piek)")


def load_years(interval, first, last, warmup_days, offline, cache_dir="data"):
    """Candles van (1 januari `first` min opwarmtijd) tot eind `last` (of nu)."""
    start = int(dt.datetime(first, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000) - warmup_days * 86_400_000
    end = int(dt.datetime(last + 1, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    os.makedirs(cache_dir, exist_ok=True)
    out = {}
    for sym in SYMBOLS:
        path = os.path.join(cache_dir, f"{sym}_{interval}_{first}-{last}.json")
        if offline or os.path.exists(path):
            with open(path) as f:
                out[sym] = json.load(f)
        else:
            print(f"Ophalen {sym} {first}-{last}...")
            out[sym] = binance.history_range(sym, interval, start, end)
            with open(path, "w") as f:
                json.dump(out[sym], f)
    return out


def run_years(candles, first, last, warmup_days, settings):
    """Elk kalenderjaar apart: verse bots die eerst `warmup_days` voor 1 januari leren."""
    header(settings)
    warm = warmup_days * 86_400_000
    print(f"\n{'Jaar':10}" + "".join(f"{s.replace('USDT', ''):>21}" for s in SYMBOLS) + f"{'Totaal':>10}")
    totals, stops, n = [], 0, 0
    for year in range(first, last + 1):
        y0 = int(dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
        y1 = int(dt.datetime(year + 1, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
        window = {s: [k for k in ks if y0 - warm <= k["t"] < y1] for s, ks in candles.items()}
        window = {s: ks for s, ks in window.items() if ks}
        if REFERENCE not in window:
            continue
        bots = {sym: TradingBot(sym, settings, use_ref=sym != REFERENCE) for sym in window}
        feed(bots, window, y0)
        cells, eq, start = [], 0.0, 0.0
        for sym in SYMBOLS:
            if sym not in bots or bots[sym].start_price is None:
                cells.append("geen data")
                continue
            st = bots[sym].status()
            eq += st["equity"]
            start += st["start_capital"]
            stops += st["risk"]["killed"]
            n += 1
            late = "*" if window[sym][0]["t"] > y0 - warm else ""
            cells.append(f"{st['pnl_pct']:+6.1f}% (hh {st['buy_hold_pct']:+5.0f}%)" + ("!" if st["risk"]["killed"] else " ") + late)
        total = (eq / start - 1) * 100
        totals.append(total)
        upto = "" if candles[REFERENCE][-1]["t"] >= y1 - 3_600_000 else " (t/m nu)"
        print(f"{str(year) + upto:10}" + "".join(f"{c:>21}" for c in cells) + f"{total:+9.1f}%")
    print(f"\nGemiddeld per jaar: {sum(totals) / len(totals):+.1f}%   Noodstop geraakt: {stops} van {n} keer")
    print("hh = kopen en houden (1x).  ! = noodstop geraakt.  * = munt kwam later dat jaar op Binance")
    return totals


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--interval", default="1h", choices=list(INTERVAL_MS))
    ap.add_argument("--capital", type=float, default=500)
    ap.add_argument("--leverage", type=float, default=5)
    ap.add_argument("--risk", type=float, default=Settings.risk_per_trade * 100, help="max verlies per trade in %%")
    ap.add_argument("--days", type=int, default=180, help="dagen waarin getraded wordt (per periode)")
    ap.add_argument("--warmup-days", type=int, default=60, help="dagen vooraf om alleen te leren")
    ap.add_argument("--periods", type=int, default=1, help="aantal aparte periodes na elkaar")
    ap.add_argument("--from", dest="first", type=int, help="eerste jaar (test elk jaar apart)")
    ap.add_argument("--to", dest="last", type=int, help="laatste jaar")
    ap.add_argument("--no-short", action="store_true", help="alleen long, niet shorten")
    ap.add_argument("--stop-mult", type=float, default=Settings.stop_vol_mult,
                    help="stop-loss = zoveel keer de normale dagbeweging (standaard 2)")
    ap.add_argument("--offline", action="store_true", help="data uit data/ gebruiken")
    args = ap.parse_args()
    settings = Settings(interval=args.interval, start_capital=args.capital, leverage=args.leverage,
                        risk_per_trade=args.risk / 100, allow_short=not args.no_short,
                        stop_vol_mult=args.stop_mult)
    if args.first:
        last = args.last or dt.datetime.now(dt.timezone.utc).year
        candles = load_years(args.interval, args.first, last, args.warmup_days, args.offline)
        run_years(candles, args.first, last, args.warmup_days, settings)
        return
    per_day = 86_400_000 // settings.interval_ms
    n = (args.warmup_days + args.periods * args.days) * per_day
    candles = load_candles(args.interval, n, args.offline)
    if args.periods > 1:
        run_periods(candles, args.periods, args.days, args.warmup_days, settings)
    else:
        report(run(candles, args.days, settings))


if __name__ == "__main__":
    main()

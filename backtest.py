#!/usr/bin/env python3
"""Test de bots op echte Binance-geschiedenis.

De bots leren tijdens de test gewoon door en zien nooit de toekomst: elke
beslissing gebruikt alleen candles van vóór dat moment (walk-forward).

    python3 backtest.py                    # 180 dagen traden na 60 dagen opwarmen (1h-candles)
    python3 backtest.py --interval 15m --days 60 --warmup-days 20
    python3 backtest.py --offline          # gebruik eerder opgehaalde data in data/
"""
import argparse
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
                out[sym] = json.load(f)[-n:]
        else:
            print(f"Ophalen {sym}: {n} candles...")
            out[sym] = binance.history(sym, interval, n)
            with open(path, "w") as f:
                json.dump(out[sym], f)
    return out


def run(candles, days, settings, seed=1):
    bots = {sym: TradingBot(sym, settings, use_ref=sym != REFERENCE, seed=seed + i)
            for i, sym in enumerate(SYMBOLS)}
    ref = candles[REFERENCE]
    per_day = 86_400_000 // settings.interval_ms
    trade_from = ref[max(0, len(ref) - days * per_day)]["t"]
    feed(bots, candles, trade_from)
    return bots


def report(bots):
    print()
    print("=" * 78)
    s = next(iter(bots.values())).s
    print(f"PAPER-TRADING BACKTEST {s.interval}, ${s.start_capital:,.0f} per bot, max {s.leverage:g}x hefboom,"
          f" max {s.risk_per_trade:.0%} risico per trade (positie tot {s.max_exposure:.2f}x)")
    print(f"(fee {s.fee_rate:.2%} + slippage {s.slippage:.2%} per trade, funding {s.funding_8h:.2%}/8u meegerekend)")
    print("=" * 78)
    total_start = total_eq = 0.0
    for sym, bot in bots.items():
        st = bot.status()
        m = st["model"]["metrics"]
        total_start += st["start_capital"]
        total_eq += st["equity"]
        print(f"\n{st['name']} ({sym})")
        print(f"  Resultaat bot     {st['pnl_pct']:+7.2f}%   (${st['pnl']:+,.2f})")
        print(f"  Kopen en houden   {st['buy_hold_pct']:+7.2f}%   (1x, zonder hefboom)")
        print(f"  Max drawdown      {st['max_drawdown_pct']:7.2f}%")
        print(f"  Trades            {st['n_trades']:7d}    fees ${st['fees']:,.2f}   funding ${st['funding']:,.2f}"
              f"   liquidaties {st['liquidations']}")
        if m.get("samples"):
            print(f"  Model             trefzeker {m['accuracy']:.1%} vs altijd-hetzelfde {m['majority_accuracy']:.1%},"
                  f" score {m['skill']:+.3f} (>0 = beter dan gokken)")
        used = ", ".join(f"{s['label']} {s['used_pct']:.0f}%" for s in st["strategies"] if s["used_pct"] >= 0.5)
        print(f"  Gebruikt          {used}")
        best = ", ".join(f"{s['label']} {s['virtual_return_pct']:+.1f}%" for s in st["strategies"])
        print(f"  Virtueel/strategie {best}  (hele periode incl. opwarmen)")
    print("\n" + "-" * 78)
    print(f"Totaal: ${total_start:,.0f} -> ${total_eq:,.2f}  ({(total_eq / total_start - 1) * 100:+.2f}%)")
    print("Let op: resultaten uit het verleden zeggen weinig over de toekomst.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--interval", default="1h", choices=list(INTERVAL_MS))
    ap.add_argument("--capital", type=float, default=500)
    ap.add_argument("--leverage", type=float, default=5)
    ap.add_argument("--risk", type=float, default=10, help="max verlies per trade in %%")
    ap.add_argument("--days", type=int, default=180, help="dagen waarin getraded wordt")
    ap.add_argument("--warmup-days", type=int, default=60, help="dagen vooraf om alleen te leren")
    ap.add_argument("--offline", action="store_true", help="data uit data/ gebruiken")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    settings = Settings(interval=args.interval, start_capital=args.capital, leverage=args.leverage,
                        risk_per_trade=args.risk / 100)
    per_day = 86_400_000 // settings.interval_ms
    candles = load_candles(args.interval, (args.days + args.warmup_days) * per_day, args.offline)
    report(run(candles, args.days, settings, args.seed))


if __name__ == "__main__":
    main()

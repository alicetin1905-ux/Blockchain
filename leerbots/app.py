"""Houdt de drie bots bij elkaar: data ophalen, opwarmen, live draaien, opslaan."""
import logging
import os
import pickle
import threading
import time

from . import binance, funding
from .bot import VERSION, TradingBot
from .config import REFERENCE, SYMBOLS, describe_risk
from .risk import RiskBook

log = logging.getLogger("leerbots")


def feed(bots, candles_by_symbol, trade_from=None):
    """Voer candles van alle munten op tijdsvolgorde aan de bots.

    BTC gaat per tijdstip eerst, zodat ETH en SOL BTC's signalen van hetzelfde
    moment kunnen gebruiken. trade_from=None: alleen leren. Anders wordt er
    getraded vanaf dat tijdstip (ms).
    """
    by_t = {}
    for sym, ks in candles_by_symbol.items():
        for k in ks:
            by_t.setdefault(k["t"], {})[sym] = k
    order = sorted(bots, key=lambda s: s != REFERENCE)
    processed = 0
    for t in sorted(by_t):
        row = by_t[t]
        trade = trade_from is not None and t >= trade_from
        ref = None
        for sym in order:
            if sym not in row:
                continue
            bot = bots[sym]
            before = bot.index
            feats = bot.step(row[sym], ref, trade)
            if sym == REFERENCE:
                ref = feats
            processed += bot.index - before  # dubbele candles tellen niet mee
    return processed


def _key(s):
    """Instellingen die bepalen of opgeslagen bots nog bruikbaar zijn."""
    return (s.interval, s.leverage, s.start_capital, getattr(s, "risk_per_trade", None),
            getattr(s, "stop_vol_mult", None),
            getattr(s, "allow_short", None))


class App:
    def __init__(self, settings_by_symbol, state_dir="state", warmup=3000):
        self.per = settings_by_symbol             # Settings per munt (verschillen alleen in risico)
        self.s = settings_by_symbol[REFERENCE]
        self.state_dir = state_dir
        self.state_file = os.path.join(state_dir, "bots.pkl")
        self.warmup = warmup
        self.lock = threading.RLock()
        self.bots = {}
        self.error = None
        self.phase = "starten"
        self.updated = None
        self.funding = {s: [] for s in SYMBOLS}   # bekende funding rates per munt
        self.funding_checked = 0
        self.funding_live = None                   # True/False: live funding-API bereikbaar?

    # --------------------------------------------------------------- opslag
    def save(self):
        os.makedirs(self.state_dir, exist_ok=True)
        tmp = self.state_file + ".tmp"
        with open(tmp, "wb") as f:
            pickle.dump({"version": VERSION, "bots": self.bots}, f)
        os.replace(tmp, self.state_file)

    def load(self):
        if not os.path.exists(self.state_file):
            return False
        try:
            with open(self.state_file, "rb") as f:
                data = pickle.load(f)
            if (data.get("version") != VERSION or set(data["bots"]) != set(SYMBOLS)
                    or any(_key(b.s) != _key(self.per[sym]) for sym, b in data["bots"].items())):
                log.warning("Opgeslagen staat hoort bij een andere versie of andere instellingen; begin opnieuw.")
                return False
            self.bots = data["bots"]
            return True
        except Exception as e:
            log.warning("Kon opgeslagen staat niet lezen (%s); begin opnieuw.", e)
            return False

    # ------------------------------------------------------------ opstarten
    def start(self, reset=False):
        if not reset and self.load():
            log.info("Opgeslagen bots geladen; gemiste candles inhalen...")
            self.phase = "inhalen"
            self.catch_up()
        else:
            self.bots = {sym: TradingBot(sym, self.per[sym], use_ref=sym != REFERENCE) for sym in SYMBOLS}
            self.phase = "opwarmen"
            log.info("Nieuwe bots: opwarmen op %d candles geschiedenis (alleen leren)...", self.warmup)
            data = {sym: binance.history(sym, self.s.interval, self.warmup) for sym in SYMBOLS}
            self._load_funding(data)
            with self.lock:
                feed(self.bots, data, trade_from=None)
            for sym, bot in self.bots.items():
                up, down = bot.model_up.metrics(), bot.model_down.metrics()
                log.info("%s opgewarmd: %d candles, modelscore stijging %.3f / daling %.3f, strategie %s",
                         sym, bot.index, up.get("skill", 0.0), down.get("skill", 0.0), bot.active)
        if self.s.max_total_risk:
            RiskBook(self.bots, self.s.max_total_risk)
        if self.funding_live is False:
            log.warning("Live funding-API (fapi.binance.com) niet bereikbaar; de laatst bekende funding rate"
                        " uit de maandarchieven wordt gebruikt.")
        self.save()
        self.phase = "live"

    def _load_funding(self, data):
        """Funding voor de opgehaalde candles: maandarchieven plus de live API."""
        for sym, ks in data.items():
            if not ks:
                continue
            start = min([ks[0]["t"]] + [t for t, _ in self.funding[sym][:1]])
            arch = funding.history(sym, start, ks[-1]["ct"], cache_dir=os.path.join(self.state_dir, "funding"))
            live = funding.recent(sym)
            self.funding_live = bool(live)
            self.funding[sym] = funding.merge(self.funding[sym], arch, live)
            funding.attach(ks, self.funding[sym])
        self.funding_checked = time.time()

    def _refresh_funding(self, fresh):
        if time.time() - self.funding_checked > 3600:
            for sym in SYMBOLS:
                live = funding.recent(sym)
                self.funding_live = bool(live)
                self.funding[sym] = funding.merge(self.funding[sym], live)
            self.funding_checked = time.time()
        for sym, ks in fresh.items():
            funding.attach(ks, self.funding[sym])

    def catch_up(self):
        """Candles die gemist zijn (pc uit, netwerk weg) alleen gebruiken om te leren."""
        now = int(time.time() * 1000)
        last = min(b.last_t or 0 for b in self.bots.values())
        missing = int((now - last) / self.s.interval_ms) + 2
        if missing <= 2:
            return
        n = min(missing, 5000)
        data = {sym: binance.history(sym, self.s.interval, n) for sym in SYMBOLS}
        self._load_funding(data)
        with self.lock:
            done = feed(self.bots, data, trade_from=None)
        if done:
            log.info("%d gemiste candles ingehaald (zonder traden).", done)

    # ----------------------------------------------------------------- live
    def poll_once(self):
        try:
            fresh = {sym: binance.closed_klines(sym, self.s.interval, 5) for sym in SYMBOLS}
            live = binance.prices(SYMBOLS)
        except binance.BinanceError as e:
            self.error = str(e)
            log.warning("%s", e)
            return
        self.error = None
        self._refresh_funding(fresh)
        now = int(time.time() * 1000)
        with self.lock:
            # Te groot gat (bijv. slaapstand)? Eerst inhalen zonder te traden.
            for sym, ks in fresh.items():
                last = self.bots[sym].last_t
                if ks and last and ks[0]["t"] > last + self.s.interval_ms:
                    self.catch_up()
                    break
            new = feed(self.bots, fresh, trade_from=0)
            for sym, price in live.items():
                self.bots[sym].tick(price, now)
            if new:
                self.save()
                for sym in SYMBOLS:
                    b = self.bots[sym]
                    log.info("%s %.2f | equity $%.2f | %s | strategie %s | stijging/daling %s", sym,
                             b.last_price, b.portfolio.equity(b.last_price), b.portfolio.side or "geen positie",
                             b.active, f"{b.p[0]:.2f}/{b.p[1]:.2f}" if b.p else "-")
            self.updated = now

    def command(self, symbol, action):
        with self.lock:
            bot = self.bots.get(symbol)
            if not bot:
                return False
            if action == "pause":
                bot.pause(int(time.time() * 1000))
            elif action == "resume":
                bot.resume()
            else:
                return False
            self.save()
            return True

    def snapshot(self):
        with self.lock:
            bots = [self.bots[s].status() for s in SYMBOLS if s in self.bots]
        start = sum(b["start_capital"] for b in bots)
        equity = sum(b["equity"] for b in bots)
        return {
            "mode": "paper",
            "phase": self.phase,
            "interval": self.s.interval,
            "updated": self.updated,
            "error": self.error,
            "funding_live": self.funding_live,
            "funding_latest": {s: (f[-1] if f else None) for s, f in self.funding.items()},
            "settings": {**{k: getattr(self.s, k) for k in self.s.__dataclass_fields__},
                         "risk_per_symbol": {s: st.risk_per_trade for s, st in self.per.items()},
                         "risk_text": describe_risk(self.per)},
            "totals": {"start": start, "equity": equity,
                       "pnl": equity - start, "pnl_pct": (equity / start - 1) * 100 if start else 0},
            "bots": bots,
        }

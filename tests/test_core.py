import math
import random
import unittest

from leerbots.app import feed
from leerbots.bandit import DiscountedThompson
from leerbots.bot import TradingBot
from leerbots.config import Settings
from leerbots.model import OnlineLogReg
from leerbots.portfolio import Portfolio
from leerbots.risk import RiskManager

HOUR = 3_600_000


def synthetic(n, drift=0.0, vol=0.01, seed=0, start=100.0):
    rng = random.Random(seed)
    out, price = [], start
    for i in range(n):
        o = price
        price *= math.exp(drift + rng.gauss(0, vol))
        h, l = max(o, price) * 1.002, min(o, price) * 0.998
        out.append({"t": i * HOUR, "o": o, "h": h, "l": l, "c": price, "v": 100 + rng.random() * 50,
                    "ct": (i + 1) * HOUR - 1})
    return out


class ModelTest(unittest.TestCase):
    def test_learns_separable_data(self):
        rng = random.Random(1)
        m = OnlineLogReg(2)
        for _ in range(3000):
            x = [rng.gauss(0, 1), rng.gauss(0, 1)]
            m.observe(x)
            m.update(x, 1 if x[0] > 0 else 0)
        self.assertGreater(m.predict([2.0, 0.0]), 0.9)
        self.assertLess(m.predict([-2.0, 0.0]), 0.1)
        self.assertGreater(m.metrics()["skill"], 0.3)

    def test_no_skill_on_noise(self):
        rng = random.Random(2)
        m = OnlineLogReg(3)
        for _ in range(3000):
            x = [rng.gauss(0, 1) for _ in range(3)]
            m.observe(x)
            m.update(x, rng.random() < 0.5)
        self.assertLess(m.metrics()["skill"], 0.02)


class BanditTest(unittest.TestCase):
    def test_prefers_profitable_arm_and_cash_over_losers(self):
        rng = random.Random(3)
        b = DiscountedThompson(["good", "bad", "cash"], gamma=0.995)
        for _ in range(1000):
            b.update({"good": rng.gauss(3, 20), "bad": rng.gauss(-3, 20), "cash": 0.0})
        self.assertEqual(b.choose(1.0), "good")
        b2 = DiscountedThompson(["bad", "noise", "cash"], gamma=0.995)
        for _ in range(1000):
            b2.update({"bad": rng.gauss(-3, 20), "noise": rng.gauss(0, 40), "cash": 0.0})
        self.assertEqual(b2.choose(1.0), "cash")

    def test_forgets_old_results(self):
        b = DiscountedThompson(["a", "cash"], gamma=0.98)
        for _ in range(500):
            b.update({"a": 5.0, "cash": 0.0})
        for _ in range(500):
            b.update({"a": -5.0, "cash": 0.0})
        self.assertEqual(b.choose(1.0), "cash")


class PortfolioTest(unittest.TestCase):
    def test_round_trip_costs_fees(self):
        p = Portfolio(10_000)
        p.rebalance(1.0, 100.0, 0, "test", "x", 0.001, 0.0)
        self.assertAlmostEqual(p.qty, 100.0)  # futures: fee gaat van het saldo af
        p.rebalance(0.0, 100.0, 1, "test", "x", 0.001, 0.0)
        self.assertEqual(p.qty, 0.0)
        self.assertAlmostEqual(p.balance, 10_000 - 10 - 10, places=6)
        self.assertEqual(p.n_trades, 2)
        self.assertLess(p.trades[-1]["pnl"], 0)

    def test_leverage_multiplies_result(self):
        p = Portfolio(500)
        p.rebalance(5.0, 100.0, 0, "test", "x", 0.0, 0.0)
        self.assertAlmostEqual(p.notional(100.0), 2500)
        self.assertAlmostEqual(p.equity(102.0), 550)      # +2% koers = +10% eigen geld
        self.assertAlmostEqual(p.equity(98.0), 450)       # -2% koers = -10% eigen geld
        liq = p.liquidation_price(0.005)
        self.assertAlmostEqual(liq, 80.0 / 0.995, places=6)  # ~-19,6%
        self.assertAlmostEqual(p.equity(liq), 0.005 * p.notional(liq), places=6)

    def test_liquidation_wipes_margin(self):
        p = Portfolio(500)
        p.rebalance(5.0, 100.0, 0, "test", "x", 0.0, 0.0)
        p.liquidate(p.liquidation_price(0.005), 1, "x", 0.005)
        self.assertEqual(p.qty, 0.0)
        self.assertLess(p.balance, 1e-6)
        self.assertEqual(p.liquidations, 1)

    def test_funding_costs_money(self):
        p = Portfolio(500)
        p.rebalance(5.0, 100.0, 0, "test", "x", 0.0, 0.0)
        p.charge_funding(100.0, 0.0001)
        self.assertAlmostEqual(p.funding, 0.25)
        self.assertAlmostEqual(p.equity(100.0), 499.75)


class RiskTest(unittest.TestCase):
    def test_limits(self):
        s = Settings()
        r = RiskManager(s)
        r.on_candle(0, 10_000)
        self.assertEqual(r.filter(1.0, 0)[0], 1.0)
        r.on_candle(HOUR, 8_400)  # -16% op een dag
        self.assertEqual(r.filter(1.0, 1)[0], 0.0)
        r.on_candle(25 * HOUR, 8_400)  # nieuwe dag
        self.assertEqual(r.filter(1.0, 2)[0], 1.0)
        r.on_candle(49 * HOUR, 5_900)  # -41% onder piek
        self.assertTrue(r.killed)
        r.resume(5_900)
        self.assertEqual(r.filter(1.0, 3)[0], 1.0)
        r.trigger_stop(10)
        self.assertEqual(r.filter(1.0, 12)[0], 0.0)


class BotTest(unittest.TestCase):
    def test_runs_end_to_end_without_lookahead(self):
        s = Settings(min_model_updates=50)
        candles = {"BTCUSDT": synthetic(1500, seed=1), "ETHUSDT": synthetic(1500, seed=2)}
        bots = {sym: TradingBot(sym, s, use_ref=sym != "BTCUSDT") for sym in candles}
        feed(bots, candles, trade_from=candles["BTCUSDT"][500]["t"])
        for bot in bots.values():
            st = bot.status()
            self.assertEqual(st["candles_seen"], 1500)
            self.assertGreater(st["model"]["updates"], 1000)
            self.assertGreater(st["equity"], 0)
            self.assertEqual(len(bot.history), 1000)

    def test_stop_loss_and_pause(self):
        s = Settings()
        bot = TradingBot("BTCUSDT", s)
        for k in synthetic(80, seed=4):
            bot.step(k, trade=False)
        bot.portfolio.rebalance(5.0, bot.last_price, 0, "test", "trend", s.fee_rate, s.slippage)
        bot.tick(bot.portfolio.entry * 0.97, 0)
        self.assertEqual(bot.portfolio.qty, 0.0)
        self.assertEqual(bot.portfolio.trades[-1]["reason"], "stop-loss")
        self.assertGreater(bot.portfolio.balance, 400)  # stop voorkwam liquidatie
        bot.portfolio.rebalance(1.0, bot.last_price, 0, "test", "trend", s.fee_rate, s.slippage)
        bot.pause(0)
        self.assertEqual(bot.portfolio.qty, 0.0)
        self.assertEqual(bot.risk.filter(1.0, 10**9)[0], 0.0)

    def test_gap_below_liquidation_liquidates(self):
        s = Settings()
        bot = TradingBot("BTCUSDT", s)
        for k in synthetic(80, seed=5):
            bot.step(k, trade=False)
        bot.portfolio.rebalance(5.0, bot.last_price, 0, "test", "trend", s.fee_rate, s.slippage)
        crash = bot.last_price * 0.75
        bot.step({"t": bot.last_t + HOUR, "o": crash, "h": crash, "l": crash * 0.99, "c": crash, "v": 1,
                  "ct": bot.last_t + 2 * HOUR - 1}, trade=True)
        self.assertEqual(bot.portfolio.liquidations, 1)
        self.assertTrue(bot.risk.killed)

    def test_never_exceeds_leverage(self):
        s = Settings(min_model_updates=50)
        candles = {"BTCUSDT": synthetic(1500, drift=0.0005, seed=7)}
        bots = {"BTCUSDT": TradingBot("BTCUSDT", s)}
        feed(bots, candles, trade_from=candles["BTCUSDT"][300]["t"])
        bot = bots["BTCUSDT"]
        self.assertLessEqual(bot.portfolio.exposure(bot.last_price), s.leverage * 1.15)

    def test_skips_duplicate_candles(self):
        bots = {"BTCUSDT": TradingBot("BTCUSDT", Settings())}
        ks = {"BTCUSDT": synthetic(3)}
        self.assertEqual(feed(bots, ks, trade_from=0), 3)
        self.assertEqual(feed(bots, ks, trade_from=0), 0)
        self.assertEqual(bots["BTCUSDT"].index, 3)


if __name__ == "__main__":
    unittest.main()

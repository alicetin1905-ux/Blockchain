"""Instellingen voor de bots. Pas hier risico, kosten en leertempo aan."""
from dataclasses import dataclass

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
REFERENCE = "BTCUSDT"  # ETH en SOL kijken ook naar wat BTC doet
NAMES = {"BTCUSDT": "Bitcoin", "ETHUSDT": "Ethereum", "SOLUSDT": "Solana"}
INTERVAL_MS = {"5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}


@dataclass
class Settings:
    # Candle-grootte. Kortere candles = meer trades = meer kosten. 1 uur is een goede start.
    interval: str = "1h"

    # Portefeuille (elke bot heeft een eigen nep-portemonnee, zoals een futures-account)
    start_capital: float = 500.0
    leverage: float = 5.0           # maximale hefboom (positie / eigen geld)
    allow_short: bool = True        # False = alleen long
    fee_rate: float = 0.0005        # Binance USDT-futures taker-fee 0,05% (spot: 0,001)
    slippage: float = 0.0002        # 0,02% aangenomen slippage per trade
    funding_8h: float = 0.0001      # gemiddelde funding 0,01% per 8 uur die longs betalen (spot: 0)
    maintenance_margin: float = 0.005  # onder 0,5% van de positie wordt je geliquideerd

    # Leren
    horizon: int = 6               # model voorspelt 6 candles (6 uur) vooruit
    min_model_updates: int = 200   # model telt pas mee na zoveel gelabelde voorbeelden
    learning_rate: float = 0.05
    l2: float = 1e-4
    bandit_discount: float = 0.995  # geheugen strategiekiezer: ~200 candles (~8 dagen)
    decision_every: int = 6         # elke 6 candles (6 uur) opnieuw een strategie kiezen
    confidence: float = 1.0         # hoe zeker een strategie moet zijn (hoger = voorzichtiger)

    # Risico (de bot kan deze regels niet wegleren). Percentages van je eigen geld,
    # behalve stop_loss: die gaat over de koers. Bij 5x kost 2% koersdaling 10% van je geld.
    risk_per_trade: float = 0.02    # max 2% van je geld verliezen als de stop-loss geraakt wordt
    stop_loss: float = 0.02         # koers 2% onder instapprijs -> sluiten
    stop_cooldown: int = 6          # na stop-loss 6 candles niet kopen
    daily_loss_limit: float = 0.15  # 15% verlies op een dag -> rest van de dag geen positie
    max_drawdown: float = 0.40      # 40% onder de piek -> bot stopt tot handmatige hervatting

    @property
    def interval_ms(self) -> int:
        return INTERVAL_MS[self.interval]

    @property
    def max_exposure(self) -> float:
        """Grootste positie (x eigen geld) waarbij een stop-loss hoogstens risk_per_trade kost.

        Verlies bij stop = positie x (koersdaling tot stop + fees en slippage bij in- en uitstappen).
        Nooit meer dan de hefboom.
        """
        loss_per_x = self.stop_loss + 2 * self.cost
        return min(self.leverage, self.risk_per_trade / loss_per_x)

    @property
    def funding_per_candle(self) -> float:
        return self.funding_8h * self.interval_ms / 28_800_000

    @property
    def cost(self) -> float:
        """Kosten per kant (fee + slippage) als fractie."""
        return self.fee_rate + self.slippage

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

    # Portefeuille (elke bot heeft een eigen nep-portemonnee)
    start_capital: float = 10_000.0
    fee_rate: float = 0.001        # Binance spot taker-fee 0,1%
    slippage: float = 0.0002       # 0,02% aangenomen slippage per trade

    # Leren
    horizon: int = 6               # model voorspelt 6 candles (6 uur) vooruit
    min_model_updates: int = 200   # model telt pas mee na zoveel gelabelde voorbeelden
    learning_rate: float = 0.05
    l2: float = 1e-4
    bandit_discount: float = 0.995  # geheugen strategiekiezer: ~200 candles (~8 dagen)
    decision_every: int = 6         # elke 6 candles (6 uur) opnieuw een strategie kiezen
    confidence: float = 1.0         # hoe zeker een strategie moet zijn (hoger = voorzichtiger)

    # Risico (de bot kan deze regels niet wegleren)
    max_exposure: float = 1.0       # max deel van de eigen portemonnee in de munt
    min_rebalance: float = 0.10     # kleinere aanpassingen dan 10% worden overgeslagen
    stop_loss: float = 0.03         # 3% onder instapprijs -> verkopen
    stop_cooldown: int = 6          # na stop-loss 6 candles niet kopen
    daily_loss_limit: float = 0.05  # 5% verlies op een dag -> rest van de dag cash
    max_drawdown: float = 0.20      # 20% onder de piek -> bot stopt tot handmatige hervatting

    @property
    def interval_ms(self) -> int:
        return INTERVAL_MS[self.interval]

    @property
    def cost(self) -> float:
        """Kosten per kant (fee + slippage) als fractie."""
        return self.fee_rate + self.slippage

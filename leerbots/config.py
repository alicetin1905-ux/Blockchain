"""Instellingen voor de bots. Pas hier risico, kosten en leertempo aan."""
from dataclasses import dataclass, replace

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
REFERENCE = "BTCUSDT"  # ETH en SOL kijken ook naar wat BTC doet
NAMES = {"BTCUSDT": "Bitcoin", "ETHUSDT": "Ethereum", "SOLUSDT": "Solana"}
# Max verlies per trade (in % van het geld van die bot) als de stop-loss geraakt wordt.
DEFAULT_RISK = {"BTCUSDT": 5.0, "ETHUSDT": 5.0, "SOLUSDT": 5.0}
INTERVAL_MS = {"5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000,
               "1d": 86_400_000}


@dataclass
class Settings:
    # Candle-grootte. Kortere candles = meer trades = meer kosten. 1 uur is een goede start.
    interval: str = "1h"

    # Portefeuille (elke bot heeft een eigen nep-portemonnee, zoals een futures-account)
    start_capital: float = 500.0
    leverage: float = 5.0           # maximale hefboom (positie / eigen geld)
    allow_short: bool = False       # True = ook shorten (kostte in backtests geld)
    fee_rate: float = 0.0005        # Binance USDT-futures taker-fee 0,05% (spot: 0,001)
    slippage: float = 0.0002        # 0,02% aangenomen slippage per trade
    funding_8h: float = 0.0001      # funding als de echte rate onbekend is: 0,01% per 8 uur
    real_funding: bool = True       # echte Binance funding rates gebruiken als die bekend zijn
    maintenance_margin: float = 0.005  # onder 0,5% van de positie wordt je geliquideerd

    # Leren
    horizon: int = 6               # model voorspelt 6 candles (6 uur) vooruit
    min_model_updates: int = 200   # model telt pas mee na zoveel gelabelde voorbeelden
    learning_rate: float = 0.05
    l2: float = 1e-4
    bandit_discount: float = 0.998  # geheugen strategiekiezer: ~500 candles (~3 weken)
    decision_every: int = 24        # elke 24 candles (1 dag) opnieuw een strategie kiezen
    confidence: float = 1.0         # hoe zeker een strategie moet zijn (hoger = voorzichtiger)
    funding_features: bool = True   # funding rates als signaal voor de modellen

    # Verbeteringen (0 of False = uit)
    trend_days: int = 50            # alleen long als de koers boven het 50-daags gemiddelde staat
    trailing_stop: bool = False     # stop-loss schuift mee met de koers (kostte in tests winst)
    max_total_risk: float = 0.0     # max open risico over alle bots samen, bijv. 0.03 = 3% (0 = uit)

    # Risico (de bot kan deze regels niet wegleren). Percentages van je eigen geld,
    # behalve de stop-loss: die gaat over de koers.
    risk_per_trade: float = 0.05    # max 5% van je geld verliezen als de stop-loss geraakt wordt
    stop_vol_mult: float = 2.0      # stop-loss = 2x de normale dagbeweging van de munt
    stop_min: float = 0.01          # ... maar minstens 1%
    stop_max: float = 0.15          # ... en hoogstens 15% van de instapprijs
    stop_cooldown: int = 6          # na stop-loss 6 candles geen nieuwe positie
    daily_loss_limit: float = 0.15  # 15% verlies op een dag -> rest van de dag geen positie
    max_drawdown: float = 0.40      # 40% onder de piek -> bot stopt tot handmatige hervatting

    @property
    def interval_ms(self) -> int:
        return INTERVAL_MS[self.interval]

    def stop_distance(self, vol_per_candle: float) -> float:
        """Afstand van de stop-loss tot de instapprijs, op basis van de beweeglijkheid.

        vol_per_candle is de standaardafwijking van de koersverandering per candle (laatste 48).
        Omgerekend naar een dag: x wortel(candles per dag).
        """
        per_day = 86_400_000 / self.interval_ms
        dist = self.stop_vol_mult * vol_per_candle * per_day ** 0.5
        return min(self.stop_max, max(self.stop_min, dist))

    def size_for(self, stop_distance: float) -> float:
        """Positie (x eigen geld) waarbij een geraakte stop-loss hoogstens risk_per_trade kost.

        Verlies bij stop = positie x (koersafstand tot stop + fees en slippage bij in- en uitstappen).
        Ruimere stop = kleinere positie. Nooit meer dan de hefboom.
        """
        return min(self.leverage, self.risk_per_trade / (stop_distance + 2 * self.cost))

    @property
    def funding_per_candle(self) -> float:
        return self.funding_8h * self.interval_ms / 28_800_000

    @property
    def cost(self) -> float:
        """Kosten per kant (fee + slippage) als fractie."""
        return self.fee_rate + self.slippage


def parse_risk(text=None):
    """Risico per munt als fractie. "5" = 5% voor alle munten, "BTC=2,ETH=5,SOL=10" = per munt.

    Munten die niet genoemd worden houden DEFAULT_RISK.
    """
    if text is None or str(text).strip() == "":
        return {s: DEFAULT_RISK[s] / 100 for s in SYMBOLS}
    text = str(text)
    if "=" not in text:
        return {s: float(text) / 100 for s in SYMBOLS}
    out = {s: DEFAULT_RISK[s] / 100 for s in SYMBOLS}
    for part in text.split(","):
        key, value = part.split("=")
        sym = key.strip().upper()
        sym = sym if sym.endswith("USDT") else sym + "USDT"
        if sym not in SYMBOLS:
            raise ValueError(f"onbekende munt: {key.strip()} (kies uit {', '.join(s[:-4] for s in SYMBOLS)})")
        out[sym] = float(value) / 100
    return out


def per_symbol(base, risk):
    """Eén Settings per munt: alles gelijk behalve het risico per trade."""
    return {s: replace(base, risk_per_trade=risk[s]) for s in SYMBOLS}


def describe_risk(settings_by_symbol):
    return ", ".join(f"{s[:-4]} {st.risk_per_trade:.0%}" for s, st in settings_by_symbol.items())


def apply_overrides(base, text):
    """Pas instellingen aan met tekst zoals "trend_days=0,trailing_stop=false,interval=4h"."""
    if not text:
        return base
    changes = {}
    for part in text.split(","):
        key, value = (x.strip() for x in part.split("="))
        if key not in base.__dataclass_fields__:
            raise ValueError(f"onbekende instelling: {key}")
        current = getattr(base, key)
        if isinstance(current, bool):
            low = value.lower()
            if low not in ("true", "false", "1", "0", "aan", "uit", "ja", "nee"):
                raise ValueError(f"{key} moet aan/uit zijn, niet {value}")
            changes[key] = low in ("true", "1", "aan", "ja")
        elif isinstance(current, int):
            changes[key] = int(value)
        elif isinstance(current, float):
            changes[key] = float(value)
        else:
            changes[key] = value
    return replace(base, **changes)

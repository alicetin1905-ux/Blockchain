# Leerbots

Drie zelflerende trading-bots voor **Bitcoin, Ethereum en Solana**. Ze handelen vanzelf op live Binance-koersen, maar alleen met **nep-geld (paper trading)**. Er worden geen orders naar een beurs gestuurd en je hebt geen API-sleutels nodig.

Standaard werkt elke bot zo:
- hij krijgt **$500**;
- hij kan **long en short**, zoals op een Binance USDT-futures account;
- hij heeft **hoogstens één positie tegelijk**;
- hij riskeert per trade maximaal **2% (BTC), 5% (ETH) of 10% (SOL)** van zijn geld, met een hefboom van hoogstens 5x.

De simulatie rekent futures-fees, funding en liquidatie mee.

Alles is gewone Python (3.9 of nieuwer), zonder extra pakketten.

## Starten

```bash
python3 run.py
```

Open daarna **http://localhost:8000** voor het dashboard.

- Bij de eerste start leren de bots eerst op de laatste 3000 uurcandles (ongeveer 4 maanden). Ze traden dan nog niet. Dat opwarmen duurt ongeveer een halve minuut.
- Daarna draaien ze live. Elk uur komt er een nieuwe candle binnen, en elke 10 seconden wordt de koers gecontroleerd voor de stop-loss en liquidatie.
- Het geheugen (modellen, strategiescores, portemonnee) staat in `state/`. Stop je het programma met Ctrl+C en start je het later opnieuw, dan gaan de bots verder waar ze waren. Gemiste candles gebruiken ze alleen om te leren; daarover traden ze niet achteraf.
- Opties:
  - `--capital 500`: startgeld per bot;
  - `--leverage 5`: maximale hefboom;
  - `--risk BTC=2,ETH=5,SOL=10`: max verlies per trade in % per munt, of `--risk 5` voor alle munten;
  - `--no-short`: alleen long;
  - `--reset`: alles vergeten;
  - `--interval 15m`: andere candle-grootte;
  - `--port 8080`;
  - `--host 0.0.0.0`: dashboard ook vanaf andere apparaten bereikbaar.
- Verander je startgeld, hefboom, risico of interval, dan beginnen de bots automatisch opnieuw.

Voor 24/7 laat je het draaien op een pc die aan blijft, een Raspberry Pi of een kleine VPS, bijvoorbeeld met `nohup python3 run.py &`, `tmux` of een systemd-service.

## Backtest

```bash
python3 backtest.py                   # 180 dagen traden na 60 dagen opwarmen, uurcandles
python3 backtest.py --periods 4       # 4 aparte periodes van 180 dagen: is het resultaat stabiel?
python3 backtest.py --risk 5 --leverage 3   # 5% risico voor alle munten
python3 backtest.py --risk BTC=2,ETH=5,SOL=10
python3 backtest.py --from 2020 --to 2026 # elk kalenderjaar apart, met verse bots
python3 backtest.py --no-short            # alleen long
python3 backtest.py --stop-mult 3         # ruimere stop-loss (3x de dagbeweging)
```

De bots leren tijdens de test gewoon door en zien nooit de toekomst: elke beslissing gebruikt alleen data van vóór dat moment. Test een wijziging altijd met `--periods 4`. Eén goede periode zegt weinig.

## Hoe de zelflerende modus werkt

Elke munt heeft een eigen bot met een eigen nep-portemonnee. Per afgesloten candle doet de bot dit:

```
candle ──► signalen ──► 2 modellen leren bij ──► strategieën ──► strategiekiezer ──► risicoregels ──► paper trade
              │            ▲                          │                ▲
              │            └─ uitkomst 6 candles later └─ virtuele winst/verlies per strategie, long én short
              └─ ETH en SOL kijken ook naar BTC
```

**1. Signalen** (`leerbots/features.py`):
- koersverandering over 1, 3, 12 en 48 candles;
- beweeglijkheid en RSI;
- afstand tot de EMA20 en EMA50;
- volume ten opzichte van normaal;
- candlevorm en tijdstip.

ETH en SOL krijgen ook BTC's koersverandering mee.

**2. Twee voorspellende modellen** (`leerbots/model.py`), allebei online logistische regressie:
- het ene schat de kans dat de koers binnen 6 candles meer **stijgt** dan de kosten van in- en uitstappen;
- het andere schat de kans dat de koers meer **daalt** dan die kosten.

Zodra die 6 candles voorbij zijn, weten de modellen of ze gelijk hadden en passen ze zich een klein stapje aan.

**3. Strategieën** (`leerbots/strategies.py`). Elke strategie zegt long, short of niets:

| Strategie | Long | Short |
|---|---|---|
| Trend volgen | EMA20 boven EMA50 en koers erboven | EMA20 onder EMA50 en koers eronder |
| Terugveren | RSI onder 30, uit boven 55 | RSI boven 70, uit onder 45 |
| Uitbraak | boven hoogste koers van 48 candles | onder laagste koers van 48 candles |
| Model (ML) | stijgingsmodel duidelijk boven normaal | dalingsmodel duidelijk boven normaal |
| Cash | nooit | nooit |

**4. Strategiekiezer** (`leerbots/bandit.py`), de eigenlijke zelfleer-laag:
- Elke candle krijgt elke strategie een virtuele score: wat ze ná kosten verdiend zou hebben, long of short, ook als de bot haar niet volgt.
- Die virtuele trades volgen **precies dezelfde regels als de echte**: dezelfde positiegrootte, dezelfde stop-loss en dezelfde afkoeltijd na een stop. De bot leert dus welke strategie werkt mét de regels die echt gelden.
- Oude resultaten vervagen (discount 0,995, ongeveer 8 dagen geheugen), zodat de bot zich aanpast als de markt omslaat.
- Elke 6 candles kiest de bot de strategie met de hoogste *ondergrens*: het gemiddelde min de onzekerheid. Is geen strategie aantoonbaar beter dan niets doen, dan blijft hij in cash.
- Hij wisselt alleen als de verwachte winst de kosten van de wissel dekt.

**5. Eén positie per munt.** Een positie wordt in één keer geopend en in één keer gesloten. De bot koopt niet bij en bouwt niet half af. Draait de strategie van long naar short, dan sluit hij eerst de long en opent daarna de short.

**6. Stop-loss die meebeweegt met de markt.** De stop-loss ligt op 2x de normale dagbeweging van de munt, berekend uit de laatste 48 candles, met een minimum van 1% en een maximum van 15%. In een rustige markt ligt hij dicht bij de instap, in een wilde markt verder weg. Zo wordt een positie niet door gewone schommelingen uitgestopt.

**7. Positiegrootte en risico per trade.** De bot kiest de grootste positie waarbij een geraakte stop-loss, inclusief fees en slippage, hoogstens het ingestelde risico kost:

```
positie = risico / (stop-afstand + 0,14% kosten), nooit meer dan de hefboom

voorbeelden bij 2% risico:   stop 3%  -> 0,64x je geld   stop 6%  -> 0,33x   stop 10% -> 0,20x
voorbeelden bij 5% risico:   stop 3%  -> 1,59x           stop 6%  -> 0,81x   stop 10% -> 0,49x
```

Ruimere stop betekent een kleinere positie, maar een geraakte stop kost altijd hetzelfde: 2% of 5% van je geld.

**8. Risicoregels** (`leerbots/risk.py`). Deze staan buiten het lerende deel, dus de bot kan ze niet "wegleren".
- de stop-loss en positiegrootte hierboven, daarna 6 candles afkoelen;
- liquidatie wordt gesimuleerd. De stop-loss moet dat voorkomen, maar bij een plotselinge koerssprong (gat) kan het toch gebeuren;
- bij 15% verlies op een dag geen positie meer voor de rest van die dag;
- bij 40% onder de piek stopt de bot tot je hem op het dashboard hervat;
- knop "Stop en sluiten" per bot.

**Kosten**:
- 0,05% futures-fee plus 0,02% slippage per trade;
- funding van gemiddeld 0,01% per 8 uur over de positiegrootte. Voorzichtig gerekend betalen long én short dit; in werkelijkheid ontvangen shorts vaak funding.

Ook de virtuele scores rekenen deze kosten mee. Alle instellingen staan in `leerbots/config.py`.

## Op het dashboard

- **Waarde en resultaat** per bot, vergeleken met gewoon kopen en houden.
- **Grafiek** van de bot tegenover de koers.
- **Positie**: long of short, grootte, instapprijs, open resultaat, stop-loss, liquidatieprijs, wat een stop-loss nu zou kosten, en gewonnen tegen verloren trades.
- **Wat de bot leert**:
  - welke strategie hij volgt;
  - de kans dat elke strategie nu echt de beste is;
  - wat elke strategie nu zou doen (▲ long, ▼ short);
  - de virtuele winst per strategie.
- **Modellen**: kans op stijging en op daling nu, vergeleken met normaal. De score toont of een model beter is dan gokken (boven 0 = beter).
- **Laatste trades** met de reden: welke strategie, of een stop-loss of risicoregel.

## Eerlijk over wat je kunt verwachten

Getest over 2020 tot 2026, elk kalenderjaar apart met verse bots van $500 (`python3 backtest.py --from 2020 --to 2026`):

| Jaar | Alleen long, 2% | Alleen long, 5% | Long + short, 2% (standaard) | Long + short, 5% |
|---|---|---|---|---|
| 2020 | +22% | +42% | -1% | -10% |
| 2021 | +24% | +65% | -11% | -7% |
| 2022 | -7% | -8% | -11% | -25% |
| 2023 | +22% | +57% | +7% | +14% |
| 2024 | -0% | -3% | -14% | -26% |
| 2025 | -7% | -15% | -13% | -29% |
| 2026 (t/m nov) | -6% | -11% | -6% | -15% |
| **Gemiddeld** | **+7%** | **+18%** | **-7%** | **-14%** |
| Noodstop geraakt | 0 van 21 | 0 van 21 | 0 van 21 | 9 van 21 |

Met risico per munt (BTC 2%, ETH 5%, SOL 10%, de standaard) en 10% voor alle munten:

| Jaar | Alleen long, BTC 2 / ETH 5 / SOL 10 | Alleen long, alles 10% | Long + short, BTC 2 / ETH 5 / SOL 10 |
|---|---|---|---|
| 2020 | +18% | +69% | -12% |
| 2021 | +167% | +173% | -16% |
| 2022 | -3% | -13% | -16% |
| 2023 | +21% | +25% | +1% |
| 2024 | -7% | -16% | -27% |
| 2025 | -12% | -18% | -22% |
| 2026 (t/m nov) | -17% | -27% | -12% |
| **Gemiddeld** | **+24%** | **+28%** | **-15%** |
| Noodstop geraakt | 5 van 21 | 12 van 21 | 10 van 21 |

Het gemiddelde van +24% komt bijna helemaal uit één jaar: SOL in 2021 (+451%, toen SOL zelf meer dan 100x steeg). Zonder 2021 is het gemiddelde ongeveer 0%, tegenover ongeveer +10% met 5% voor alle munten. De SOL-bot op 10% raakte in elk jaar van 2022 tot 2026 de noodstop. Ook in 2023, een sterk jaar voor SOL, verdiende hij met 10% minder (+30%) dan met 5% (+128%), omdat hij onderweg werd stilgelegd.

Wat dit betekent:

- **Shorten kost geld.** In elk van de 7 jaren deed long + short het slechter dan alleen long. De bots zitten met shorts vaak fout. Gebruik `--no-short`.
- **Alleen long verdient vooral in stijgende jaren** (2020, 2021, 2023), maar veel minder dan kopen en houden. Zo deed BTC kopen en houden in 2020 +303% en de bot +31%. In dalende jaren verliest de bot wel veel minder: in 2022 -7% tegenover -65% tot -94% voor kopen en houden.
- **De laatste twee jaar (2025-2026) zijn negatief**, ook met alleen long. Een groot deel van de winst komt uit de sterke stijgingsjaren 2020-2023. Of dat zich herhaalt, weet niemand.
- **Het resultaat hangt niet af van de precieze stop-loss.** Met 1,5x, 2x of 3x de dagbeweging is alleen long steeds positief (+5% tot +21% per jaar) en long + short steeds negatief (-4% tot -13%). Test zelf met `--stop-mult`.
- **De modellen scoren rond 0**, dus niet beter dan gokken. De winst komt van de eenvoudige strategieën en de risicoregels, niet van voorspellen.
- **De 5x hefboom wordt meestal niet gebruikt.** Bij 2% of 5% risico en een stop van een paar procent blijft de positie onder 1,6x. De hefboom is alleen een plafond.

Een eerdere versie had een vaste stop-loss van 2% en beoordeelde strategieën zonder stop-loss. Die verloor gemiddeld 9% (alleen long) tot 21% (long + short) per jaar, doordat gewone schommelingen bijna elke trade uitstopten.

Laat de bots eerst lang op paper draaien voordat je aan echt geld denkt. Echte handel zit er bewust niet in. Als die ooit wordt toegevoegd: gebruik API-sleutels zonder opnamerechten en alleen geld dat je kunt missen.

## Tests

```bash
python3 -m unittest discover -s tests
```

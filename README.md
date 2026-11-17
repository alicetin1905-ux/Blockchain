# Leerbots

Drie zelflerende trading-bots voor **Bitcoin, Ethereum en Solana**. Ze handelen vanzelf op live Binance-koersen, maar alleen met **nep-geld (paper trading)**. Er worden geen orders naar een beurs gestuurd en je hebt geen API-sleutels nodig.

Standaard werkt elke bot zo:
- hij krijgt **$500**;
- hij kan **long en short**, zoals op een Binance USDT-futures account;
- hij heeft **hoogstens één positie tegelijk**;
- hij riskeert **maximaal 2% van zijn geld per trade**, met een hefboom van hoogstens 5x.

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
  - `--risk 2`: max verlies per trade in %;
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
python3 backtest.py --risk 5 --leverage 3
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
- Oude resultaten vervagen (discount 0,995, ongeveer 8 dagen geheugen), zodat de bot zich aanpast als de markt omslaat.
- Elke 6 candles kiest de bot de strategie met de hoogste *ondergrens*: het gemiddelde min de onzekerheid. Is geen strategie aantoonbaar beter dan niets doen, dan blijft hij in cash.
- Hij wisselt alleen als de verwachte winst de kosten van de wissel dekt.

**5. Eén positie per munt.** Een positie wordt in één keer geopend en in één keer gesloten. De bot koopt niet bij en bouwt niet half af. Draait de strategie van long naar short, dan sluit hij eerst de long en opent daarna de short.

**6. Positiegrootte en risico per trade.** De bot kiest de grootste positie waarbij een geraakte stop-loss, inclusief fees en slippage, hoogstens het ingestelde risico kost:

```
positie = risico / (2% stop-loss + 0,14% kosten), nooit meer dan de hefboom
  2% risico   -> 0,93x je geld  ($467 bij $500)
  5% risico   -> 2,34x
 10% risico   -> 4,67x
```

**7. Risicoregels** (`leerbots/risk.py`). Deze staan buiten het lerende deel, dus de bot kan ze niet "wegleren".
- stop-loss bij 2% koersbeweging tegen de positie in (onder de instap bij long, erboven bij short), daarna 6 candles afkoelen;
- liquidatie wordt gesimuleerd. Bij 5x is dat ongeveer 19,6% tegen je in, en dan is de inleg weg. De stop-loss moet dat voorkomen, maar bij een plotselinge koerssprong (gat) kan het toch gebeuren;
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

De bots hebben in de tests **geen betrouwbaar voordeel** laten zien. Zo ziet `python3 backtest.py --periods 4` eruit, met vier aparte periodes van 180 dagen (november 2024 tot november 2026), $500 per bot:

| Instelling | Gemiddeld per periode | Noodstop geraakt |
|---|---|---|
| Alleen long, 10% risico | -16% | 12 van 12 keer |
| Alleen long, 2% risico | -5% | 0 van 12 keer |
| Long en short, 10% risico | -21% | 12 van 12 keer |
| Long en short, 5% risico | -13% | 9 van 12 keer |
| **Long en short, 2% risico (standaard)** | **-12%** | 2 van 12 keer |

- **Shorten hielp in deze test niet.** De strategieën verloren op shorts ongeveer even vaak als op longs, en meer trades betekent meer kosten.
- **Hoger risico per trade is vooral gokken.** Met 10% raakt elke bot vroeg of laat de noodstop.
- **De modellen scoren rond 0**, dus niet beter dan gokken. De strategiekiezer merkt dat en volgt ze dan weinig.
- **De 5x hefboom wordt bij 2% risico niet gebruikt.** De positie blijft dan onder 1x. De hefboom is alleen een plafond.
- Laat de bots eerst lang op paper draaien voordat je aan echt geld denkt. Echte handel zit er bewust niet in. Als die ooit wordt toegevoegd: gebruik API-sleutels zonder opnamerechten en alleen geld dat je kunt missen.

## Tests

```bash
python3 -m unittest discover -s tests
```

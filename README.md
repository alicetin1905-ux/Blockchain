# Leerbots

Drie zelflerende trading-bots voor **Bitcoin, Ethereum en Solana**. Ze handelen vanzelf op live Binance-koersen, maar alleen met **nep-geld (paper trading)**. Er worden geen orders naar een beurs gestuurd en je hebt geen API-sleutels nodig.

Standaard werkt elke bot zo:
- hij krijgt **$500**;
- hij handelt **alleen long**, zoals op een Binance USDT-futures account (shorten kan met `--short`, maar kostte in de tests geld);
- hij heeft **hoogstens één positie tegelijk**;
- hij riskeert per trade maximaal **5% van zijn geld**, met een hefboom van hoogstens 5x;
- hij gaat alleen long als de munt **boven zijn 50-daags gemiddelde** staat (dagtrend).

De simulatie rekent futures-fees, **echte Binance funding rates** en liquidatie mee.

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
  - `--risk 5`: max verlies per trade in % voor alle munten, of per munt zoals `--risk BTC=2,ETH=5,SOL=10`;
  - `--short`: ook shorten;
  - `--reset`: alles vergeten;
  - `--interval 15m`: andere candle-grootte;
  - `--port 8080`;
  - `--host 0.0.0.0`: dashboard ook vanaf andere apparaten bereikbaar;
  - `--set trend_days=0,trailing_stop=aan,max_total_risk=0.03`: elke instelling uit `leerbots/config.py` aanpassen.
- Verander je startgeld, hefboom, risico of interval, dan beginnen de bots automatisch opnieuw.

Voor 24/7 laat je het draaien op een pc die aan blijft, een Raspberry Pi of een kleine VPS, bijvoorbeeld met `nohup python3 run.py &`, `tmux` of een systemd-service.

## Backtest

```bash
python3 backtest.py                   # 180 dagen traden na 60 dagen opwarmen, uurcandles
python3 backtest.py --periods 4       # 4 aparte periodes van 180 dagen: is het resultaat stabiel?
python3 backtest.py --risk 5 --leverage 3   # 5% risico voor alle munten
python3 backtest.py --risk BTC=2,ETH=5,SOL=10
python3 backtest.py --from 2020 --to 2026 # elk kalenderjaar apart, met verse bots
python3 backtest.py --short               # ook shorten
python3 backtest.py --stop-mult 3         # ruimere stop-loss (3x de dagbeweging)
python3 backtest.py --from 2020 --to 2023 --set trailing_stop=aan   # een verbetering apart testen
```

De bots leren tijdens de test gewoon door en zien nooit de toekomst: elke beslissing gebruikt alleen data van vóór dat moment. Ook funding rates tellen pas mee vanaf het moment dat ze bekend waren.

**Eerlijk testen:** ontwikkel en vergelijk op **2020 tot 2023** (`--from 2020 --to 2023`) en test pas aan het eind, één keer, op **2024 tot 2026**. Wie op dezelfde jaren blijft bijstellen, krijgt resultaten die mooier lijken dan ze zijn.

## Hoe de zelflerende modus werkt

Elke munt heeft een eigen bot met een eigen nep-portemonnee. Per afgesloten candle doet de bot dit:

```
candle ──► signalen ──► 2 modellen leren bij ──► strategieën ──► strategiekiezer ──► risicoregels ──► paper trade
              │            ▲                          │                ▲
              │            └─ uitkomst 6 candles later └─ virtuele winst/verlies per strategie, met dezelfde regels
              └─ ETH en SOL kijken ook naar BTC; funding rates als extra signaal
```

**1. Signalen** (`leerbots/features.py`):
- koersverandering over 1, 3, 12 en 48 candles;
- beweeglijkheid en RSI;
- afstand tot de EMA20 en EMA50;
- volume ten opzichte van normaal;
- candlevorm en tijdstip;
- de funding rate nu en het gemiddelde van de laatste 3 dagen (`leerbots/funding.py`). Een hoge rate betekent dat veel handelaren long zitten met hefboom.

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
- Oude resultaten vervagen (discount 0,998, ongeveer 3 weken geheugen), zodat de bot zich aanpast als de markt omslaat, maar niet op elke schommeling reageert.
- Eén keer per dag (elke 24 candles) kiest de bot de strategie met de hoogste *ondergrens*: het gemiddelde min de onzekerheid. Is geen strategie aantoonbaar beter dan niets doen, dan blijft hij in cash.
- Hij wisselt alleen als de verwachte winst de kosten van de wissel dekt.

**5. Eén positie per munt.** Een positie wordt in één keer geopend en in één keer gesloten. De bot koopt niet bij en bouwt niet half af. Draait de strategie van long naar short, dan sluit hij eerst de long en opent daarna de short.

**6. Dagtrendfilter.** Een strategie mag alleen long gaan als de koers boven het gemiddelde van de laatste 50 dagslotkoersen staat (en alleen short eronder, als shorten aan staat). Ook de virtuele trades volgen dit filter. Uitzetten kan met `--set trend_days=0`.

**7. Stop-loss die meebeweegt met de markt.** De stop-loss ligt op 2x de normale dagbeweging van de munt, berekend uit de laatste 48 candles, met een minimum van 1% en een maximum van 15%. In een rustige markt ligt hij dicht bij de instap, in een wilde markt verder weg. Zo wordt een positie niet door gewone schommelingen uitgestopt.

**8. Positiegrootte en risico per trade.** De bot kiest de grootste positie waarbij een geraakte stop-loss, inclusief fees en slippage, hoogstens het ingestelde risico kost:

```
positie = risico / (stop-afstand + 0,14% kosten), nooit meer dan de hefboom

voorbeelden bij 2% risico:   stop 3%  -> 0,64x je geld   stop 6%  -> 0,33x   stop 10% -> 0,20x
voorbeelden bij 5% risico:   stop 3%  -> 1,59x           stop 6%  -> 0,81x   stop 10% -> 0,49x
```

Ruimere stop betekent een kleinere positie, maar een geraakte stop kost altijd hetzelfde: 2% of 5% van je geld.

**9. Risicoregels** (`leerbots/risk.py`). Deze staan buiten het lerende deel, dus de bot kan ze niet "wegleren".
- de stop-loss en positiegrootte hierboven, daarna 6 candles afkoelen;
- liquidatie wordt gesimuleerd. De stop-loss moet dat voorkomen, maar bij een plotselinge koerssprong (gat) kan het toch gebeuren;
- bij 15% verlies op een dag geen positie meer voor de rest van die dag;
- bij 40% onder de piek stopt de bot tot je hem op het dashboard hervat;
- knop "Stop en sluiten" per bot.

Twee extra's die standaard uitstaan, omdat ze in de tests niet hielpen:
- **trailing stop** (`--set trailing_stop=aan`): de stop schuift mee met de koers;
- **totaalrisico** (`--set max_total_risk=0.03`): het open risico van de drie bots samen blijft onder 3% van al het geld. Nieuwe posities worden zo nodig verkleind. Dit maakt winst én verlies kleiner.

**Kosten**:
- 0,05% futures-fee plus 0,02% slippage per trade;
- funding: de echte rate van Binance, elke 8 uur. Longs betalen een positieve rate, shorts ontvangen die. De geschiedenis komt uit Binance's maandarchieven en de laatste weken uit de live API (fapi.binance.com). Is die niet bereikbaar, dan geldt de laatst bekende rate en meldt het dashboard dat.

Ook de virtuele scores rekenen deze kosten mee. Alle instellingen staan in `leerbots/config.py`.

## Op het dashboard

- **Waarde en resultaat** per bot, vergeleken met gewoon kopen en houden.
- **Grafiek** van de bot tegenover de koers.
- **Positie**: long of short, grootte, instapprijs, open resultaat, stop-loss, liquidatieprijs, wat een stop-loss nu zou kosten, gewonnen tegen verloren trades, de dagtrend en de funding rate.
- **Wat de bot leert**:
  - welke strategie hij volgt;
  - de kans dat elke strategie nu echt de beste is;
  - wat elke strategie nu zou doen (▲ long, ▼ short);
  - de virtuele winst per strategie.
- **Modellen**: kans op stijging en op daling nu, vergeleken met normaal. De score toont of een model beter is dan gokken (boven 0 = beter).
- **Laatste trades** met de reden: welke strategie, of een stop-loss of risicoregel.

## Eerlijk over wat je kunt verwachten

### Verbeteringen stap voor stap (ontwikkeljaren 2020 tot 2023)

Elke regel voegt één verbetering toe aan de regel erboven, alleen long, 5% risico, $500 per bot:

| Stap | 2020 | 2021 | 2022 | 2023 | Gemiddeld | Slechtste jaar |
|---|---|---|---|---|---|---|
| Vorige versie | +42% | +65% | -8% | +57% | +39% | -8% |
| + echte funding (eerlijkere kosten) | +22% | +56% | -8% | +64% | **+33%** | -8% |
| + dagtrendfilter | +31% | +38% | -7% | +62% | +31% | -7% |
| + trailing stop | +18% | +18% | -7% | +35% | +16% | -7% |
| + totaalrisico 8% | +18% | +18% | -7% | +35% | +16% | -7% |
| + funding als signaal | +22% | +18% | -8% | +43% | +19% | -8% |
| + minder wisselen | +27% | +18% | -3% | +62% | +26% | -3% |
| **Gekozen: trendfilter, funding-signaal, minder wisselen (zonder trailing stop)** | +26% | +44% | -2% | +92% | **+40%** | **-2%** |
| Ter vergelijking: 4-uurscandles zonder extra's | +18% | +89% | -6% | +103% | +51% | -6% |

- **Echte funding kost geld.** In 2020 en 2021 betaalden longs vaak veel meer dan de eerder aangenomen 0,01% per 8 uur.
- **De trailing stop kostte de helft van de winst.** Hij stopte winnaars uit bij gewone terugvallen.
- **Totaalrisico 8% veranderde niets.** 5% risico per bot is 5% van die bot zijn eigen $500, dus samen hoogstens 5% van $1500. Een grens wordt pas merkbaar onder 5%, en dan worden winst én verlies kleiner.
- **4-uurscandles** scoorden gemiddeld hoger, maar vooral door één uitschieter (SOL 2021 +256%) en met een slechter slechtste jaar. Daarom is gekozen voor de gelijkmatiger variant op uurcandles.

### De test op de apart gehouden jaren (2024 tot 2026)

Pas na de keuze één keer getest:

| Jaar | Vorige versie | Vorige versie + echte funding | **Nieuwe versie** |
|---|---|---|---|
| 2024 | -3% | -1% | **+1%** |
| 2025 | -15% | -14% | **-19%** |
| 2026 (t/m nov) | -11% | -12% | **-4%** |
| **Gemiddeld** | -10% | -9% | **-7%** |
| Slechtste jaar | -15% | -14% | **-19%** |

**De verbeteringen houden op nieuwe data nauwelijks stand.** Het gemiddelde is iets beter (-7% tegen -9%), maar het slechtste jaar is slechter (-19% tegen -14%). Dat verschil valt binnen het toeval. De winst van de ontwikkeljaren kwam vooral uit de sterke stijgingsmarkten van 2020 tot 2023; in 2024 tot 2026 verliezen de bots met en zonder verbeteringen.

Wat verder blijft gelden:
- **Shorten kost geld** (`--short`): in alle geteste jaren deed long + short het slechter dan alleen long.
- **De modellen scoren rond 0**, ook met funding als signaal: niet beter dan gokken.
- **De 5x hefboom wordt meestal niet gebruikt.** Bij 5% risico en een stop van een paar procent blijft de positie onder 1,6x.
- **In dalende markten beschermen de bots goed**, maar ze verliezen nog steeds geld. In stijgende markten pakken ze maar een klein deel van de stijging.

Laat de bots eerst lang op paper draaien voordat je aan echt geld denkt. Echte handel zit er bewust niet in. Als die ooit wordt toegevoegd: gebruik API-sleutels zonder opnamerechten en alleen geld dat je kunt missen.

## Tests

```bash
python3 -m unittest discover -s tests
```

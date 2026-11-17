# Leerbots

Drie zelflerende trading-bots voor **Bitcoin, Ethereum en Solana**. Ze handelen vanzelf op live Binance-koersen, maar alleen met **nep-geld (paper trading)**. Er worden geen orders naar een beurs gestuurd en je hebt geen API-sleutels nodig.

Standaard krijgt elke bot **$500** en handelt hij met maximaal **5x hefboom**, zoals op een Binance USDT-futures account. De simulatie rekent futures-fees, funding en liquidatie mee.

Alles is gewone Python (3.9 of nieuwer), zonder extra pakketten.

## Starten

```bash
python3 run.py
```

Open daarna **http://localhost:8000** voor het dashboard.

- Bij de eerste start leren de bots eerst op de laatste 3000 uurcandles (ongeveer 4 maanden). Ze traden dan nog niet. Dat opwarmen duurt ongeveer een halve minuut.
- Daarna draaien ze live. Elk uur komt er een nieuwe candle binnen, en elke 10 seconden wordt de koers gecontroleerd voor de stop-loss.
- Het geheugen (model, strategiescores, portemonnee) staat in `state/`. Stop je het programma met Ctrl+C en start je het later opnieuw, dan gaan de bots verder waar ze waren. Gemiste candles gebruiken ze alleen om te leren; daarover traden ze niet achteraf.
- Opties: `--capital 500` (startgeld per bot), `--leverage 5` (hefboom, `1` = zonder), `--reset` (alles vergeten), `--interval 15m` (andere candle-grootte), `--port 8080`, `--host 0.0.0.0` (dashboard ook vanaf andere apparaten bereikbaar).
- Verander je startgeld, hefboom of interval, dan beginnen de bots automatisch opnieuw.

Voor 24/7 laat je het draaien op een pc die aan blijft, een Raspberry Pi of een kleine VPS, bijvoorbeeld met `nohup python3 run.py &`, `tmux` of een systemd-service.

## Backtest

```bash
python3 backtest.py                       # 180 dagen traden na 60 dagen opwarmen, uurcandles
python3 backtest.py --interval 15m --days 60 --warmup-days 20
python3 backtest.py --leverage 2          # andere hefboom testen
```

De bots leren tijdens de test gewoon door en zien nooit de toekomst: elke beslissing gebruikt alleen data van vóór dat moment.

## Hoe de zelflerende modus werkt

Elke munt heeft een eigen bot met een eigen nep-portemonnee van $500. Per afgesloten candle doet de bot dit:

```
candle ──► signalen ──► model leert bij ──► strategieën ──► strategiekiezer ──► risicoregels ──► paper trade
              │              ▲                   │                ▲
              │              └─ uitkomst 6 candles later          └─ virtuele winst/verlies per strategie
              └─ ETH en SOL kijken ook naar BTC
```

**1. Signalen** (`leerbots/features.py`): koersverandering over 1, 3, 12 en 48 candles, beweeglijkheid, RSI, afstand tot de EMA20 en EMA50, volume ten opzichte van normaal, candlevorm en tijdstip. ETH en SOL krijgen ook BTC's koersverandering mee.

**2. Voorspellend model** (`leerbots/model.py`): online logistische regressie. Het schat de kans dat de koers binnen 6 candles meer stijgt dan de kosten van een koop en verkoop samen. Zodra die 6 candles voorbij zijn, weet het model of het gelijk had en past het zijn gewichten een klein stapje aan. Het leert dus continu, niet één keer vooraf.

**3. Strategieën** (`leerbots/strategies.py`): trend volgen, terugveren (RSI), uitbraak, het model volgen, of cash. Alleen long: kopen of niet, zonder shorten en zonder hefboom.

**4. Strategiekiezer** (`leerbots/bandit.py`), de eigenlijke zelfleer-laag. Elke candle krijgt elke strategie een virtuele score: wat ze ná kosten verdiend zou hebben, ook als de bot haar niet volgt. Oude resultaten vervagen (discount 0,995, ongeveer 8 dagen geheugen), zodat de bot zich aanpast als de markt omslaat. Elke 6 candles kiest de bot de strategie met de hoogste *ondergrens* (gemiddelde min de onzekerheid). Is geen strategie aantoonbaar beter dan niets doen, dan blijft hij in cash. Hij wisselt ook alleen als de verwachte winst de kosten van de wissel dekt.

**5. Hefboom**: de strategie bepaalt óf de bot in de munt zit; de hefboom bepaalt hoe groot. Bij 5x opent de bot met $500 een positie van $2.500. Elke 1% koersbeweging is dan 5% van je geld. Alleen long, geen shorten.

**6. Risicoregels** (`leerbots/risk.py`): deze staan buiten het lerende deel, dus de bot kan ze niet "wegleren".
- stop-loss bij 2% koersdaling onder de instapprijs (bij 5x is dat 10% van je geld), daarna 6 candles afkoelen;
- liquidatie wordt gesimuleerd: bij 5x ongeveer 19,6% koersdaling, en dan is de inleg weg. De stop-loss moet dat voorkomen, maar bij een plotselinge koerssprong (gat) kan het toch gebeuren;
- bij 15% verlies op een dag geen positie meer voor de rest van die dag;
- bij 40% onder de piek stopt de bot tot je hem op het dashboard hervat;
- nooit meer dan de ingestelde hefboom;
- knop "Stop en sluiten" per bot.

**Kosten**: 0,05% futures-fee plus 0,02% slippage per trade, en funding van gemiddeld 0,01% per 8 uur over de positiegrootte zolang die open staat. Ook de virtuele scores rekenen dit mee. In werkelijkheid schommelt funding, en kan die bij veel vraag naar longs flink hoger zijn.

Alle instellingen staan in `leerbots/config.py`.

## Op het dashboard

- **Waarde en resultaat** per bot, vergeleken met gewoon kopen en houden.
- **Grafiek** van de bot tegenover de koers.
- **Wat de bot leert**: welke strategie hij volgt, de kans dat elke strategie nu echt de beste is, de gemiddelde virtuele winst per candle in basispunten, en het totaal.
- **Modelscore**: is het model beter dan gokken? Het dashboard vergelijkt het met "altijd hetzelfde antwoord". Een score boven 0 betekent beter dan gokken.
- **Laatste trades** met de reden: welke strategie, of een stop-loss of risicoregel.

## Eerlijk over wat je kunt verwachten

- Crypto-koersen zijn grotendeels onvoorspelbaar. In de tests scoort het model meestal rond 0, dus nauwelijks beter dan gokken. De strategiekiezer merkt dat en negeert het model dan.
- In de backtests (180 dagen uurcandles, dalende markt) verloren de bots veel minder dan kopen en houden, vooral doordat ze vaak in cash bleven. In een stijgende markt blijven ze daardoor waarschijnlijk achter bij kopen en houden.
- Hefboom vergroot winst én verlies. Dezelfde backtest met $500 per bot:

  | Hefboom | Totaal 3 bots | BTC | ETH | SOL | Grootste daling |
  |---|---|---|---|---|---|
  | 1x | +6,5% | +10,4% | +1,0% | +8,1% | 11 tot 15% |
  | 2x | +10,3% | +19,0% | +0,1% | +11,9% | 21 tot 29% |
  | 3x | -4,3% | +27,7% | -2,8% | -37,7% | 29 tot 40% |
  | 5x | +5,7% | +42,6% | +10,8% | -36,3% | alle drie ~40%: noodstop geraakt |

  Bij 5x raakten alle drie de bots de noodstop (40% onder de piek). Het totaal hing dus vooral af van geluk in de volgorde van winst en verlies. Eén periode zegt bovendien weinig.
- Korte candles (5 minuten) kostten in tests veel meer aan fees dan ze opleverden. Daarom is 1 uur de standaard.
- Laat de bots eerst weken op paper draaien voordat je aan echt geld denkt. Echte handel zit er bewust niet in. Als die ooit wordt toegevoegd: gebruik API-sleutels zonder opnamerechten en alleen geld dat je kunt missen.

## Tests

```bash
python3 -m unittest discover -s tests
```

# ChainScout

Dashboard om DexScreener-tokens te volgen, te filteren op veiligheid en met paper trading te testen. Het is één bestand (`index.html`) zonder build, backend of API-sleutels.

## Starten

Open `index.html` in je browser, of serveer de map:

```bash
python3 -m http.server 8080   # daarna http://localhost:8080
```

De browser haalt data rechtstreeks op bij DexScreener, honeypot.is, GoPlus en RugCheck. Zonder internet of in een omgeving die die hosts blokkeert, schakelt de app zelf over op **Demo-modus** met gesimuleerde tokens.

## Wat het doet

- **Tokennetwerk.** Elk token is een lichtgevend knooppunt rond het gekozen blok. Gevalideerde tokens zitten dichtbij het blok met bewegende transactiepuntjes, afgekeurde zweven verder weg. Grootte is liquiditeit. Klik op een knooppunt voor details. Op de achtergrond drijft een plexus van knooppunten in twee lagen.
- **Tokenbronnen.** DexScreener-profielen en -boosts, plus nieuwe en trending pools van GeckoTerminal. Elk token toont waar het vandaan komt, en je kunt op bron filteren. Boosts zijn betaalde promotie, nieuwe en trending pools zijn onafhankelijk. Bij Instellingen zet je elke bron aan of uit.
- **Keten van scans.** Elke scan wordt een blok met hash, vorige hash, Merkle-root van de tokens en een kleine proof-of-work. Klik op een blok om de tokens (transacties) erin te zien. "Controleer keten" herberekent alle hashes.
- **Filters.** Liquiditeit, volume, transacties, leeftijd, marktcap, koersmomentum, koop/verkoop-balans, liq/mcap, wash-trading, socials, tax, grootste holder, LP-lock, mint en owner-risico. Presets: Veilig, Gebalanceerd, Degen. Elk token krijgt een score van 0 tot 100.
- **Honeypot- en rugcheck.**
  - EVM (ETH, BSC, Base, Arbitrum, Polygon, Avalanche, Optimism): honeypot.is koop/verkoop-simulatie plus GoPlus (tax, mint, verborgen eigenaar, LP-lock, holders, eerdere honeypots van de maker).
  - Solana: GoPlus (mint, freeze, transfer fee, holders) plus RugCheck.
  - Altijd: markt-heuristieken op DexScreener-data, zoals geen verkopen, liquiditeit die verdwijnt, dump of pump, wash trading en extreem dunne pools.
  - Andere ketens krijgen alleen de markt-heuristieken.
- **Paper trading.** Startkapitaal $10.000. Prijsimpact volgt uit de pool-liquiditeit, daarbij komen 0,3% swapfee, gas en de gemeten buy/sell tax. De koersen van open posities verversen elke 4 seconden (instelbaar bij Instellingen), met resultaat in procenten en dollars. Take profit, stop loss, trailing stop en een rug-alarm dat uitstapt als de liquiditeit wegvalt, controleren in hetzelfde ritme. Optioneel een auto-trader die alleen gevalideerde tokens koopt. Honeypots worden altijd geblokkeerd.
- **Grootboek.** Elke trade is een blok in een eigen hash-keten.

## Let op

De checks helpen bij het sorteren en zijn geen garantie. Nieuwe tokens kunnen binnen minuten veranderen, en een audit-API kan een token nog niet kennen. Alle trades zijn gesimuleerd en er wordt niets met een wallet gedaan. Gegevens staan in `localStorage` van je browser.

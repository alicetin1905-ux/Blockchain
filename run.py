#!/usr/bin/env python3
"""Start de drie zelflerende paper-trading bots en het dashboard.

    python3 run.py              # daarna http://localhost:8000
    python3 run.py --reset      # alles vergeten en opnieuw beginnen
"""
import argparse
import logging
import threading
import time

from leerbots.app import App
from leerbots.config import INTERVAL_MS, Settings
from leerbots.server import make_server


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1", help="adres van het dashboard (standaard alleen deze pc)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--interval", default="1h", choices=list(INTERVAL_MS), help="candle-grootte (standaard 1h)")
    ap.add_argument("--capital", type=float, default=500, help="nep-startgeld per bot in USD (standaard 500)")
    ap.add_argument("--leverage", type=float, default=5, help="maximale hefboom (standaard 5)")
    ap.add_argument("--warmup", type=int, default=3000, help="candles geschiedenis om op te leren bij de start")
    ap.add_argument("--poll", type=float, default=10, help="seconden tussen koerscontroles")
    ap.add_argument("--state", default="state", help="map waar de bots hun geheugen opslaan")
    ap.add_argument("--reset", action="store_true", help="opgeslagen bots negeren en opnieuw beginnen")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    log = logging.getLogger("leerbots")

    app = App(Settings(interval=args.interval, start_capital=args.capital, leverage=args.leverage),
              args.state, args.warmup)
    server = make_server(app, args.host, args.port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("Dashboard: http://%s:%d  (PAPER TRADING, geen echt geld)", args.host, args.port)

    app.start(reset=args.reset)
    log.info("Live. Elke %gs koersen controleren (stop-loss), elke %s een nieuwe candle.", args.poll, args.interval)
    try:
        while True:
            app.poll_once()
            time.sleep(args.poll)
    except KeyboardInterrupt:
        log.info("Stoppen; staat opslaan...")
        with app.lock:
            app.save()


if __name__ == "__main__":
    main()

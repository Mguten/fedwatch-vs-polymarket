"""Modul 7: LIVE-notisfunktion — kollar dagligen om något FOMC-mötes ledande
utfallsnivå (STRATEGY.md §3-4) kvalificerar för entry, och skickar en
Telegram-notis om så är fallet.

Datakälla för p (vår sannolikhet): investing.com/central-banks/fed-rate-monitor
(fedwatch.livesource.investing) — INTE ZQ-kontraktspipelinen. Det är ett
medvetet val (se RAPPORT.md/konversationen): ZQ-kontraktsdata är svår att
få tag på löpande, medan investing.com är en fritt tillgänglig, dagsaktuell
sida. Se den modulens docstring för den metodologiska skillnaden och
ToS-reservationen kring att scrapa den.

OBS: detta är en annan datakälla än den som backtestades i STRATEGY.md §8
(som använde vår egen ZQ-baserade motor). Siffrorna i den tabellen gäller
alltså inte nödvändigtvis exakt för den här live-varianten — se den
kommande valideringen (RAPPORT.md/konversationen) för hur mycket de skiljer
sig åt.

Miljövariabler som krävs:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  — se README för hur man skaffar dem.
Valfria:
    NOTIFY_THRESHOLD_PCT (default 60.0)   — tröskeln T i STRATEGY.md §4.
    NOTIFY_WINDOW_DAYS (default 90)       — tidsfönstret i STRATEGY.md §2.

Användning:
    python run_notify.py
"""

import logging
import os
import sys
from datetime import date

from fedwatch.config import PROJECT_ROOT
from fedwatch.fomc.dates import get_fomc_meetings
from fedwatch.fomc.decisions import fetch_fred_series
from fedwatch.livesource.investing import (
    fetch_fed_rate_monitor_html,
    local_steps_from_cumulative,
    parse_fed_rate_monitor,
)
from fedwatch.notify import (
    filter_new_signals,
    find_leading_level_signals,
    format_signal_message,
    load_notify_state,
    save_notify_state,
    send_telegram_message,
)
from fedwatch.polymarket import (
    fetch_confirmed_current_prices,
    fetch_fed_decision_events,
    load_confirmed_matches,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_notify")

STATE_PATH = PROJECT_ROOT / "output" / "notify_state.json"
DEFAULT_THRESHOLD_PCT = 60.0
DEFAULT_WINDOW_DAYS = 90


def main() -> None:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        logger.error(
            "TELEGRAM_BOT_TOKEN och/eller TELEGRAM_CHAT_ID saknas i miljön. "
            "Se README för hur man skaffar dem. Avbryter."
        )
        sys.exit(1)

    threshold_pct = float(os.environ.get("NOTIFY_THRESHOLD_PCT", DEFAULT_THRESHOLD_PCT))
    window_days = int(os.environ.get("NOTIFY_WINDOW_DAYS", DEFAULT_WINDOW_DAYS))
    today = date.today()

    logger.info("=== Hämtar aktuell target-rate (FRED) ===")
    upper_series = fetch_fred_series("DFEDTARU")
    lower_series = fetch_fred_series("DFEDTARL")
    current_upper = float(upper_series.iloc[-1])
    current_lower = float(lower_series.iloc[-1])

    logger.info("=== Hämtar Fed Rate Monitor (investing.com) ===")
    html = fetch_fed_rate_monitor_html()
    cumulative = parse_fed_rate_monitor(html)
    fedfunds_local = local_steps_from_cumulative(cumulative, current_upper, current_lower)

    logger.info("=== Hämtar aktuella Polymarket-priser ===")
    meetings = get_fomc_meetings()
    events = fetch_fed_decision_events()
    confirmed = load_confirmed_matches()
    polymarket_current = fetch_confirmed_current_prices(confirmed, events)

    logger.info("=== Letar efter kvalificerande signaler (T=%.1f%%, fönster=%d dagar) ===", threshold_pct, window_days)
    signals = find_leading_level_signals(
        fedfunds_local, polymarket_current, threshold_pct=threshold_pct, window_days=window_days, as_of=today,
    )

    state = load_notify_state(STATE_PATH)
    new_signals, updated_state = filter_new_signals(signals, state, as_of=today)
    save_notify_state(updated_state, STATE_PATH)

    if new_signals.empty:
        logger.info("Inga nya signaler idag.")
        return

    for _, row in new_signals.iterrows():
        message = format_signal_message(row)
        send_telegram_message(bot_token, chat_id, message)
        logger.info("Notis skickad för möte %s.", row["meeting_date"])


if __name__ == "__main__":
    main()

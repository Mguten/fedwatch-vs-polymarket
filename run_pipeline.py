"""Kör hela fedwatch-pipelinen end-to-end för ett givet watch_date.

Modul 4 (CME-validering) är pausad — cmegroup.com blockerar programmatisk
åtkomst (403, se fedwatch/validation/README.md). Modul 5:s matchningstabell
kräver ett manuellt granskningssteg (se spec) — kör skriptet en första gång
för att generera config/polymarket_fomc_match_review.csv, granska filen
för hand (fyll i TRUE/FALSE i kolumnen 'confirmed'), kör sedan igen för att
även få ut Modul 6:s jämförelsedata.

Användning:
    python run_pipeline.py [YYYY-MM-DD]   # watch_date, default: idag
"""

import logging
import sys
from datetime import date, datetime

from fedwatch.comparison import build_fedfunds_local_time_series, compare_fedfunds_vs_polymarket
from fedwatch.config import PROJECT_ROOT
from fedwatch.deconvolution import run_deconvolution
from fedwatch.fomc.dates import get_fomc_meetings
from fedwatch.ingestion import load_all_contracts
from fedwatch.polymarket import (
    build_match_review_table,
    fetch_fed_decision_events,
    fetch_confirmed_market_histories,
    load_confirmed_matches,
    save_review_table,
)
from fedwatch.polymarket.matching import REVIEW_TABLE_PATH

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_pipeline")

OUTPUT_DIR = PROJECT_ROOT / "output"


def main(watch_date: date) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    logger.info("=== Modul 1: Data ingestion ===")
    contracts = load_all_contracts()

    logger.info("=== Modul 2: FOMC-mötesdatum ===")
    meetings = get_fomc_meetings()

    logger.info("=== Modul 3: Deconvolution (watch_date=%s) ===", watch_date)
    fedfunds = run_deconvolution(watch_date, meetings, contracts)
    fedfunds_path = OUTPUT_DIR / f"fedfunds_probabilities_{watch_date}.csv"
    fedfunds.to_csv(fedfunds_path, index=False)
    logger.info("Sparade FedFunds-sannolikheter till %s", fedfunds_path)

    logger.info("=== Modul 4: PAUSAD (se fedwatch/validation/README.md) ===")

    logger.info("=== Modul 5: Polymarket — discovery + matchning ===")
    events = fetch_fed_decision_events()
    review_table = build_match_review_table(events, meetings)
    save_review_table(review_table)

    try:
        confirmed = load_confirmed_matches()
    except (FileNotFoundError, ValueError) as exc:
        logger.warning(
            "%s\n\n>>> Granska %s för hand (fyll i TRUE/FALSE i kolumnen 'confirmed') "
            "och kör skriptet igen för att få ut Modul 6:s jämförelsedata. <<<",
            exc, REVIEW_TABLE_PATH,
        )
        return

    logger.info("=== Modul 6: Jämförelse mot Polymarket ===")
    polymarket_history = fetch_confirmed_market_histories(confirmed, events)
    fedfunds_ts = build_fedfunds_local_time_series(
        watch_dates=sorted(polymarket_history["date"].unique()),
        meetings=meetings,
        contracts=contracts,
    )
    comparison = compare_fedfunds_vs_polymarket(fedfunds_ts, polymarket_history)
    comparison_path = OUTPUT_DIR / "fedfunds_vs_polymarket.csv"
    comparison.to_csv(comparison_path, index=False)
    logger.info("Sparade jämförelsedata till %s", comparison_path)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        watch_date_arg = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    else:
        watch_date_arg = date.today()
    main(watch_date_arg)

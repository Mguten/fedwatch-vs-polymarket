"""Kör hela fedwatch-pipelinen end-to-end för ett givet watch_date.

Modul 5:s matchningstabell kräver ett manuellt granskningssteg — kör
skriptet en första gång för att generera
config/polymarket_fomc_match_review.csv, granska filen för hand (fyll i
TRUE/FALSE i kolumnen 'confirmed'), kör sedan igen för att även få ut
Modul 6:s jämförelsedata.

Modul 4 (CME-validering) kör ~250 motorkörningar (en per historiskt
observationsdatum i Data/FedMeeting_*.csv) och tar ~30-40 sekunder.
Hoppa över med --skip-validation vid snabbare iteration.

Användning (kör från repo-roten):
    python scripts/run_pipeline.py [YYYY-MM-DD] [--skip-validation]
"""

import logging
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
from fedwatch.validation import load_all_cme_meeting_histories, validate_against_cme

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_pipeline")

OUTPUT_DIR = PROJECT_ROOT / "output"


def main(watch_date: date, skip_validation: bool = False) -> None:
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

    if skip_validation:
        logger.info("=== Modul 4: hoppar över (--skip-validation) ===")
    else:
        logger.info("=== Modul 4: Validering mot CME:s historik ===")
        try:
            cme_history = load_all_cme_meeting_histories()
            validation = validate_against_cme(cme_history, meetings, contracts)
            summary_path = OUTPUT_DIR / "cme_validation_summary.csv"
            validation["per_meeting_summary"].to_csv(summary_path, index=False)
            logger.info("Sparade valideringssammanfattning till %s", summary_path)
        except FileNotFoundError as exc:
            logger.warning(
                "Ingen CME-historik hittades (%s) — se fedwatch/validation/README.md för hur "
                "man skaffar den. Hoppar över Modul 4.", exc,
            )

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
    args = sys.argv[1:]
    skip_validation_arg = "--skip-validation" in args
    date_args = [a for a in args if a != "--skip-validation"]

    if date_args:
        watch_date_arg = datetime.strptime(date_args[0], "%Y-%m-%d").date()
    else:
        watch_date_arg = date.today()
    main(watch_date_arg, skip_validation=skip_validation_arg)

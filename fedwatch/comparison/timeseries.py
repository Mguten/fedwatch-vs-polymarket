"""Modul 6: bygger FedFunds-motorns sannolikhetsserie över FLERA watch_dates,
så den kan jämföras mot Polymarkets tidsserie (Modul 5).

Kör Modul 3:s deconvolution-motor en gång per önskat observationsdatum.
FRED:s target-rate-serier hämtas EN gång och återanvänds för samtliga
watch_dates (annars ett nätverksanrop per datum) — samma källa som
Modul 2 använder för de facto FOMC-beslut.
"""

import logging
from datetime import date

import pandas as pd

from fedwatch.deconvolution.engine import run_deconvolution
from fedwatch.fomc.decisions import fetch_fred_series

logger = logging.getLogger(__name__)


def build_fedfunds_local_time_series(
    watch_dates: list,
    meetings: pd.DataFrame,
    contracts: pd.DataFrame,
) -> pd.DataFrame:
    """Kör deconvolution-motorn för varje watch_date i watch_dates och
    plockar ut 'local'-raderna (steget vid respektive möte, oberoende av
    tidigare möten — den storhet som är jämförbar med Polymarkets
    möte-för-möte-marknader, se engine.run_deconvolution).

    Output-kolumner: watch_date, meeting_date, local_bp_change,
    fedfunds_probability_pct.
    """
    upper_series = fetch_fred_series("DFEDTARU")
    lower_series = fetch_fred_series("DFEDTARL")

    frames = []
    for watch_date in sorted(watch_dates):
        upper_window = upper_series.loc[: pd.Timestamp(watch_date)]
        lower_window = lower_series.loc[: pd.Timestamp(watch_date)]
        if upper_window.empty or lower_window.empty:
            logger.warning("Ingen FRED-data på eller före %s, hoppar över.", watch_date)
            continue

        try:
            result = run_deconvolution(
                watch_date, meetings, contracts,
                current_rate_upper=float(upper_window.iloc[-1]),
                current_rate_lower=float(lower_window.iloc[-1]),
            )
        except ValueError as exc:
            logger.warning("Deconvolution misslyckades för watch_date=%s: %s", watch_date, exc)
            continue

        local = result[result["row_type"] == "local"][
            ["watch_date", "meeting_date", "local_bp_change", "probability_pct"]
        ].rename(columns={"probability_pct": "fedfunds_probability_pct"})
        frames.append(local)

    if not frames:
        return pd.DataFrame(columns=[
            "watch_date", "meeting_date", "local_bp_change", "fedfunds_probability_pct",
        ])
    return pd.concat(frames, ignore_index=True)

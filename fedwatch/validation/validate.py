"""Modul 4: automatiskt jämförelsetest mot CME:s historiska sannolikheter.

Kör Modul 3:s deconvolution-motor en gång per unikt observationsdatum i
CME:s historik (inte en gång per möte — samma körning ger alla mötens
fördelningar samtidigt) och jämför bin för bin mot CME:s publicerade
siffror. Toleransen (config.CME_VALIDATION_TOLERANCE_PP) är satt INNAN
detta test kördes, inte efteråt utifrån vad som "ser bra ut" — se spec.
"""

import logging

import pandas as pd

from fedwatch.config import CME_VALIDATION_TOLERANCE_PP
from fedwatch.deconvolution.engine import run_deconvolution
from fedwatch.fomc.decisions import fetch_fred_series

logger = logging.getLogger(__name__)


def _run_engine_for_dates(watch_dates, meetings, contracts):
    """Kör motorn en gång per watch_date, återanvänder EN FRED-hämtning för
    samtliga (annars ett nätverksanrop per datum)."""
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
            logger.warning("Deconvolution misslyckades för %s: %s", watch_date, exc)
            continue
        frames.append(result[result["row_type"] == "cumulative"])

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def validate_against_cme(
    cme_history: pd.DataFrame,
    meetings: pd.DataFrame,
    contracts: pd.DataFrame,
    tolerance_pp: float = CME_VALIDATION_TOLERANCE_PP,
) -> dict:
    """Jämför vår motor mot cme_history (se cme_history.load_all_cme_meeting_histories).

    Returnerar {'per_datapoint': DataFrame, 'per_meeting_summary': DataFrame,
    'not_computed': DataFrame}.

    per_datapoint: en rad per (meeting_date, date, rate_low, rate_high) som
    fanns i CME:s data, med vår motsvarande sannolikhet, abs-diff och
    within_tolerance.

    not_computed: (meeting_date, date)-par där CME hade data men vår motor
    inte kunde beräkna något (saknar kontraktsdata/buffert) — redovisas
    separat, jämförs INTE tyst mot implicit 0%.
    """
    watch_dates = cme_history["date"].unique()
    ours = _run_engine_for_dates(watch_dates, meetings, contracts)
    if ours.empty:
        raise ValueError("Motorn producerade inga resultat för något av CME-historikens datum.")

    ours = ours.rename(columns={"watch_date": "date"})[
        ["date", "meeting_date", "rate_low", "rate_high", "probability_pct"]
    ]

    computed_pairs = set(zip(ours["date"], ours["meeting_date"]))
    cme_pairs = cme_history[["date", "meeting_date"]].drop_duplicates()
    not_computed_mask = ~cme_pairs.apply(lambda r: (r["date"], r["meeting_date"]) in computed_pairs, axis=1)
    not_computed = cme_pairs[not_computed_mask].reset_index(drop=True)

    merged = cme_history.merge(
        ours, on=["date", "meeting_date", "rate_low", "rate_high"],
        how="left", suffixes=("_cme", "_ours"),
    )
    merged["probability_pct_ours"] = merged["probability_pct_ours"].fillna(0.0)
    merged["abs_diff_pp"] = (merged["probability_pct_cme"] - merged["probability_pct_ours"]).abs()
    merged["within_tolerance"] = merged["abs_diff_pp"] <= tolerance_pp

    # Uteslut (meeting_date, date)-par där vi inte kunde beräkna NÅGOT —
    # abs_diff_pp där vore missvisande (jämför CME:s riktiga sannolikhet
    # mot en tyst antagen 0%, inte en verklig avvikelse i vår metod).
    computed_mask = merged.apply(lambda r: (r["date"], r["meeting_date"]) in computed_pairs, axis=1)
    evaluable = merged[computed_mask].copy()

    summary = evaluable.groupby("meeting_date").agg(
        n_datapoints=("abs_diff_pp", "size"),
        mean_abs_diff_pp=("abs_diff_pp", "mean"),
        max_abs_diff_pp=("abs_diff_pp", "max"),
        pct_within_tolerance=("within_tolerance", "mean"),
    )
    summary["pct_within_tolerance"] = (summary["pct_within_tolerance"] * 100).round(1)
    summary = summary.reset_index()

    n_flagged = (summary["pct_within_tolerance"] < 95).sum()
    if n_flagged:
        logger.warning(
            "%d möte(n) har <95%% av datapunkterna inom ±%.1fpp-toleransen — "
            "flaggat som känt metodgap, inte dolt. Se per_meeting_summary.",
            n_flagged, tolerance_pp,
        )
    if not not_computed.empty:
        logger.warning(
            "%d (möte, datum)-par kunde inte beräknas alls (saknar kontraktsdata/buffert) "
            "och exkluderades ur toleransjämförelsen — se 'not_computed'.",
            len(not_computed),
        )

    return {
        "per_datapoint": evaluable.drop(columns=["probability"], errors="ignore"),
        "per_meeting_summary": summary,
        "not_computed": not_computed,
    }

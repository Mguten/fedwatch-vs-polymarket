"""Modul 6: jämför P_FedFunds(möte, datum) mot P_Polymarket(möte, datum) och
sparar skillnaden som egen tidsserie.

Scope (se spec): få jämförelsedatan på plats. Djupare analys (korrelation mot
volatilitetsproxy, CPI-datum, etc.) byggs INTE här — se docstring i slutet av
denna fil för var den skulle hakas på.

Jämförelsen görs mot FedFunds-motorns 'local'-fördelning (steget vid just
det specifika mötet, oberoende av tidigare möten sedan watch_date) — inte
den kumulativa CME-konventionen — eftersom det är precis den storhet
Polymarkets möte-för-möte-marknader ("increase by 25bps after the July
meeting?") faktiskt prisar in. Se fedwatch.deconvolution.engine docstring.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def _lookup_tables(fedfunds_ts: pd.DataFrame) -> dict:
    keyed = fedfunds_ts.copy()
    keyed["watch_date"] = pd.to_datetime(keyed["watch_date"])
    keyed["meeting_date"] = pd.to_datetime(keyed["meeting_date"])
    return {
        key: group.set_index("local_bp_change")["fedfunds_probability_pct"]
        for key, group in keyed.groupby(["watch_date", "meeting_date"])
    }


def _fedfunds_probability_for(series: pd.Series, bp_delta: int, open_ended: bool) -> float:
    if series is None:
        return None
    if not open_ended:
        return float(series.get(bp_delta, 0.0))
    if bp_delta >= 0:
        return float(series[series.index >= bp_delta].sum())
    return float(series[series.index <= bp_delta].sum())


def compare_fedfunds_vs_polymarket(fedfunds_ts: pd.DataFrame, polymarket_ts: pd.DataFrame) -> pd.DataFrame:
    """Radvis jämförelse mellan FedFunds-motorns lokala stegfördelning och
    Polymarkets historiska priser, per (möte, datum, bp-utfall).

    fedfunds_ts: kolumner watch_date, meeting_date, local_bp_change,
    fedfunds_probability_pct — se timeseries.build_fedfunds_local_time_series.

    polymarket_ts: kolumner meeting_date, event_id, bp_delta, open_ended,
    date, polymarket_probability_pct — se polymarket.history.
    fetch_confirmed_market_histories.

    Öppna buckets (open_ended=True, t.ex. "50+ bps") jämförs mot FedFunds
    SVANSSUMMA (all sannolikhet på eller bortom bp_delta i samma riktning),
    eftersom Polymarket-marknaden aggregerar svansen till en enda fråga.

    Output-kolumner: meeting_date, date, bp_delta, open_ended, event_id,
    polymarket_probability_pct, fedfunds_probability_pct, probability_diff_pp
    (= polymarket - fedfunds; NaN om inget FedFunds-resultat fanns för det
    datumet/mötet, t.ex. utanför kontraktsdatans täckning).
    """
    lookup = _lookup_tables(fedfunds_ts)

    rows = []
    for _, pm in polymarket_ts.iterrows():
        key = (pd.Timestamp(pm["date"]), pd.Timestamp(pm["meeting_date"]))
        series = lookup.get(key)
        fedfunds_prob = _fedfunds_probability_for(series, int(pm["bp_delta"]), bool(pm["open_ended"]))

        rows.append({
            "meeting_date": pm["meeting_date"],
            "date": pm["date"],
            "bp_delta": pm["bp_delta"],
            "open_ended": pm["open_ended"],
            "event_id": pm["event_id"],
            "question": pm["question"],
            "polymarket_probability_pct": pm["polymarket_probability_pct"],
            "fedfunds_probability_pct": fedfunds_prob,
            "probability_diff_pp": (
                pm["polymarket_probability_pct"] - fedfunds_prob if fedfunds_prob is not None else None
            ),
        })

    result = pd.DataFrame(rows)
    if result.empty:
        return result

    n_unmatched = result["fedfunds_probability_pct"].isna().sum()
    if n_unmatched:
        logger.warning(
            "%d/%d Polymarket-datapunkter saknar en motsvarande FedFunds-körning för samma "
            "(datum, möte) — troligen utanför kontraktsdatans eller watch_dates-fönstrets täckning.",
            n_unmatched, len(result),
        )
    return result.sort_values(["meeting_date", "bp_delta", "date"]).reset_index(drop=True)


# Framtida analys (INTE byggd här, per spec:s uttryckliga scope-avgränsning):
#   - Korrelation mellan probability_diff_pp och en volatilitetsproxy
#     (t.ex. MOVE-index eller ZQ-kontraktens dagliga rörelse).
#   - Jämförelse av probability_diff_pp runt CPI-/sysselsättningsdatum
#     (kräver ett separat datum-dataset som inte finns i denna pipeline än).
#   Bygg detta som en ny funktion i denna modul när den datan finns på plats
#   — inte genom att bygga ut compare_fedfunds_vs_polymarket självt.

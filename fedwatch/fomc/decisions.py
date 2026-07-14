"""Hämtar vilket beslut som faktiskt togs vid varje FOMC-möte.

Istället för att förlita sig på en manuellt underhållen (och snabbt
inaktuell) lista över historiska beslut, härleds beslutet empiriskt ur
FRED:s publika target-rate-serier (DFEDTARU/DFEDTARL — Fed Funds target
range upper/lower bound). Dessa går att hämta som ren CSV utan API-nyckel
via fredgraph.csv, och är alltid aktuella. Beslutet vid ett möte = skillnaden
i target-räntan strax efter mötet jämfört med strax innan.
"""

import logging

import pandas as pd
import requests

logger = logging.getLogger(__name__)

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"


def fetch_fred_series(series_id: str, timeout: int = 15) -> pd.Series:
    """Hämtar en FRED-serie (t.ex. DFEDTARU) som daglig pd.Series indexerad på datum.

    OBS: skicka inte en spoofad browser-User-Agent hit — till skillnad från
    federalreserve.gov (som kräver en för att undvika 403) verkar FRED:s
    bot-skydd tarpitta/hänga anslutningen just när en Chrome-UA kommer från
    en icke-browser TLS-fingeravtryck. Standard-requests-UA fungerar fint.
    """
    url = FRED_CSV_URL.format(series_id=series_id)
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()

    from io import StringIO
    df = pd.read_csv(StringIO(response.text))
    date_col, value_col = df.columns[0], df.columns[1]
    df[date_col] = pd.to_datetime(df[date_col])
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
    return df.set_index(date_col)[value_col].rename(series_id)


def attach_decisions(meetings: pd.DataFrame, lookahead_business_days: int = 3) -> pd.DataFrame:
    """Lägger till decision_bps_upper/lower + rate_before/after på meetings-DataFrame.

    decision_bps_* > 0 => höjning, < 0 => sänkning, 0 => oförändrat.
    NaN om target-raten inte kunde hämtas för de aktuella datumen
    (t.ex. framtida möten som ännu inte skett).
    """
    upper = fetch_fred_series("DFEDTARU")
    lower = fetch_fred_series("DFEDTARL")

    out = meetings.copy()
    rate_before_upper, rate_after_upper = [], []
    rate_before_lower, rate_after_lower = [], []

    for end_date in out["end_date"]:
        before_window = upper.loc[:end_date]
        after_window = upper.loc[end_date:].iloc[: lookahead_business_days + 1]
        rb_u = before_window.iloc[-1] if not before_window.empty else float("nan")
        ra_u = after_window.dropna().iloc[-1] if not after_window.dropna().empty else float("nan")

        before_window_l = lower.loc[:end_date]
        after_window_l = lower.loc[end_date:].iloc[: lookahead_business_days + 1]
        rb_l = before_window_l.iloc[-1] if not before_window_l.empty else float("nan")
        ra_l = after_window_l.dropna().iloc[-1] if not after_window_l.dropna().empty else float("nan")

        rate_before_upper.append(rb_u)
        rate_after_upper.append(ra_u)
        rate_before_lower.append(rb_l)
        rate_after_lower.append(ra_l)

    out["rate_before_upper"] = rate_before_upper
    out["rate_after_upper"] = rate_after_upper
    out["decision_bps_upper"] = (
        (pd.Series(rate_after_upper, index=out.index) - pd.Series(rate_before_upper, index=out.index)) * 100
    ).round().astype("Int64")

    out["rate_before_lower"] = rate_before_lower
    out["rate_after_lower"] = rate_after_lower
    out["decision_bps_lower"] = (
        (pd.Series(rate_after_lower, index=out.index) - pd.Series(rate_before_lower, index=out.index)) * 100
    ).round().astype("Int64")

    n_unknown = int(out["decision_bps_upper"].isna().sum())
    if n_unknown:
        logger.info(
            "%d möte(n) saknar känt beslut ännu (troligen framtida möten utan efterföljande target-ränta).",
            n_unknown,
        )

    return out

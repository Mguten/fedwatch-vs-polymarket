"""Enhetstester för Modul 6:s jämförelselogik (compare_fedfunds_vs_polymarket).

Testar den rena matchnings-/aggregeringslogiken mot syntetisk indata —
nätverksberoende hämtning (Modul 5:s Polymarket-historik, Modul 3:s
FedFunds-tidsserie) testas i respektive moduls egna tester.
"""

from datetime import date

import pandas as pd
import pytest

from fedwatch.comparison.compare import compare_fedfunds_vs_polymarket


def _fedfunds_ts():
    return pd.DataFrame([
        {"watch_date": date(2026, 7, 1), "meeting_date": date(2026, 7, 29), "local_bp_change": 0, "fedfunds_probability_pct": 63.0},
        {"watch_date": date(2026, 7, 1), "meeting_date": date(2026, 7, 29), "local_bp_change": 25, "fedfunds_probability_pct": 37.0},
        {"watch_date": date(2026, 7, 1), "meeting_date": date(2026, 9, 16), "local_bp_change": -25, "fedfunds_probability_pct": 20.0},
        {"watch_date": date(2026, 7, 1), "meeting_date": date(2026, 9, 16), "local_bp_change": 0, "fedfunds_probability_pct": 55.0},
        {"watch_date": date(2026, 7, 1), "meeting_date": date(2026, 9, 16), "local_bp_change": 25, "fedfunds_probability_pct": 20.0},
        {"watch_date": date(2026, 7, 1), "meeting_date": date(2026, 9, 16), "local_bp_change": 50, "fedfunds_probability_pct": 5.0},
    ])


def test_exact_bucket_match_computes_diff():
    fedfunds_ts = _fedfunds_ts()
    polymarket_ts = pd.DataFrame([{
        "meeting_date": date(2026, 7, 29), "event_id": "e1", "question": "No change?",
        "bp_delta": 0, "open_ended": False, "date": date(2026, 7, 1), "polymarket_probability_pct": 65.0,
    }])

    result = compare_fedfunds_vs_polymarket(fedfunds_ts, polymarket_ts)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["fedfunds_probability_pct"] == 63.0
    assert row["probability_diff_pp"] == pytest.approx(2.0)


def test_open_ended_positive_bucket_sums_tail():
    fedfunds_ts = _fedfunds_ts()
    polymarket_ts = pd.DataFrame([{
        "meeting_date": date(2026, 9, 16), "event_id": "e2", "question": "25+ bps hike?",
        "bp_delta": 25, "open_ended": True, "date": date(2026, 7, 1), "polymarket_probability_pct": 30.0,
    }])

    result = compare_fedfunds_vs_polymarket(fedfunds_ts, polymarket_ts)

    # 25+ ska summera bp=25 OCH bp=50 (20.0 + 5.0 = 25.0), inte bara bp=25.
    row = result.iloc[0]
    assert row["fedfunds_probability_pct"] == pytest.approx(25.0)
    assert row["probability_diff_pp"] == pytest.approx(5.0)


def test_open_ended_negative_bucket_sums_tail():
    fedfunds_ts = _fedfunds_ts()
    polymarket_ts = pd.DataFrame([{
        "meeting_date": date(2026, 9, 16), "event_id": "e3", "question": "25+ bps cut?",
        "bp_delta": -25, "open_ended": True, "date": date(2026, 7, 1), "polymarket_probability_pct": 15.0,
    }])

    result = compare_fedfunds_vs_polymarket(fedfunds_ts, polymarket_ts)
    row = result.iloc[0]
    assert row["fedfunds_probability_pct"] == pytest.approx(20.0)


def test_missing_fedfunds_datapoint_yields_nan_not_zero():
    """Om FedFunds-motorn aldrig kördes för det datumet/mötet ska diffen bli
    NaN — INTE tyst tolkas som 0% sannolikhet (vilket skulle ge en falskt
    stor/missvisande diff)."""
    fedfunds_ts = _fedfunds_ts()
    polymarket_ts = pd.DataFrame([{
        "meeting_date": date(2026, 12, 9), "event_id": "e4", "question": "No change?",
        "bp_delta": 0, "open_ended": False, "date": date(2026, 7, 1), "polymarket_probability_pct": 40.0,
    }])

    result = compare_fedfunds_vs_polymarket(fedfunds_ts, polymarket_ts)
    row = result.iloc[0]
    assert pd.isna(row["fedfunds_probability_pct"])
    assert pd.isna(row["probability_diff_pp"])

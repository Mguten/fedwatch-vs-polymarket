"""Enhetstester för Modul 3 (deconvolution engine).

Strategi (se spec: "skriv enhetstester för Modul 3 mot minst 2-3 kända CME
FedWatch-datapunkter innan resten av pipelinen byggs vidare"):

1. Algoritmkorrekthet mot verkliga CME-siffror: vi använder CME:s egen
   publicerade ZQ-kurva och Conditional Meeting Probabilities (extraherade
   ur en skärmdump från användaren, config/cme_validation_*.csv) som
   input/facit — det isolerar "är algoritmen korrekt" från "är vår
   indata färsk", vilket hör hemma i Modul 4 istället.
2. Formelkorrekthet (prispropagering, flermötesmånader) via syntetiska
   fixturer där vi kan verifiera intern konsistens (att den dagviktade
   återkonstruktionen av Pavg stämmer), snarare än handräknade tal som
   lätt blir fel att transkribera.
"""

import calendar
from datetime import date

import pandas as pd
import pytest

from fedwatch.config import CME_VALIDATION_TOLERANCE_PP, PROJECT_ROOT
from fedwatch.deconvolution.engine import _convolve, _local_step_distribution, run_deconvolution
from fedwatch.deconvolution.pricing import MonthRecord, month_avg_price, propagate_prices
from fedwatch.ingestion import load_all_contracts
from fedwatch.fomc.dates import get_fomc_meetings

CONFIG_DIR = PROJECT_ROOT / "config"


# ---------------------------------------------------------------------------
# Fixturer: CME:s egna publicerade referensdata (skärmdump 2026-07-14)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def watch_date():
    return date(2026, 7, 14)


@pytest.fixture(scope="module")
def cme_reference_probabilities():
    df = pd.read_csv(CONFIG_DIR / "cme_validation_probabilities.csv", parse_dates=["meeting_date"])
    df["rate_low"] = df["rate_low"] / 100
    df["rate_high"] = df["rate_high"] / 100
    df["probability_pct"] = df["probability_pct"].fillna(0.0)
    return df


@pytest.fixture(scope="module")
def contracts_for_watch_date(watch_date):
    """Maj/juni 2026 (redan nästan förfallna) från riktig Data/, juli 2026
    och framåt från CME:s egen publicerade kurva — ger en exakt,
    självkonsistent input för att testa algoritmen mot CME:s eget facit.
    """
    real = load_all_contracts()
    past = real[
        (real["contract_year"] == 2026) & (real["contract_month"].isin([5, 6]))
    ].copy()

    validation_curve = pd.read_csv(CONFIG_DIR / "cme_validation_zq_curve.csv", parse_dates=["as_of_date"])
    validation_curve["date"] = validation_curve["as_of_date"]
    validation_curve["volume"] = 0
    validation_curve["open_interest"] = 0
    validation_curve["low_confidence_flag"] = False

    columns = [
        "contract_symbol", "contract_month", "contract_year", "date",
        "close_price", "volume", "open_interest", "low_confidence_flag",
    ]
    return pd.concat([past[columns], validation_curve[columns]], ignore_index=True)


@pytest.fixture(scope="module")
def fomc_meetings():
    return get_fomc_meetings()


@pytest.fixture(scope="module")
def deconvolution_result(watch_date, fomc_meetings, contracts_for_watch_date):
    return run_deconvolution(
        watch_date, fomc_meetings, contracts_for_watch_date,
        current_rate_upper=3.75, current_rate_lower=3.50,
    )


@pytest.fixture(scope="module")
def cumulative_result(deconvolution_result):
    """CME:s egen konvention (ackumulerad förändring sedan watch_date, med
    absoluta rate_low/rate_high) — det som jämförs mot CME:s publicerade
    siffror. Se engine.run_deconvolution docstring för 'local'-radernas syfte.
    """
    return deconvolution_result[deconvolution_result["row_type"] == "cumulative"].reset_index(drop=True)


# ---------------------------------------------------------------------------
# 1. Algoritmkorrekthet mot CME:s publicerade siffror
# ---------------------------------------------------------------------------

def test_next_meeting_matches_cme_binary_split(cumulative_result, cme_reference_probabilities):
    """Det närmaste mötet (2026-07-29) ska ge CME:s exakta binära uppdelning
    (endast två utfall) — detta är det enda mötet som INTE kräver convolution
    med tidigare möten, så det isolerar att steg 1-3+6-7 (E[R], klassificering,
    prispropagering, heltal+mantissa) är korrekt implementerade.
    """
    mine = cumulative_result[cumulative_result["meeting_date"] == date(2026, 7, 29)]
    cme = cme_reference_probabilities[cme_reference_probabilities["meeting_date"] == pd.Timestamp("2026-07-29")]

    assert not mine.empty
    assert (mine["multi_outcome_flag"] == False).all()  # noqa: E712
    assert len(mine) == 2  # exakt två utfall

    merged = mine.merge(cme, on=["rate_low", "rate_high"], suffixes=("_mine", "_cme"))
    diff = (merged["probability_pct_mine"] - merged["probability_pct_cme"]).abs()
    assert (diff <= CME_VALIDATION_TOLERANCE_PP).all(), diff.to_dict()


def test_later_meetings_match_cme_within_tolerance(cumulative_result, cme_reference_probabilities):
    """Möten 2-7 stegs bort (kräver convolution över flera FOMC-möten) ska
    matcha CME:s publicerade "Conditional Meeting Probabilities" inom den i
    Modul 4 fastställda toleransen (±2 procentenheter, satt INNAN testet
    kördes — se config.CME_VALIDATION_TOLERANCE_PP). Detta validerar att
    fler-än-två-utfall-hanteringen (full multi-step convolution) är korrekt,
    inte bara det enskilda binära specialfallet.
    """
    computed_meetings = sorted(cumulative_result["meeting_date"].unique())
    later_meetings = [d for d in computed_meetings if d != date(2026, 7, 29)]
    assert len(later_meetings) >= 2, "Behöver minst 2-3 kända datapunkter utöver det första mötet."

    max_diffs = {}
    for meeting_date in later_meetings:
        mine = cumulative_result[cumulative_result["meeting_date"] == meeting_date]
        cme = cme_reference_probabilities[
            cme_reference_probabilities["meeting_date"] == pd.Timestamp(meeting_date)
        ]
        merged = mine.merge(cme, on=["rate_low", "rate_high"], how="left", suffixes=("_mine", "_cme"))
        merged["probability_pct_cme"] = merged["probability_pct_cme"].fillna(0.0)
        diff = (merged["probability_pct_mine"] - merged["probability_pct_cme"]).abs()
        max_diffs[str(meeting_date)] = diff.max()

        assert (mine["multi_outcome_flag"] == True).all(), meeting_date  # noqa: E712
        assert (diff <= CME_VALIDATION_TOLERANCE_PP).all(), (meeting_date, diff.to_dict())

    # Sanity: vi ska faktiskt ha testat fler-än-två-utfall-fallet, inte bara
    # råkat filtrera bort alla avvikande rader.
    assert any(v > 0 for v in max_diffs.values())


def test_probabilities_sum_to_100_per_meeting(cumulative_result, deconvolution_result):
    cumulative_sums = cumulative_result.groupby("meeting_date")["probability_pct"].sum()
    assert (cumulative_sums.sub(100).abs() < 0.1).all(), cumulative_sums.to_dict()

    local_result = deconvolution_result[deconvolution_result["row_type"] == "local"]
    local_sums = local_result.groupby("meeting_date")["probability_pct"].sum()
    assert (local_sums.sub(100).abs() < 0.1).all(), local_sums.to_dict()


# ---------------------------------------------------------------------------
# 2. Lokal stegfördelning (_local_step_distribution) och convolution
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("change", [0.0, 0.3, 0.6, 1.0, 1.7, -0.4, -2.2])
def test_local_step_distribution_preserves_mean_and_sums_to_one(change):
    dist = _local_step_distribution(change)
    assert sum(dist.values()) == pytest.approx(1.0)
    implied_mean_steps = sum(bp * p for bp, p in dist.items()) / 25
    assert implied_mean_steps == pytest.approx(change, abs=1e-9)


def test_local_step_distribution_zero_mantissa_collapses_to_single_outcome():
    dist = _local_step_distribution(2.0)
    assert dist == {50: 1.0}


def test_convolve_preserves_total_probability_and_sums_means():
    a = _local_step_distribution(0.4)
    b = _local_step_distribution(-1.3)
    combined = _convolve(a, b)
    assert sum(combined.values()) == pytest.approx(1.0)
    mean_a = sum(bp * p for bp, p in a.items())
    mean_b = sum(bp * p for bp, p in b.items())
    mean_combined = sum(bp * p for bp, p in combined.items())
    assert mean_combined == pytest.approx(mean_a + mean_b, abs=1e-9)


# ---------------------------------------------------------------------------
# 3. Prispropagering (pricing.py) — syntetiska fixturer, verifierar intern
#    konsistens (dagviktad återkonstruktion av Pavg) snarare än handräknade
#    tal.
# ---------------------------------------------------------------------------

def _days_in(year, month):
    return calendar.monthrange(year, month)[1]


def _reconstruct_avg(p_start, p_end, meeting_day, year, month):
    days_no = _days_in(year, month)
    m = days_no - meeting_day + 1
    n = days_no - m
    return (n * p_start + m * p_end) / days_no


def test_propagate_single_fomc_month_between_no_fomc_months():
    """Jan (icke-FOMC) -> Feb (FOMC, möte 15:e) -> Mar (icke-FOMC)."""
    jan = MonthRecord(year=2027, month=1, p_avg=98.00)
    feb = MonthRecord(year=2027, month=2, meeting_end_dates=[date(2027, 2, 15)], p_avg=97.80)
    mar = MonthRecord(year=2027, month=3, p_avg=97.60)

    months = propagate_prices([jan, feb, mar])

    assert months[0].p_start == pytest.approx(98.00)
    assert months[0].p_end == pytest.approx(98.00)
    assert months[2].p_start == pytest.approx(97.60)
    assert months[2].p_end == pytest.approx(97.60)

    # Feb ska framåtpropageras från Jan.p_end och bakåt lösas mot Mar.p_start.
    assert months[1].p_start == pytest.approx(98.00)
    assert months[1].p_end == pytest.approx(97.60)

    reconstructed = _reconstruct_avg(months[1].p_start, months[1].p_end, 15, 2027, 2)
    assert reconstructed == pytest.approx(feb.p_avg)


def test_propagate_consecutive_fomc_months_chain():
    """Två FOMC-månader i rad (som verkliga juni/juli 2026): Maj(icke-FOMC)
    -> Jun(FOMC 17:e) -> Jul(FOMC 29:e) -> Aug(icke-FOMC). Kräver att
    framåt-passet löser Jun.Pstart och bakåt-passet löser Jul.Pstart/Jun.Pend
    i rätt ordning.

    Jun:s egen Pavg konsumeras inte i denna kedja (se kommentar i
    pricing.propagate_prices) — brytpunkten mellan Jun och Jul löses
    uteslutande ur Jul:s Pavg/dagviktning. Vi verifierar därför att JUL
    (inte Jun) rekonstruerar korrekt, plus att gränsvärdena hänger ihop.
    """
    may = MonthRecord(year=2026, month=5, p_avg=96.40)
    jun = MonthRecord(year=2026, month=6, meeting_end_dates=[date(2026, 6, 17)], p_avg=96.38)
    jul = MonthRecord(year=2026, month=7, meeting_end_dates=[date(2026, 7, 29)], p_avg=96.37)
    aug = MonthRecord(year=2026, month=8, p_avg=96.28)

    months = propagate_prices([may, jun, jul, aug])

    assert months[1].p_start == pytest.approx(96.40)  # framåtpropagerat från maj
    assert months[2].p_end == pytest.approx(96.28)  # bakåtpropagerat från augusti

    # Jun.p_end (=Jul.p_start) och Jul.p_start ska vara konsistenta med varandra.
    assert months[1].p_end == pytest.approx(months[2].p_start)

    reconstructed_jul = _reconstruct_avg(months[2].p_start, months[2].p_end, 29, 2026, 7)
    assert reconstructed_jul == pytest.approx(jul.p_avg)


def test_multi_meeting_month_is_flagged_and_conserves_average():
    """En kontraktsmånad med två FOMC-möten (spec Modul 3 punkt 5) — inget
    verkligt exempel finns i 2021-2027 FOMC-kalendern, så detta testar
    algebran mot en syntetisk månad. Vi kan inte lösa de interna
    brytpunkterna exakt (se pricing._solve_multi_meeting_month) men
    approximationen måste bevara den dagviktade månadsgenomsnittet exakt
    och flaggas tydligt.
    """
    jan = MonthRecord(year=2027, month=1, p_avg=98.00)
    feb = MonthRecord(
        year=2027, month=2,
        meeting_end_dates=[date(2027, 2, 5), date(2027, 2, 20)],
        p_avg=97.50,
    )
    mar = MonthRecord(year=2027, month=3, p_avg=97.00)

    months = propagate_prices([jan, feb, mar])
    feb_resolved = months[1]

    assert feb_resolved.multi_meeting_month is True
    assert feb_resolved.resolved_via_approximation is True
    assert len(feb_resolved.segment_rates) == 2

    days_no = _days_in(2027, 2)
    boundaries = [feb_resolved.p_start] + feb_resolved.segment_rates
    seg_days = [4, 15, days_no - 19]  # dagar 1-4, 5-19, 20-slut
    weighted_avg = sum(d * r for d, r in zip(seg_days, boundaries)) / days_no
    assert weighted_avg == pytest.approx(feb.p_avg)


# ---------------------------------------------------------------------------
# 4. month_avg_price: förfallna vs aktiva kontrakt
# ---------------------------------------------------------------------------

def test_month_avg_price_uses_last_close_before_watch_date_for_active_contract():
    contracts = pd.DataFrame({
        "contract_symbol": ["ZQF27"] * 3,
        "contract_month": [1, 1, 1],
        "contract_year": [2027, 2027, 2027],
        "date": pd.to_datetime(["2027-01-05", "2027-01-10", "2027-01-20"]),
        "close_price": [98.0, 98.1, 98.2],
    })
    price = month_avg_price(contracts, 2027, 1, date(2027, 1, 12))
    assert price == pytest.approx(98.1)


def test_month_avg_price_uses_month_end_cutoff_for_expired_contract():
    contracts = pd.DataFrame({
        "contract_symbol": ["ZQF27"] * 3,
        "contract_month": [1, 1, 1],
        "contract_year": [2027, 2027, 2027],
        "date": pd.to_datetime(["2027-01-20", "2027-01-29", "2027-02-15"]),
        "close_price": [98.0, 98.1, 999.0],  # sista raden simulerar "orealistiskt" pris efter förfall
    })
    price = month_avg_price(contracts, 2027, 1, date(2027, 3, 1))
    assert price == pytest.approx(98.1)

"""Tester för fedwatch.livesource.investing — parsning av investing.coms
Fed Rate Monitor-sida (alternativ datakälla till ZQ-kontraktspipelinen för
DAGSAKTUELLA sannolikheter, se moduldocstring i fedwatch/livesource/investing.py).

Kör mot en sparad kopia av sidan (tests/fixtures/investing_fed_rate_monitor.html,
hämtad 2026-07-16) snarare än mot internet, så testerna är deterministiska och
inte beroende av investing.coms faktiska innehåll vid testkörning."""

from pathlib import Path

import pytest

from fedwatch.livesource.investing import local_steps_from_cumulative, parse_fed_rate_monitor

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "investing_fed_rate_monitor.html"


@pytest.fixture
def fixture_html() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8", errors="replace")


def test_parse_fed_rate_monitor_extracts_all_meetings(fixture_html):
    result = parse_fed_rate_monitor(fixture_html)

    assert not result.empty
    assert result["meeting_date"].nunique() == 12
    assert list(result.columns) == ["meeting_date", "rate_low", "rate_high", "probability_pct"]


def test_parse_fed_rate_monitor_deduplicates_sidebar_widget(fixture_html):
    # Sidopanelens "Fed Rate Monitor Tool"-widget visar samma närmaste möte
    # som huvudtabellen — utan dedup skulle det mötet få dubblerade rader.
    result = parse_fed_rate_monitor(fixture_html)
    first_meeting = result[result["meeting_date"] == result["meeting_date"].min()]
    assert len(first_meeting) == len(first_meeting.drop_duplicates(subset=["rate_low", "rate_high"]))


def test_parse_fed_rate_monitor_known_values(fixture_html):
    result = parse_fed_rate_monitor(fixture_html)
    import datetime

    first_meeting = result[result["meeting_date"] == datetime.date(2026, 7, 29)]
    probs = dict(zip(zip(first_meeting["rate_low"], first_meeting["rate_high"]), first_meeting["probability_pct"]))
    assert probs[(3.50, 3.75)] == pytest.approx(87.8)
    assert probs[(3.75, 4.00)] == pytest.approx(12.2)

    # Radsumman per möte ska vara ~100% (sannolikhetsfördelning).
    for meeting_date, group in result.groupby("meeting_date"):
        assert group["probability_pct"].sum() == pytest.approx(100.0, abs=0.5), meeting_date


def test_local_steps_from_cumulative_first_meeting_matches_cumulative_when_current_rate_is_lower_bucket(fixture_html):
    # Om nuvarande target-rate exakt sammanfaller med den lägsta bucketen i
    # första mötets kumulativa fördelning ska den lokala fördelningen för det
    # mötet vara identisk med den kumulativa (första steget har ingen
    # historik att skilja ut) — ett bra sanity-check för matematiken.
    cumulative = parse_fed_rate_monitor(fixture_html)
    local = local_steps_from_cumulative(cumulative, current_rate_upper=3.75, current_rate_lower=3.50)

    first_meeting_local = local[local["meeting_ordinal"] == 1]
    probs = dict(zip(first_meeting_local["local_bp_change"], first_meeting_local["probability_pct"]))
    assert probs[0] == pytest.approx(87.8, abs=0.1)
    assert probs[25] == pytest.approx(12.2, abs=0.1)


def test_local_steps_from_cumulative_probabilities_sum_to_100_per_meeting(fixture_html):
    cumulative = parse_fed_rate_monitor(fixture_html)
    local = local_steps_from_cumulative(cumulative, current_rate_upper=3.75, current_rate_lower=3.50)

    for meeting_date, group in local.groupby("meeting_date"):
        assert group["probability_pct"].sum() == pytest.approx(100.0, abs=0.1), meeting_date


def test_parse_fed_rate_monitor_empty_html_returns_empty_frame():
    result = parse_fed_rate_monitor("<html><body>ingenting här</body></html>")
    assert result.empty
    assert list(result.columns) == ["meeting_date", "rate_low", "rate_high", "probability_pct"]


def test_local_steps_from_cumulative_empty_input_returns_empty_frame():
    import pandas as pd

    result = local_steps_from_cumulative(pd.DataFrame(), current_rate_upper=3.75, current_rate_lower=3.50)
    assert result.empty

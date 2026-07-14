"""Enhetstester för Modul 5: bp-parsning av frågetext och matchningstabellens
skyddsmekanismer (ingen ogranskad rad får smygas igenom till Modul 6).

Nätverksanropen mot Polymarket testas inte här (hör hemma i en integrationstest
mot en verklig, tillgänglig tjänst) — detta testar den rena parsnings- och
gatekeeping-logiken.
"""

import pandas as pd
import pytest

from fedwatch.polymarket.discovery import _parse_bp_outcome
from fedwatch.polymarket.matching import build_match_review_table, load_confirmed_matches


@pytest.mark.parametrize("question,expected", [
    ("No change in Fed interest rates after 2024 May meeting?", {"bp_delta": 0, "open_ended": False}),
    ("Fed decreases interest rates by 25 bps after 2024 May meeting?", {"bp_delta": -25, "open_ended": False}),
    ("Fed decreases interest rates by 50+ bps after May 2024 meeting?", {"bp_delta": -50, "open_ended": True}),
    ("Fed raises interest rates by 25+ bps after 2024 May meeting?", {"bp_delta": 25, "open_ended": True}),
    ("Will the Fed increase interest rates by 50+ bps after the July 2026 meeting?", {"bp_delta": 50, "open_ended": True}),
    ("Will the Fed cut rates by 25 bps at the July meeting?", {"bp_delta": -25, "open_ended": False}),
])
def test_parse_bp_outcome_known_phrasings(question, expected):
    assert _parse_bp_outcome(question) == expected


@pytest.mark.parametrize("question", [
    "Will Powell say \"Inflation\" 40+ times during March press conference?",
    "Will two people dissent the January Fed decision?",
    "Powell Bingo: March",
    "Will Christopher Waller dissent the next Fed Decision?",
])
def test_parse_bp_outcome_rejects_non_rate_questions(question):
    assert _parse_bp_outcome(question) is None


def test_load_confirmed_matches_rejects_unreviewed_file(tmp_path):
    unreviewed = pd.DataFrame({
        "event_id": ["1", "2"],
        "event_title": ["Fed decision in July?", "Fed decision in September?"],
        "event_end_date": pd.to_datetime(["2026-07-29", "2026-09-16"]),
        "matched_meeting_date": pd.to_datetime(["2026-07-29", "2026-09-16"]),
        "match_method": ["exact_date", "exact_date"],
        "n_submarkets_total": [4, 4],
        "n_submarkets_parsed": [4, 4],
        "suggested_confirm": [True, True],
        "confirmed": ["", ""],  # ogranskat — ska INTE accepteras
        "notes": ["", ""],
    })
    path = tmp_path / "review.csv"
    unreviewed.to_csv(path, index=False)

    with pytest.raises(ValueError):
        load_confirmed_matches(path)


def test_load_confirmed_matches_only_returns_true_rows(tmp_path):
    reviewed = pd.DataFrame({
        "event_id": ["1", "2", "3"],
        "event_title": ["Fed decision in July?", "Powell Bingo: March", "Fed decision in September?"],
        "event_end_date": pd.to_datetime(["2026-07-29", "2026-03-18", "2026-09-16"]),
        "matched_meeting_date": pd.to_datetime(["2026-07-29", "2026-03-18", "2026-09-16"]),
        "match_method": ["exact_date"] * 3,
        "n_submarkets_total": [4, 1, 4],
        "n_submarkets_parsed": [4, 0, 4],
        "suggested_confirm": [True, False, True],
        "confirmed": ["TRUE", "FALSE", "TRUE"],  # granskat för hand
        "notes": ["", "inte en räntemarknad", ""],
    })
    path = tmp_path / "review.csv"
    reviewed.to_csv(path, index=False)

    confirmed = load_confirmed_matches(path)
    assert set(confirmed["event_id"]) == {1, 3}


def test_build_match_review_table_flags_exact_date_matches_only():
    events = pd.DataFrame({
        "event_id": ["1", "1", "2"],
        "market_id": ["m1", "m2", "m3"],
        "event_title": ["Fed decision in July?", "Fed decision in July?", "Unrelated market"],
        "event_end_date": ["2026-07-29T00:00:00Z", "2026-07-29T00:00:00Z", "2026-08-15T00:00:00Z"],
        "parse_failed": [False, False, True],
    })
    meetings = pd.DataFrame({"end_date": pd.to_datetime(["2026-07-29", "2026-09-16"])})

    table = build_match_review_table(events, meetings)
    row1 = table[table["event_id"] == "1"].iloc[0]
    row2 = table[table["event_id"] == "2"].iloc[0]

    assert row1["match_method"] == "exact_date"
    assert row1["n_submarkets_parsed"] == 2
    assert row2["match_method"] == "none"
    assert pd.isna(row2["matched_meeting_date"])
    # confirmed ska ALDRIG förifyllas av koden — bara en hint i suggested_confirm.
    assert (table["confirmed"] == "").all()

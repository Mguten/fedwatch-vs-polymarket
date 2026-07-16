"""Tester för fedwatch.notify — entry-signalen från STRATEGY.md §4 tillämpad
på live-data, samt state-hanteringen som förhindrar daglig spam för samma
öppna position."""

from datetime import date, timedelta

import pandas as pd
import pytest

from fedwatch.notify.signals import (
    filter_new_signals,
    find_leading_level_signals,
    format_signal_message,
    kelly_fraction,
    suggested_stake_sek,
)

TODAY = date(2026, 7, 16)


def _fedfunds(meeting_date, bp_to_pct):
    return pd.DataFrame([
        {"meeting_date": meeting_date, "local_bp_change": bp, "probability_pct": pct}
        for bp, pct in bp_to_pct.items()
    ])


def _polymarket(meeting_date, bp_to_price, event_id="evt1"):
    return pd.DataFrame([
        {
            "meeting_date": meeting_date, "event_id": event_id, "bp_delta": bp,
            "open_ended": False, "question": f"{bp:+d}bp?", "polymarket_probability_pct": price,
        }
        for bp, price in bp_to_price.items()
    ])


def test_qualifying_leader_is_returned():
    meeting_date = TODAY + timedelta(days=30)
    fedfunds = _fedfunds(meeting_date, {0: 30.0, -25: 70.0})
    polymarket = _polymarket(meeting_date, {0: 35.0, -25: 55.0})

    signals = find_leading_level_signals(fedfunds, polymarket, threshold_pct=60.0, as_of=TODAY)

    assert len(signals) == 1
    row = signals.iloc[0]
    assert row["bp_delta"] == -25
    assert row["fedfunds_probability_pct"] == pytest.approx(70.0)
    assert row["polymarket_probability_pct"] == pytest.approx(55.0)
    assert row["edge_pp"] == pytest.approx(15.0)


def test_leader_below_threshold_is_excluded():
    meeting_date = TODAY + timedelta(days=30)
    fedfunds = _fedfunds(meeting_date, {0: 45.0, -25: 55.0})
    polymarket = _polymarket(meeting_date, {0: 40.0, -25: 50.0})

    signals = find_leading_level_signals(fedfunds, polymarket, threshold_pct=60.0, as_of=TODAY)

    assert signals.empty


def test_leader_without_positive_edge_is_excluded():
    # p >= threshold men p <= P (inget edge) — ska INTE ge en signal (STRATEGY.md §4.2).
    meeting_date = TODAY + timedelta(days=30)
    fedfunds = _fedfunds(meeting_date, {0: 30.0, -25: 65.0})
    polymarket = _polymarket(meeting_date, {0: 35.0, -25: 70.0})

    signals = find_leading_level_signals(fedfunds, polymarket, threshold_pct=60.0, as_of=TODAY)

    assert signals.empty


def test_meeting_outside_window_is_excluded():
    meeting_date = TODAY + timedelta(days=120)
    fedfunds = _fedfunds(meeting_date, {-25: 80.0})
    polymarket = _polymarket(meeting_date, {-25: 50.0})

    signals = find_leading_level_signals(fedfunds, polymarket, threshold_pct=60.0, window_days=90, as_of=TODAY)

    assert signals.empty


def test_past_meeting_is_excluded():
    meeting_date = TODAY - timedelta(days=1)
    fedfunds = _fedfunds(meeting_date, {-25: 80.0})
    polymarket = _polymarket(meeting_date, {-25: 50.0})

    signals = find_leading_level_signals(fedfunds, polymarket, threshold_pct=60.0, as_of=TODAY)

    assert signals.empty


def test_filter_new_signals_first_time_is_new():
    meeting_date = TODAY + timedelta(days=30)
    signals = pd.DataFrame([{
        "meeting_date": meeting_date, "bp_delta": -25, "open_ended": False,
        "event_id": "evt1", "question": "-25bp?",
        "fedfunds_probability_pct": 70.0, "polymarket_probability_pct": 55.0, "edge_pp": 15.0,
    }])

    new_signals, state = filter_new_signals(signals, state={}, as_of=TODAY)

    assert len(new_signals) == 1
    assert state[str(meeting_date)] == "-25|False"


def test_filter_new_signals_same_leader_again_is_not_new():
    meeting_date = TODAY + timedelta(days=30)
    signals = pd.DataFrame([{
        "meeting_date": meeting_date, "bp_delta": -25, "open_ended": False,
        "event_id": "evt1", "question": "-25bp?",
        "fedfunds_probability_pct": 70.0, "polymarket_probability_pct": 55.0, "edge_pp": 15.0,
    }])
    state = {str(meeting_date): "-25|False"}

    new_signals, updated_state = filter_new_signals(signals, state, as_of=TODAY)

    assert new_signals.empty
    assert updated_state == state


def test_filter_new_signals_overtake_is_new():
    # Ledande nivå har bytts sedan senaste notisen (STRATEGY.md §5a) — ska
    # trigga en ny notis trots att mötet redan hade ett notifierat läge.
    meeting_date = TODAY + timedelta(days=30)
    signals = pd.DataFrame([{
        "meeting_date": meeting_date, "bp_delta": 0, "open_ended": False,
        "event_id": "evt1", "question": "0bp?",
        "fedfunds_probability_pct": 65.0, "polymarket_probability_pct": 50.0, "edge_pp": 15.0,
    }])
    state = {str(meeting_date): "-25|False"}

    new_signals, updated_state = filter_new_signals(signals, state, as_of=TODAY)

    assert len(new_signals) == 1
    assert updated_state[str(meeting_date)] == "0|False"


def test_filter_new_signals_clears_past_meetings_from_state():
    past_meeting = TODAY - timedelta(days=5)
    future_meeting = TODAY + timedelta(days=30)
    state = {str(past_meeting): "-25|False", str(future_meeting): "0|False"}

    _, updated_state = filter_new_signals(pd.DataFrame(), state, as_of=TODAY)

    assert str(past_meeting) not in updated_state
    assert str(future_meeting) in updated_state


def test_kelly_fraction_basic():
    # f* = (p-P)/(1-P) = (0.70-0.55)/(1-0.55) = 0.15/0.45
    assert kelly_fraction(70.0, 55.0) == pytest.approx(0.15 / 0.45)


def test_kelly_fraction_clips_to_zero_without_edge():
    # Skyddsklippning om p<=P (ska inte hända givet entry-regeln, men f* ska
    # aldrig bli negativ om funktionen ändå anropas utanför den).
    assert kelly_fraction(50.0, 55.0) == 0.0


def test_suggested_stake_sek_applies_hard_cap():
    # f* = 0.3333, halv-Kelly = 0.1667 -> över taket 10%, ska klippas dit.
    stake, f_star = suggested_stake_sek(
        p_pct=70.0, polymarket_pct=55.0, bankroll_sek=1000.0, kelly_multiplier=0.5, max_stake_pct=10.0,
    )
    assert f_star == pytest.approx(0.15 / 0.45)
    assert stake == pytest.approx(100.0)


def test_suggested_stake_sek_below_cap_uses_fractional_kelly():
    # Litet edge -> halv-Kelly hamnar under taket, ska inte klippas.
    stake, f_star = suggested_stake_sek(
        p_pct=61.0, polymarket_pct=59.0, bankroll_sek=1000.0, kelly_multiplier=0.5, max_stake_pct=10.0,
    )
    expected_f_star = (0.61 - 0.59) / (1 - 0.59)
    assert f_star == pytest.approx(expected_f_star)
    assert stake == pytest.approx(expected_f_star * 0.5 * 1000.0, abs=0.01)


def test_format_signal_message_includes_sizing_when_bankroll_given():
    row = pd.Series({
        "meeting_date": date(2026, 9, 16), "bp_delta": -25, "open_ended": False,
        "question": "-25bp?", "fedfunds_probability_pct": 70.0,
        "polymarket_probability_pct": 55.0, "edge_pp": 15.0,
    })
    message = format_signal_message(row, bankroll_sek=1000.0, kelly_multiplier=0.5, max_stake_pct=10.0)
    assert "Förslag på satsning" in message
    assert "100 kr" in message


def test_format_signal_message_omits_sizing_without_bankroll():
    row = pd.Series({
        "meeting_date": date(2026, 9, 16), "bp_delta": -25, "open_ended": False,
        "question": "-25bp?", "fedfunds_probability_pct": 70.0,
        "polymarket_probability_pct": 55.0, "edge_pp": 15.0,
    })
    message = format_signal_message(row)
    assert "Förslag på satsning" not in message

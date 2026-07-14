"""Enhetstester för Modul 4:s CME-historikparsning (ren logik, inget nätverk).

validate_against_cme testas inte här (kräver FRED-nätverksanrop och är
tungt att köra, ~250 motorkörningar) — verifierat manuellt mot den riktiga
Data/FedMeeting_*.csv-datan: 12/12 möten beräkningsbara, medelavvikelse
0.02-0.4pp, 10/12 möten >=95% av datapunkterna inom ±2pp-toleransen.
"""

from datetime import date

import pandas as pd
import pytest

from fedwatch.validation.cme_history import _parse_bin_label, load_cme_meeting_history


def test_parse_bin_label():
    assert _parse_bin_label("(350-375)") == (350, 375)
    assert _parse_bin_label("(0-25)") == (0, 25)
    assert _parse_bin_label("(1550-1575)") == (1550, 1575)


def test_parse_bin_label_rejects_bad_format():
    with pytest.raises(ValueError):
        _parse_bin_label("350-375")


def test_load_cme_meeting_history_drops_nan_rows_and_converts_units(tmp_path):
    path = tmp_path / "FedMeeting_20260729.csv"
    path.write_text(
        "Date,(350-375),(375-400)\n"
        "2026-07-01,0.6,0.4\n"
        "2026-07-02,,\n"  # inte prissatt ännu — ska hoppas över
    )

    result = load_cme_meeting_history(path)

    assert set(result["date"]) == {date(2026, 7, 1)}
    assert (result["meeting_date"] == date(2026, 7, 29)).all()
    row_375 = result[result["rate_low"] == 3.50].iloc[0]
    assert row_375["rate_high"] == pytest.approx(3.75)
    assert row_375["probability_pct"] == pytest.approx(60.0)


def test_load_cme_meeting_history_rejects_bad_filename(tmp_path):
    path = tmp_path / "not_a_meeting_file.csv"
    path.write_text("Date,(0-25)\n2026-01-01,1.0\n")
    with pytest.raises(ValueError):
        load_cme_meeting_history(path)


def test_load_cme_meeting_history_handles_fully_empty_file(tmp_path):
    path = tmp_path / "FedMeeting_20271208.csv"
    path.write_text("Date,(0-25),(25-50)\n")
    result = load_cme_meeting_history(path)
    assert result.empty

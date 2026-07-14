"""Modul 4: läser in CME:s egna historiska sannolikhets-CSV-filer.

Format (en fil per möte, `Data/FedMeeting_<YYYYMMDD>.csv`): en rad per
observationsdatum, en kolumn per 25bp-band i absolut ränta, t.ex.
"(350-375)" = 3.50-3.75%. Sannolikheter anges som andelar (0-1), summerar
till 1.0 per rad (där data finns — möten långt fram i tiden har tomma rader
innan CME börjar prisa in dem).

`Data/FedMeetingHistory_<YYYYMMDD>.csv` är samma data konsoliderad i ett
enda bredare (multi-möte) format och används INTE här — FedMeeting_*.csv
per möte är enklare att validera mot och innehåller samma information.
"""

import logging
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from fedwatch.config import DATA_DIR

logger = logging.getLogger(__name__)

MEETING_FILE_RE = re.compile(r"^FedMeeting_(\d{8})\.csv$", re.IGNORECASE)
BIN_LABEL_RE = re.compile(r"^\((\d+)-(\d+)\)$")


def _parse_bin_label(label: str) -> tuple:
    match = BIN_LABEL_RE.match(label.strip())
    if not match:
        raise ValueError(f"Oväntat bin-format: '{label}'")
    return int(match.group(1)), int(match.group(2))


def load_cme_meeting_history(path: Path) -> pd.DataFrame:
    """Läser en FedMeeting_<YYYYMMDD>.csv till tidy long-format.

    Output-kolumner: meeting_date, date, rate_low, rate_high, probability_pct.
    NaN-rader (möte ännu inte prissatt av CME på det datumet) hoppas över.
    """
    match = MEETING_FILE_RE.match(path.name)
    if not match:
        raise ValueError(f"Filnamn matchar inte FedMeeting_<YYYYMMDD>.csv: {path.name}")
    meeting_date = datetime.strptime(match.group(1), "%Y%m%d").date()

    raw = pd.read_csv(path)
    if raw.empty:
        return pd.DataFrame(columns=["meeting_date", "date", "rate_low", "rate_high", "probability_pct"])

    bin_columns = [c for c in raw.columns if c != "Date"]
    long = raw.melt(id_vars="Date", value_vars=bin_columns, var_name="bin_label", value_name="probability")
    long = long.dropna(subset=["probability"])
    if long.empty:
        return pd.DataFrame(columns=["meeting_date", "date", "rate_low", "rate_high", "probability_pct"])

    bins = long["bin_label"].apply(_parse_bin_label)
    long["rate_low"] = [b[0] / 100 for b in bins]
    long["rate_high"] = [b[1] / 100 for b in bins]
    long["date"] = pd.to_datetime(long["Date"]).dt.date
    long["meeting_date"] = meeting_date
    long["probability_pct"] = long["probability"] * 100

    return long[["meeting_date", "date", "rate_low", "rate_high", "probability_pct"]].reset_index(drop=True)


def load_all_cme_meeting_histories(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """Läser samtliga FedMeeting_<YYYYMMDD>.csv i data_dir och slår ihop dem."""
    files = sorted(p for p in data_dir.iterdir() if MEETING_FILE_RE.match(p.name))
    if not files:
        raise FileNotFoundError(f"Inga FedMeeting_<YYYYMMDD>.csv-filer hittades i {data_dir}")

    frames = []
    for path in files:
        df = load_cme_meeting_history(path)
        if df.empty:
            logger.info("%s: inga datapunkter ännu (mötet ligger för långt fram).", path.name)
            continue
        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=["meeting_date", "date", "rate_low", "rate_high", "probability_pct"])

    combined = pd.concat(frames, ignore_index=True)
    logger.info(
        "Läste %d CME-historikfiler, %d datapunkter över %d möten (%s till %s).",
        len(files), len(combined), combined["meeting_date"].nunique(),
        combined["date"].min(), combined["date"].max(),
    )
    return combined

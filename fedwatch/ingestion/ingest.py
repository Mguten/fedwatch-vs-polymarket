"""Modul 1: Data ingestion för ZQ (Fed Funds futures) CSV-filer.

Läser samtliga ZQ<månadskod><år>.csv-filer i Data/, parsar kontraktsmånad/år
ur filnamnet, och bygger en enhetlig DataFrame. Rader med Volume == 0 OCH
Open Interest under en konfigurerbar tröskel flaggas som low_confidence
(behålls i output, raderas inte) — se spec Modul 1.
"""

import logging
import re
from pathlib import Path

import pandas as pd

from fedwatch.config import DATA_DIR, DEFAULT_OI_LOW_CONFIDENCE_THRESHOLD

logger = logging.getLogger(__name__)

# CME-månadskoder.
MONTH_CODES = {
    "F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
    "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12,
}

FILENAME_RE = re.compile(r"^ZQ([FGHJKMNQUVXZ])(\d{2})\.csv$", re.IGNORECASE)

EXPECTED_COLUMNS = [
    "Date Time", "Open", "High", "Low", "Close", "Change", "Volume", "Open Interest",
]


def parse_contract_filename(path: Path) -> tuple[str, int, int]:
    """Parsar '<månadskod><år>' ur filnamnet till (symbol, month, year).

    T.ex. ZQF22.csv -> ("ZQF22", 1, 2022).
    """
    match = FILENAME_RE.match(path.name)
    if not match:
        raise ValueError(f"Filnamn matchar inte förväntat ZQ<månadskod><år>-mönster: {path.name}")

    month_code, year_suffix = match.group(1).upper(), match.group(2)
    month = MONTH_CODES[month_code]
    year = 2000 + int(year_suffix)
    symbol = f"ZQ{month_code}{year_suffix}"
    return symbol, month, year


def load_contract_file(
    path: Path,
    oi_low_confidence_threshold: int = DEFAULT_OI_LOW_CONFIDENCE_THRESHOLD,
) -> pd.DataFrame:
    """Läser en enskild ZQ-kontraktsfil till standardiserad DataFrame.

    Filerna har en metadatarad (Symbol: ...), en header-rad, datarader,
    och ibland en fotnotsrad ("Downloaded from Barchart.com...") eller
    är helt tomma ("No data to export"). Fotnotsrader/tomma filer
    hoppas över med en varning i loggen snarare än att krascha pipelinen.
    """
    symbol, month, year = parse_contract_filename(path)

    raw = pd.read_csv(
        path,
        skiprows=1,  # hoppa över "Symbol: ZQ<X><YY>"-metadataraden
        header=0,
        dtype=str,
        keep_default_na=False,
    )

    if list(raw.columns[: len(EXPECTED_COLUMNS)]) != EXPECTED_COLUMNS:
        raise ValueError(
            f"Oväntad kolumnstruktur i {path.name}: {list(raw.columns)}"
        )

    raw = raw[EXPECTED_COLUMNS]

    dates = pd.to_datetime(raw["Date Time"], format="%Y-%m-%d", errors="coerce")
    valid_mask = dates.notna()
    n_invalid = (~valid_mask).sum()
    if n_invalid:
        logger.debug(
            "%s: hoppar över %d rad(er) som inte kunde tolkas som datum "
            "(fotnot/tom fil, t.ex. 'No data to export').",
            path.name, n_invalid,
        )

    if valid_mask.sum() == 0:
        logger.warning("%s innehåller inga giltiga datarader — hoppar över.", path.name)
        return pd.DataFrame(columns=[
            "contract_symbol", "contract_month", "contract_year", "date",
            "close_price", "volume", "open_interest", "low_confidence_flag",
        ])

    clean = raw.loc[valid_mask].copy()
    clean["date"] = dates.loc[valid_mask]

    close_price = pd.to_numeric(clean["Close"], errors="coerce")
    volume = pd.to_numeric(clean["Volume"].replace("", "0"), errors="coerce").fillna(0)
    open_interest = pd.to_numeric(clean["Open Interest"].replace("", "0"), errors="coerce").fillna(0)

    low_confidence_flag = (volume == 0) & (open_interest < oi_low_confidence_threshold)
    n_low_confidence = int(low_confidence_flag.sum())
    if n_low_confidence:
        logger.info(
            "%s: %d/%d rader flaggade som low_confidence (Volume==0 och OI<%d).",
            path.name, n_low_confidence, len(clean), oi_low_confidence_threshold,
        )

    return pd.DataFrame({
        "contract_symbol": symbol,
        "contract_month": month,
        "contract_year": year,
        "date": clean["date"].values,
        "close_price": close_price.values,
        "volume": volume.values,
        "open_interest": open_interest.values,
        "low_confidence_flag": low_confidence_flag.values,
    })


def load_all_contracts(
    data_dir: Path = DATA_DIR,
    oi_low_confidence_threshold: int = DEFAULT_OI_LOW_CONFIDENCE_THRESHOLD,
) -> pd.DataFrame:
    """Läser samtliga ZQ*.csv-filer i data_dir till en sammanslagen DataFrame."""
    # glob är skiftlägeskänsligt på Linux, och några filer i Data/ har .CSV
    # (versaler) — matcha alla ZQ*.csv/.CSV oavsett skiftläge, deduplicerat.
    files = sorted({p for p in data_dir.iterdir() if FILENAME_RE.match(p.name)})
    if not files:
        raise FileNotFoundError(f"Inga ZQ<månadskod><år>.csv-filer hittades i {data_dir}")

    frames = []
    for path in files:
        try:
            frames.append(load_contract_file(path, oi_low_confidence_threshold))
        except ValueError as exc:
            logger.warning("Hoppar över %s: %s", path.name, exc)

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values(["contract_year", "contract_month", "date"]).reset_index(drop=True)
    logger.info(
        "Läste in %d kontraktsfiler, %d rader totalt (%d low_confidence).",
        len(files), len(combined), int(combined["low_confidence_flag"].sum()),
    )
    return combined

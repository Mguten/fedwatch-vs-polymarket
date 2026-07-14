"""Modul 2: FOMC-mötesdatum.

Hämtar FOMC-mötesschema dynamiskt från Federal Reserves egen kalendersida.
Om skrapningen misslyckas (sidan ändrar struktur, blockerar bots, etc.)
faller vi tillbaka till en manuellt underhållen statisk CSV
(config/fomc_dates.csv) istället för att krascha hela pipelinen.
"""

import logging
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from fedwatch.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FALLBACK_CSV = PROJECT_ROOT / "config" / "fomc_dates.csv"

# federalreserve.gov svarar 403 på tomma/bot-liknande User-Agents.
_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

_STATEMENT_LINK_RE = re.compile(r"monetary(\d{8})[a-z]?\d*\.(?:htm|pdf)$", re.IGNORECASE)
_YEAR_HEADING_RE = re.compile(r"(\d{4})\s+FOMC Meetings", re.IGNORECASE)
_NOTATION_VOTE_RE = re.compile(r"^(\d+)\s*\(notation vote\)$", re.IGNORECASE)
_DAY_RANGE_RE = re.compile(r"^(\d+)(?:-(\d+))?$")

_MEETING_COLUMNS = [
    "start_date", "end_date", "meeting_type", "has_projection_materials", "source",
]


def _month_name_to_num(name: str) -> int:
    name = name.strip()
    for fmt in ("%B", "%b"):
        try:
            return datetime.strptime(name, fmt).month
        except ValueError:
            continue
    raise ValueError(f"Okänt månadsnamn i FOMC-kalendern: '{name}'")


def _parse_meeting_row(month_text: str, date_text: str, year: int) -> dict:
    has_projection_materials = "*" in date_text
    date_clean = date_text.replace("*", "").strip()

    notation_match = _NOTATION_VOTE_RE.match(date_clean)
    if notation_match:
        meeting_type = "notation_vote"
        day1 = day2 = int(notation_match.group(1))
    else:
        meeting_type = "regular"
        day_match = _DAY_RANGE_RE.match(date_clean)
        if not day_match:
            raise ValueError(f"Kunde inte tolka datumfält: '{date_text}'")
        day1 = int(day_match.group(1))
        day2 = int(day_match.group(2)) if day_match.group(2) else day1

    months = [m.strip() for m in month_text.split("/")]
    start_month = _month_name_to_num(months[0])
    end_month = _month_name_to_num(months[-1])

    start_year = year
    end_year = year
    if end_month < start_month:
        # T.ex. ett möte som sträcker sig december -> januari.
        end_year = year + 1

    return {
        "start_date": date(start_year, start_month, day1),
        "end_date": date(end_year, end_month, day2),
        "meeting_type": meeting_type,
        "has_projection_materials": has_projection_materials,
    }


def parse_fomc_calendar(html: str) -> pd.DataFrame:
    """Parsar HTML från federalreserve.gov/monetarypolicy/fomccalendars.htm."""
    soup = BeautifulSoup(html, "html.parser")

    rows = []
    for heading in soup.find_all("h4"):
        link = heading.find("a")
        if link is None:
            continue
        year_match = _YEAR_HEADING_RE.search(link.get_text(strip=True))
        if not year_match:
            continue
        year = int(year_match.group(1))

        panel = heading.find_parent(class_="panel")
        if panel is None:
            continue

        for meeting_div in panel.find_all(class_="fomc-meeting"):
            month_el = meeting_div.find(class_="fomc-meeting__month")
            date_el = meeting_div.find(class_="fomc-meeting__date")
            if month_el is None or date_el is None:
                continue

            month_text = month_el.get_text(strip=True)
            date_text = date_el.get_text(strip=True)
            try:
                parsed = _parse_meeting_row(month_text, date_text, year)
            except ValueError as exc:
                logger.warning("Hoppar över orolig FOMC-mötesrad (%s %s): %s", month_text, date_text, exc)
                continue

            # Statement-länkens filnamn (monetary<YYYYMMDD>...) är en exakt
            # källa för mötets sista dag/beslutsdag — föredra den framför
            # den textparsade datumtexten om den finns och avviker.
            for a in meeting_div.find_all("a", href=True):
                link_match = _STATEMENT_LINK_RE.search(a["href"])
                if link_match:
                    link_date = datetime.strptime(link_match.group(1), "%Y%m%d").date()
                    if link_date != parsed["end_date"]:
                        logger.debug(
                            "Justerar end_date för möte %s %s %d: textparsning gav %s, "
                            "statement-länk ger %s. Använder länkdatumet.",
                            month_text, date_text, year, parsed["end_date"], link_date,
                        )
                        parsed["end_date"] = link_date
                    break

            parsed["source"] = "scrape"
            rows.append(parsed)

    if not rows:
        raise ValueError("Ingen FOMC-mötesdata kunde extraheras ur sidans HTML-struktur.")

    df = pd.DataFrame(rows, columns=_MEETING_COLUMNS)
    df["start_date"] = pd.to_datetime(df["start_date"])
    df["end_date"] = pd.to_datetime(df["end_date"])
    df = df.drop_duplicates(subset=["start_date", "end_date"]).sort_values("start_date").reset_index(drop=True)
    return df


def fetch_fomc_calendar_html(url: str = CALENDAR_URL, timeout: int = 15) -> str:
    response = requests.get(url, headers=_REQUEST_HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.text


def _load_fallback(fallback_path: Path) -> pd.DataFrame:
    if not fallback_path.exists():
        raise FileNotFoundError(
            f"Ingen fallback-fil hittades på {fallback_path}. "
            "Skrapning misslyckades och det finns ingen statisk reservlista."
        )
    df = pd.read_csv(fallback_path, parse_dates=["start_date", "end_date"])
    df["source"] = "fallback_csv"
    return df[_MEETING_COLUMNS]


def get_fomc_meetings(
    calendar_url: str = CALENDAR_URL,
    fallback_path: Path = FALLBACK_CSV,
) -> pd.DataFrame:
    """Hämtar FOMC-mötesdatum: skrapning i första hand, statisk CSV som fallback.

    Kolumner: start_date, end_date, meeting_type (regular/notation_vote),
    has_projection_materials, source (scrape/fallback_csv).
    """
    try:
        html = fetch_fomc_calendar_html(calendar_url)
        df = parse_fomc_calendar(html)
        logger.info("Hämtade %d FOMC-möten via skrapning av %s.", len(df), calendar_url)
        return df
    except Exception as exc:  # skrapningen kan fela på många olika sätt (nätverk, 403, HTML-ändring)
        logger.warning("Skrapning av FOMC-kalendern misslyckades (%s). Faller tillbaka till %s.", exc, fallback_path)
        df = _load_fallback(fallback_path)
        logger.info("Läste %d FOMC-möten från fallback-CSV.", len(df))
        return df


def save_fallback_snapshot(df: pd.DataFrame, fallback_path: Path = FALLBACK_CSV) -> None:
    """Sparar en aktuell skrapning som ny fallback-snapshot (körs manuellt/periodiskt)."""
    fallback_path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out["source"] = "fallback_csv"
    out.to_csv(fallback_path, index=False)
    logger.info("Sparade %d FOMC-möten till fallback-snapshot %s.", len(out), fallback_path)

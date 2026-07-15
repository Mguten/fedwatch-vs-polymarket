"""Modul 5: matchar Polymarket-events mot FOMC-möten (Modul 2) och bygger
den manuella verifieringstabell som spec kräver.

Automatisk textmatchning på frågeformuleringar är felbenäget (spec:s egna
ord) — därför är ALLT denna modul producerar en KANDIDATTABELL som måste
granskas för hand (fylla i kolumnen `confirmed`) innan Modul 6 använder den.
load_confirmed_matches vägrar användas av en ogranskad fil.
"""

import logging
from pathlib import Path

import pandas as pd

from fedwatch.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

REVIEW_TABLE_PATH = PROJECT_ROOT / "config" / "polymarket_fomc_match_review.csv"


def build_match_review_table(
    polymarket_events: pd.DataFrame,
    meetings: pd.DataFrame,
    min_parsed_submarkets: int = 1,
    require_match: bool = True,
) -> pd.DataFrame:
    """Bygger en kandidatmatchning event <-> FOMC-möte, en rad per event.

    Matchningsmetod: exakt datum-likhet mellan eventets endDate och ett
    mötes end_date (t.ex. Polymarket-event 'Fed Decision in July?' med
    endDate=2026-07-29 mot FOMC-mötet 2026-07-29). Events utan exakt
    datum-träff får matched_meeting_date=NaT.

    min_parsed_submarkets: events med FÄRRE tolkade bp-submarknader än
    detta utesluts helt ur granskningstabellen (default 1). Detta är INTE
    en genväg runt manuell granskning av MATCHNING — det är bara att events
    som "Powell Bingo: March", dissent-räknare eller
    press-conference-ordräkningar strukturellt saknar bp_delta helt och
    hållet och därmed inte kan bidra någon sannolikhetsdata till Modul 6,
    oavsett om matchningen mot ett mötesdatum råkar stämma.

    require_match: utesluter events UTAN exakt datum-träff (default True).
    Nyckelordssökningen ("Fed", "interest rate") ger falska positiva från
    ANDRA centralbanker (ECB, Bank of Japan, Bank of Israel, ...) vars
    marknader råkar vara strukturerade likadant och därför tolkas fint som
    bp-submarknader — men de matchar inget FOMC-mötesdatum och kan därför
    ALDRIG användas av load_confirmed_matches ändå (den kräver
    matched_meeting_date). Att lista dem ger bara fler rader utan poäng.

    Sätt båda till 0/False om du vill se ALLA kandidater oberedda (t.ex.
    för att dubbelkolla att inget relevant filtrerades bort av misstag).
    """
    if polymarket_events.empty:
        return pd.DataFrame(columns=[
            "event_id", "event_title", "event_end_date", "matched_meeting_date",
            "match_method", "n_submarkets_total", "n_submarkets_parsed",
            "suggested_confirm", "confirmed", "notes",
        ])

    events = polymarket_events.drop_duplicates(subset=["event_id"]).copy()
    events["event_end_date_only"] = pd.to_datetime(events["event_end_date"]).dt.date

    meeting_dates = set(meetings["end_date"].dt.date)

    submarket_counts = polymarket_events.groupby("event_id").agg(
        n_submarkets_total=("market_id", "count"),
        n_submarkets_parsed=("parse_failed", lambda s: int((~s).sum())),
    )

    rows = []
    for _, event in events.iterrows():
        end_date = event["event_end_date_only"]
        matched = end_date if end_date in meeting_dates else None
        counts = submarket_counts.loc[event["event_id"]]
        n_parsed = int(counts["n_submarkets_parsed"])
        rows.append({
            "event_id": event["event_id"],
            "event_title": event["event_title"],
            "event_end_date": end_date,
            "matched_meeting_date": matched,
            "match_method": "exact_date" if matched else "none",
            "n_submarkets_total": int(counts["n_submarkets_total"]),
            "n_submarkets_parsed": n_parsed,
            # Enbart en HEURISTISK fingervisning för att snabba upp granskningen
            # (matchat datum + minst 3 tolkade bp-submarknader) — INTE en
            # automatisk bekräftelse. Kolumnen 'confirmed' måste ändå fyllas
            # i för hand, se load_confirmed_matches.
            "suggested_confirm": bool(matched and n_parsed >= 3),
            "confirmed": "",  # fylls i FÖR HAND: TRUE/FALSE
            "notes": "",
        })

    table = pd.DataFrame(rows).sort_values(["matched_meeting_date", "event_title"], na_position="last")

    before_filter = len(table)
    table = table[table["n_submarkets_parsed"] >= min_parsed_submarkets]
    n_dropped_unparsed = before_filter - len(table)
    if n_dropped_unparsed:
        logger.info(
            "Uteslöt %d/%d event ur granskningstabellen: färre än %d tolkade bp-submarknader "
            "(t.ex. dissent-räknare, Powell Bingo, ordräkningsmarknader — strukturellt "
            "oanvändbara för Modul 6 oavsett matchning).",
            n_dropped_unparsed, before_filter, min_parsed_submarkets,
        )

    if require_match:
        before_match_filter = len(table)
        table = table[table["matched_meeting_date"].notna()]
        n_dropped_unmatched = before_match_filter - len(table)
        if n_dropped_unmatched:
            logger.info(
                "Uteslöt %d event ur granskningstabellen: inget exakt FOMC-mötesdatum "
                "(troligen andra centralbanker som ECB/BoJ/BoI som nyckelordssökningen "
                "råkade fånga upp — kan aldrig användas av load_confirmed_matches ändå).",
                n_dropped_unmatched,
            )

    table = table.reset_index(drop=True)
    n_matched = table["matched_meeting_date"].notna().sum()
    logger.info(
        "Byggde granskningstabell: %d rader kvar (%d matchade ett FOMC-mötesdatum exakt). "
        "MÅSTE granskas för hand (kolumn 'confirmed') innan Modul 6 använder resultatet.",
        len(table), n_matched,
    )
    return table


def save_review_table(table: pd.DataFrame, path: Path = REVIEW_TABLE_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(path, index=False)
    logger.info("Sparade granskningstabell till %s — granska och fyll i 'confirmed' innan produktion.", path)


def load_confirmed_matches(path: Path = REVIEW_TABLE_PATH) -> pd.DataFrame:
    """Läser den MANUELLT GRANSKADE tabellen och returnerar endast rader där
    confirmed==TRUE. Kräver att kolumnen 'confirmed' faktiskt fyllts i —
    vägrar tysta anta att en ogranskad match är korrekt.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Ingen granskningstabell hittades på {path}. Kör build_match_review_table + "
            "save_review_table, granska filen för hand, och försök igen."
        )
    table = pd.read_csv(path, parse_dates=["matched_meeting_date"])
    confirmed_col = table["confirmed"].astype(str).str.strip().str.upper()
    n_reviewed = (confirmed_col.isin(["TRUE", "FALSE"])).sum()
    if n_reviewed == 0:
        raise ValueError(
            f"{path} verkar inte ha granskats än (kolumnen 'confirmed' är tom för alla rader). "
            "Fyll i TRUE/FALSE per rad för hand innan detta används i Modul 6."
        )
    confirmed = table[confirmed_col == "TRUE"].copy()
    logger.info("Läste %d bekräftade Polymarket<->FOMC-matchningar av %d granskade rader.", len(confirmed), n_reviewed)
    return confirmed

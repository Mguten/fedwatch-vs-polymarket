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


def build_match_review_table(polymarket_events: pd.DataFrame, meetings: pd.DataFrame) -> pd.DataFrame:
    """Bygger en kandidatmatchning event <-> FOMC-möte, en rad per event.

    Matchningsmetod: exakt datum-likhet mellan eventets endDate och ett
    mötes end_date (t.ex. Polymarket-event 'Fed Decision in July?' med
    endDate=2026-07-29 mot FOMC-mötet 2026-07-29). Events utan exakt
    datum-träff får matched_meeting_date=NaT och måste granskas manuellt
    eller uteslutas.
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
    n_matched = table["matched_meeting_date"].notna().sum()
    logger.info(
        "Byggde granskningstabell: %d/%d events matchade ett FOMC-mötesdatum exakt. "
        "MÅSTE granskas för hand (kolumn 'confirmed') innan Modul 6 använder resultatet.",
        n_matched, len(table),
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

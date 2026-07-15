"""Modul 5: hämtar historiska sannolikhetsserier för bekräftade
(manuellt granskade) Polymarket-submarknader."""

import logging
from datetime import datetime, timezone

import pandas as pd

from fedwatch.polymarket.client import get_price_history

logger = logging.getLogger(__name__)


def fetch_confirmed_market_histories(confirmed_matches: pd.DataFrame, polymarket_events: pd.DataFrame) -> pd.DataFrame:
    """För varje bekräftad match: hämta historisk prisserie per submarknad
    (=bp-utfall) och platta ut till en tidsserie-DataFrame.

    Output-kolumner: meeting_date, event_id, bp_delta, open_ended, date,
    polymarket_probability_pct.
    """
    # event_id kan komma som antingen str (direkt från Polymarkets JSON-API)
    # eller int64 (efter en CSV-tur-och-retur via granskningsfilen) — matcha
    # på strängform så en dtype-skillnad inte tyst ger noll träffar.
    events = polymarket_events.copy()
    events["event_id"] = events["event_id"].astype(str)
    confirmed = confirmed_matches.copy()
    confirmed["event_id"] = confirmed["event_id"].astype(str)

    submarkets = events[
        events["event_id"].isin(confirmed["event_id"])
        & events["bp_delta"].notna()
        & events["yes_clob_token_id"].notna()
    ].merge(
        confirmed[["event_id", "matched_meeting_date"]], on="event_id", how="inner",
    )

    rows = []
    for _, sub in submarkets.iterrows():
        try:
            history = get_price_history(sub["yes_clob_token_id"])
        except Exception as exc:
            logger.warning(
                "Kunde inte hämta prishistorik för event %s (%s): %s",
                sub["event_id"], sub["question"], exc,
            )
            continue

        for point in history:
            rows.append({
                "meeting_date": sub["matched_meeting_date"],
                "event_id": sub["event_id"],
                "question": sub["question"],
                "bp_delta": int(sub["bp_delta"]),
                "open_ended": bool(sub["open_ended"]),
                "date": datetime.fromtimestamp(point["t"], tz=timezone.utc).date(),
                "polymarket_probability_pct": round(point["p"] * 100, 4),
            })

    result = pd.DataFrame(rows)
    if not result.empty:
        # CLOB:s prishistorik innehåller en extra "just nu"-datapunkt för
        # INNEVARANDE dag utöver den vanliga dagliga snapshotten (samma
        # kalenderdatum, olika klockslag) — dedupa till senaste pris per dag.
        before_dedup = len(result)
        result = (
            result.sort_values("date")
            .drop_duplicates(subset=["event_id", "bp_delta", "date"], keep="last")
            .reset_index(drop=True)
        )
        if before_dedup != len(result):
            logger.debug(
                "Dedupade %d dubblettdatapunkter (samma dag, flera klockslag — t.ex. dagens "
                "intradag-pris utöver den ordinarie dagliga snapshotten).",
                before_dedup - len(result),
            )

    logger.info(
        "Hämtade %d historiska datapunkter över %d submarknader (%d bekräftade möten).",
        len(result), submarkets["market_id"].nunique() if not submarkets.empty else 0,
        confirmed_matches["event_id"].nunique(),
    )
    return result

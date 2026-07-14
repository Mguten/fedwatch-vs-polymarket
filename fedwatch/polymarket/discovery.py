"""Modul 5: hittar Fed/FOMC-relaterade Polymarket-events och parsar ut
respektive submarknads implicita bp-utfall ur frågetexten.

Två kompletterande sökvägar (unionen dedupliceras på event-id):
  1. Taggbaserad listning (tag_slug='fed-rates') — Polymarkets egen
     kategorisering, mest precis.
  2. Fritextsökning på nyckelord ('Fed', 'FOMC', 'interest rate') — täcker
     events som saknar taggen, per spec:s explicita krav.
"""

import json
import logging
import re

import pandas as pd

from fedwatch.polymarket.client import events_by_tag, search_events

logger = logging.getLogger(__name__)

SEARCH_KEYWORDS = ["Fed", "FOMC", "interest rate"]
FED_RATES_TAG = "fed-rates"

_UP_WORDS = r"increase|increases|raise|raises|hike|hikes"
_DOWN_WORDS = r"decrease|decreases|cut|cuts|lower|lowers"
_BP_PATTERN = re.compile(
    rf"(?P<direction>{_UP_WORDS}|{_DOWN_WORDS}).*?by\s+(?P<bp>\d+)(?P<plus>\+)?\s*bps?", re.IGNORECASE
)
_UP_WORDS_SET = {w.lower() for w in _UP_WORDS.split("|")}
_NO_CHANGE_PATTERN = re.compile(r"no change", re.IGNORECASE)


def _parse_bp_outcome(question: str) -> dict:
    """Försöker tolka en submarknadsfråga till ett bp-utfall.

    Returnerar {'bp_delta': int, 'open_ended': bool} eller None om frågan
    inte matchar något av de kända mönstren (t.ex. icke-räntefrågor som
    "Powell fired?" som ibland följer med i samma event/tagg).
    """
    if _NO_CHANGE_PATTERN.search(question):
        return {"bp_delta": 0, "open_ended": False}

    match = _BP_PATTERN.search(question)
    if not match:
        return None

    bp = int(match.group("bp"))
    sign = 1 if match.group("direction").lower() in _UP_WORDS_SET else -1
    return {"bp_delta": sign * bp, "open_ended": match.group("plus") is not None}


def _extract_markets(event: dict) -> list:
    rows = []
    for market in event.get("markets", []):
        question = market.get("question", "")
        parsed = _parse_bp_outcome(question)
        try:
            outcomes = json.loads(market.get("outcomes", "[]"))
            prices = json.loads(market.get("outcomePrices", "[]"))
            clob_token_ids = json.loads(market.get("clobTokenIds", "[]"))
        except (json.JSONDecodeError, TypeError):
            outcomes, prices, clob_token_ids = [], [], []

        yes_price = None
        yes_token_id = None
        if "Yes" in outcomes:
            idx = outcomes.index("Yes")
            if idx < len(prices):
                yes_price = float(prices[idx])
            if idx < len(clob_token_ids):
                yes_token_id = clob_token_ids[idx]

        rows.append({
            "event_id": event.get("id"),
            "market_id": market.get("id"),
            "question": question,
            "bp_delta": parsed["bp_delta"] if parsed else None,
            "open_ended": parsed["open_ended"] if parsed else None,
            "parse_failed": parsed is None,
            "yes_probability": yes_price,
            "yes_clob_token_id": yes_token_id,
            "market_end_date": market.get("endDate"),
        })
    return rows


def fetch_fed_decision_events() -> pd.DataFrame:
    """Hämtar samtliga kandidat-events (taggbaserat + nyckelordssökning,
    deduplicerat), plattar ut till en DataFrame med en rad per submarknad.

    OBS: detta är RÅA kandidater. Se matching.py — dessa ska matchas mot
    FOMC-möten och GRANSKAS FÖR HAND (spec Modul 5) innan de används.
    """
    events_by_id: dict = {}

    try:
        for event in events_by_tag(FED_RATES_TAG, limit=200):
            events_by_id[event["id"]] = event
    except Exception as exc:
        logger.warning("Taggbaserad Polymarket-hämtning (tag_slug=%s) misslyckades: %s", FED_RATES_TAG, exc)

    for keyword in SEARCH_KEYWORDS:
        try:
            for event in search_events(keyword, limit_per_type=50):
                events_by_id[event["id"]] = event
        except Exception as exc:
            logger.warning("Polymarket-sökning på '%s' misslyckades: %s", keyword, exc)

    logger.info("Hittade %d unika Polymarket-events över taggar + nyckelordssökning.", len(events_by_id))

    rows = []
    for event in events_by_id.values():
        event_rows = _extract_markets(event)
        for row in event_rows:
            row["event_title"] = event.get("title")
            row["event_end_date"] = event.get("endDate")
            row["event_closed"] = event.get("closed")
            row["event_tags"] = [t.get("slug") for t in event.get("tags", [])]
        rows.extend(event_rows)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    n_unparsed = int(df["parse_failed"].sum())
    if n_unparsed:
        logger.info(
            "%d/%d submarknader kunde inte tolkas till ett bp-utfall (troligen icke-räntefrågor "
            "som följde med via tagg/sökning, t.ex. 'Powell fired?'). Dessa flaggas parse_failed=True.",
            n_unparsed, len(df),
        )
    return df

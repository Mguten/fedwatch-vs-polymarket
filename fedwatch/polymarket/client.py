"""Modul 5: tunn klient mot Polymarkets publika API:er.

clob.polymarket.com (orderbok/historiska priser) och gamma-api.polymarket.com
(marknads-/eventmetadata, sökning) är båda fritt tillgängliga utan nyckel
eller kostnad — verifierat manuellt innan denna modul byggdes (ingen
betalvägg, ingen påträngande rate-limit vid normal användning). Därför
byggs direktanrop, per spec, istället för CSV-fallback.
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
CLOB_BASE_URL = "https://clob.polymarket.com"

_REQUEST_TIMEOUT = 20
_RATE_LIMIT_SLEEP_SECONDS = 0.2  # artig paus mellan anrop vid paginering/batchar


def _get(url: str, params: dict = None) -> dict:
    response = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def search_events(query: str, limit_per_type: int = 20) -> list:
    """Fritextsökning via gamma-api:s public-search — täcker t.ex. 'Fed',
    'FOMC', 'interest rate'."""
    data = _get(f"{GAMMA_BASE_URL}/public-search", params={"q": query, "limit_per_type": limit_per_type})
    return data.get("events", [])


def events_by_tag(tag_slug: str, limit: int = 100, closed: bool = None) -> list:
    """Strukturerad taggbaserad listning (t.ex. tag_slug='fed-rates') —
    mer precis än fritextsökning när Polymarket redan kategoriserat
    marknaderna åt oss."""
    params = {"tag_slug": tag_slug, "limit": limit}
    if closed is not None:
        params["closed"] = str(closed).lower()
    return _get(f"{GAMMA_BASE_URL}/events", params=params)


def get_event(event_id: str) -> dict:
    return _get(f"{GAMMA_BASE_URL}/events/{event_id}")


def get_price_history(clob_token_id: str, interval: str = "max", fidelity: int = 1440) -> list:
    """Historisk prisserie (=marknadsimplicit sannolikhet för "Yes") för en
    enskild outcome-token. fidelity i minuter (1440 = daglig upplösning)."""
    data = _get(
        f"{CLOB_BASE_URL}/prices-history",
        params={"market": clob_token_id, "interval": interval, "fidelity": fidelity},
    )
    time.sleep(_RATE_LIMIT_SLEEP_SECONDS)
    return data.get("history", [])

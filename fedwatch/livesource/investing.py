"""Live-datakälla: investing.com/central-banks/fed-rate-monitor som alternativ
till att köra vår egen ZQ-kontraktsbaserade deconvolution (fedwatch.deconvolution)
för DAGSAKTUELLA sannolikheter.

Bakgrund (se konversationen/RAPPORT.md): CME:s eget FedWatch-verktyg
(cmegroup.com) är skyddat av Akamai bot management och går inte att hämta
programmatiskt. investing.com visar samma typ av tabell (sannolikhet per
target-rate-intervall, per kommande FOMC-möte) som en vanlig
server-renderad sida utan bot-skydd — verifierat manuellt 2026-07-16, se
tests/fixtures/investing_fed_rate_monitor.html för en sparad kopia av
sidan som testerna kör mot.

VIKTIGT — ToS-reservation: robots.txt blockerar inte den här sidan, men det
säger inget om investing.coms användarvillkor för automatiserad datahämtning.
Den här modulen gör en enstaka daglig GET (inte massuttag), men det är
användarens ansvar att bedöma om det är förenligt med deras villkor.

User-Agent (2026-07-17, ändrat efter att en spoofad Chrome-UA plötsligt
började ge 403 samma dag den fungerat fint tidigare): vi identifierar oss nu
ÄRLIGT som ett bot med syfte och kontakt (se _USER_AGENT), istället för att
låtsas vara en webbläsare. Testat sida vid sida samma dag: spoofad
Chrome-UA -> 403, ärlig bot-UA -> 200 med identisk, giltig data. Troligen
för att en spoofad UA från en icke-webbläsarklient (fel TLS-fingeravtryck,
saknade headers en riktig webbläsare skulle skicka) är precis det mönster
enkla bot-heuristiker letar efter — att öppet ANGE att man är ett bot
undviker den specifika detektionen, snarare än att kringgå den.

Metodologisk skillnad mot fedwatch.deconvolution.engine: den motorn räknar
fram sannolikheter från rå ZQ-kontraktsdata (steg 1-7 i CME:s metod).
investing.com ger oss redan en färdig KUMULATIV fördelning per möte (samma
konvention som CME:s egen 'cumulative'-radtyp, se engine.py) — vi slipper
alltså heltal+mantissa-uppdelningen från kontraktspriser, men behöver
fortfarande härleda den LOKALA (möte-för-möte) stegfördelningen som är det
Polymarkets marknader faktiskt prisar in (se fedwatch.comparison).

Den härledningen (local_steps_from_cumulative) återanvänder EXAKT samma
binära heltal+mantissa-uppdelning (_local_step_distribution) som
fedwatch.deconvolution.engine — grundat i att E[lokal ändring vid möte N] =
E[kumulativ ändring t.o.m. möte N] - E[kumulativ ändring t.o.m. möte N-1]
(linjäritet hos väntevärde, gäller oavsett datakälla). Det är samma
matematiska antagande som redan är validerat mot CME:s egna publicerade
siffror i tests/test_deconvolution.py — bara tillämpat på investing.coms
väntevärden istället för på kontraktspriser.
"""

import logging
import re
from datetime import date, datetime

import pandas as pd
import requests

from fedwatch.config import BP_STEP
from fedwatch.deconvolution.engine import _local_step_distribution

logger = logging.getLogger(__name__)

FED_RATE_MONITOR_URL = "https://www.investing.com/central-banks/fed-rate-monitor"

_USER_AGENT = (
    "FedWatchResearchBot/1.0 (+https://github.com/Mguten/fedwatch-vs-polymarket; "
    "personligt forskningsprojekt, ~1 anrop/dygn)"
)
_REQUEST_TIMEOUT = 20

# Ett mötesblock på sidan: "Meeting Time: <datum>" ... "Future Price: <pris>"
# följt av ett antal percfedRateItem-rader innan nästa infoFed-block (eller
# slutet av sidan).
_MEETING_BLOCK_RE = re.compile(
    r"Meeting Time:</span>\s*<i>([^<]+)</i>.*?"
    r"Future Price:</span>\s*<i>([^<]+)</i>(.*?)(?=<div class=\"infoFed\">|\Z)",
    re.S,
)
# En bucket-rad inom ett mötesblock: intervall + procentsats.
_BUCKET_ITEM_RE = re.compile(
    r'percfedRateItem">\s*<span>([^<]+)</span>\s*<i></i>\s*'
    r'<div[^>]*style="width: [0-9.]+%"></div>\s*<span>([0-9.]+)%</span>'
)
_MEETING_TIME_FORMAT = "%b %d, %Y %I:%M%p ET"


def fetch_fed_rate_monitor_html(url: str = FED_RATE_MONITOR_URL) -> str:
    """Hämtar sidans HTML med en ÄRLIG, självidentifierande User-Agent (se
    modulens docstring för varför — en spoofad Chrome-UA gav 403, denna gav
    200 med identisk data, testat sida vid sida 2026-07-17)."""
    response = requests.get(
        url, headers={"User-Agent": _USER_AGENT}, timeout=_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.text


def parse_fed_rate_monitor(html: str) -> pd.DataFrame:
    """Parsar sidans inbäddade Fed Rate Monitor-tabell till en kumulativ
    sannolikhetsfördelning per kommande möte.

    Output-kolumner: meeting_date, rate_low, rate_high, probability_pct.
    En rad per (möte, target-rate-intervall). Samma konvention som
    fedwatch.deconvolution.engine.run_deconvolution's 'cumulative'-rader:
    ackumulerad sannolikhet för var target-räntan ligger VID det mötet.

    Rader/block som inte går att tolka hoppas över med en varning istället
    för att krascha hela hämtningen — sidans HTML-struktur är investing.coms
    egen och kan ändras utan förvarning.
    """
    rows = []
    blocks = _MEETING_BLOCK_RE.findall(html)
    if not blocks:
        logger.warning(
            "Hittade inga möbesblock i investing.com-sidan — HTML-strukturen kan ha ändrats."
        )
    for meeting_time_raw, _future_price_raw, rest in blocks:
        try:
            meeting_date = datetime.strptime(meeting_time_raw.strip(), _MEETING_TIME_FORMAT).date()
        except ValueError:
            logger.warning("Kunde inte tolka mötesdatum %r, hoppar över blocket.", meeting_time_raw)
            continue

        items = _BUCKET_ITEM_RE.findall(rest)
        if not items:
            logger.warning("Inga tolkningsbara bucket-rader för mötet %s, hoppar över.", meeting_date)
            continue

        for bucket_label, pct_raw in items:
            try:
                low_raw, high_raw = bucket_label.split("-")
                rate_low, rate_high = float(low_raw.strip()), float(high_raw.strip())
            except ValueError:
                logger.warning(
                    "Kunde inte tolka target-rate-intervallet %r för mötet %s, hoppar över raden.",
                    bucket_label, meeting_date,
                )
                continue

            rows.append({
                "meeting_date": meeting_date,
                "rate_low": rate_low,
                "rate_high": rate_high,
                "probability_pct": float(pct_raw),
            })

    result = pd.DataFrame(rows, columns=["meeting_date", "rate_low", "rate_high", "probability_pct"])
    if not result.empty:
        # Sidans "Fed Rate Monitor Tool"-sidopanel visar samma närmaste möte
        # som huvudtabellen redan täcker — dedupa så det mötet inte räknas
        # dubbelt (alla andra möten förekommer bara i huvudtabellen).
        result = (
            result.drop_duplicates(subset=["meeting_date", "rate_low", "rate_high"])
            .sort_values(["meeting_date", "rate_low"])
            .reset_index(drop=True)
        )
    logger.info(
        "Tolkade %d bucket-rader över %d möten från investing.com.",
        len(result), result["meeting_date"].nunique() if not result.empty else 0,
    )
    return result


def local_steps_from_cumulative(
    cumulative: pd.DataFrame, current_rate_upper: float, current_rate_lower: float,
) -> pd.DataFrame:
    """Härleder LOKALA (möte-för-möte) stegfördelningar ur investing.coms
    kumulativa tabell — se moduldocstringen för det matematiska motivet
    (E[lokal_N] = E[kumulativ_N] - E[kumulativ_{N-1}]).

    Output-kolumner: meeting_date, meeting_ordinal, local_bp_change,
    probability_pct — samma form som de 'local'-rader
    fedwatch.deconvolution.engine.run_deconvolution ger, så resultatet kan
    användas rakt av där vi idag använder row_type=='local'.
    """
    if cumulative.empty:
        return pd.DataFrame(columns=["meeting_date", "meeting_ordinal", "local_bp_change", "probability_pct"])

    expected_current = (current_rate_upper + current_rate_lower) / 2
    rows = []
    prev_expected = expected_current
    for ordinal, (meeting_date, group) in enumerate(
        cumulative.sort_values("meeting_date").groupby("meeting_date", sort=True), start=1,
    ):
        midpoints = (group["rate_low"] + group["rate_high"]) / 2
        weights = group["probability_pct"] / 100
        expected_rate = float((midpoints * weights).sum())

        change = (expected_rate - prev_expected) / BP_STEP * 100
        local_dist = _local_step_distribution(change)

        for bp, prob in sorted(local_dist.items()):
            rows.append({
                "meeting_date": meeting_date,
                "meeting_ordinal": ordinal,
                "local_bp_change": bp,
                "probability_pct": round(prob * 100, 6),
            })
        prev_expected = expected_rate

    return pd.DataFrame(rows)

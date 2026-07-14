"""Modul 3, steg 1-3+5: bygger per-kalendermånad genomsnittspriser (Pavg) ur
ZQ-kontraktsdata, klassificerar FOMC- vs icke-FOMC-månader, och propagerar
implicit ränta för FOMC-månader enligt CME:s regel:

  - framåt: endast en månad (från en icke-FOMC-månads Pend till nästa
    FOMC-månads Pstart)
  - bakåt: så många månader som behövs (kedjor av flera FOMC-månader i rad
    löses upp bakifrån, med dag-viktad uppdelning inom varje FOMC-månad)

Hanterar även kontraktsmånader med FLERA FOMC-möten (spec punkt 5): då räcker
inte en enda ekvation (månadens Pavg) för att lösa ut alla interna
brytpunkter om även månadens start- eller slutpris är okänt — i så fall
används spreaden mot efterföljande kontraktsmånad som extra ekvation.

Logiken är en direkt, dokumenterad omskrivning av referensimplementationen
pyfedwatch (`add_price_data`/`fill_price_data` i pyfedwatch.fedwatch), som
spec pekar ut som jämförelsepunkt.
"""

import calendar
import logging
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

logger = logging.getLogger(__name__)


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = (year * 12 + (month - 1)) + delta
    return idx // 12, idx % 12 + 1


def month_avg_price(contracts: pd.DataFrame, year: int, month: int, watch_date: date) -> float:
    """Genomsnittspris (close) för kontraktsmånad (year, month) per watch_date.

    Om kontraktet ännu inte förfallit: senaste close på/före watch_date.
    Om det redan förfallit (kontraktsmånaden ligger före watch_date-månaden):
    senaste close på/före sista dagen i kontraktsmånaden (undviker orealistiska
    priser som vissa datakällor kan visa efter förfall) — samma princip som
    pyfedwatch.add_price_data.
    """
    subset = contracts[(contracts["contract_year"] == year) & (contracts["contract_month"] == month)]
    if subset.empty:
        raise ValueError(f"Ingen kontraktsdata för {year}-{month:02d}.")

    watch_period_start = date(watch_date.year, watch_date.month, 1)
    contract_period_start = date(year, month, 1)

    if contract_period_start >= watch_period_start:
        cutoff = watch_date
    else:
        last_day = calendar.monthrange(year, month)[1]
        cutoff = date(year, month, last_day)

    eligible = subset[subset["date"].dt.date <= cutoff].sort_values("date")
    if eligible.empty:
        raise ValueError(f"Ingen kontraktsdata för {year}-{month:02d} på eller före {cutoff}.")
    return float(eligible.iloc[-1]["close_price"])


@dataclass
class MonthRecord:
    year: int
    month: int
    meeting_end_dates: list = field(default_factory=list)  # datetime.date, sorterat
    p_avg: float = float("nan")
    p_start: float = float("nan")
    p_end: float = float("nan")
    resolved_via_approximation: bool = False
    # För flermötesmånader: rate direkt EFTER varje möte i meeting_end_dates,
    # i samma ordning (segment_rates[-1] == p_end). Tom för enmötesmånader
    # (då räcker p_start/p_end).
    segment_rates: list = field(default_factory=list)

    @property
    def is_fomc_month(self) -> bool:
        return len(self.meeting_end_dates) > 0

    @property
    def multi_meeting_month(self) -> bool:
        return len(self.meeting_end_dates) > 1


def build_month_frame(
    watch_date: date,
    meetings: pd.DataFrame,
    contracts: pd.DataFrame,
    anchor_price: float = None,
) -> list[MonthRecord]:
    """Bygger en MonthRecord per kalendermånad från watch_date:s månad t.o.m.
    sista mötets månad, med Pavg ifylld och FOMC-möten kopplade till rätt månad.

    anchor_price: om watch_date:s egen månad redan är en FOMC-månad (mötet
    ligger senare samma månad som watch_date) finns ingen tidigare månad i
    fönstret att framåtpropagera Pstart ifrån. Då krävs en känd "ankarränta"
    för läget precis vid watch_date (typiskt dagens faktiska target rate från
    FRED, se engine.run_deconvolution) — den läggs in som en syntetisk
    icke-FOMC-månad omedelbart före watch_date:s månad.
    """
    horizon_meetings = meetings[meetings["end_date"].dt.date >= watch_date].sort_values("end_date")
    if horizon_meetings.empty:
        raise ValueError("Inga kommande FOMC-möten på eller efter watch_date.")

    last_meeting_date = horizon_meetings["end_date"].dt.date.max()
    watch_month_has_meeting = any(
        d.year == watch_date.year and d.month == watch_date.month
        for d in horizon_meetings["end_date"].dt.date
    )

    months: list[MonthRecord] = []
    if watch_month_has_meeting and anchor_price is not None:
        anchor_year, anchor_month = _add_months(watch_date.year, watch_date.month, -1)
        anchor = MonthRecord(year=anchor_year, month=anchor_month)
        anchor.p_avg = anchor.p_start = anchor.p_end = anchor_price
        months.append(anchor)

    year, month = watch_date.year, watch_date.month
    while (year, month) <= (last_meeting_date.year, last_meeting_date.month):
        rec = MonthRecord(year=year, month=month)
        rec.meeting_end_dates = sorted(
            d for d in horizon_meetings["end_date"].dt.date if d.year == year and d.month == month
        )
        try:
            rec.p_avg = month_avg_price(contracts, year, month, watch_date)
        except ValueError as exc:
            logger.warning("Saknar kontraktsdata för %d-%02d: %s", year, month, exc)
        months.append(rec)
        year, month = _add_months(year, month, 1)

    return months


def propagate_prices(months: list[MonthRecord]) -> list[MonthRecord]:
    """Fyller Pstart/Pend för samtliga månader enligt CME:s propageringsregel.

    Icke-FOMC-månader: Pstart = Pend = Pavg (rakt av).
    FOMC-månader: forward-pass propagerar en granne-månads kända pris ett steg;
    backward-pass löser resterande genom dag-viktad uppdelning av Pavg, med stöd
    för flermötesmånader (löses mot Pavg + ev. spread mot nästa kontraktsmånad).

    OBS — känd egenskap vid KEDJOR AV FLERA FOMC-månader I RAD (t.ex. verkliga
    juni/juli 2026): den mittersta brytpunkten (t.ex. junis Pend = julis
    Pstart) löses uteslutande ur den SENARE månadens egen Pavg/dagviktning
    (här: juli), eftersom den tidigare månaden (juni) redan fått sitt Pstart
    framåtpropagerat och aldrig konsumerar sitt eget Pavg i denna kedja. Juni
    egen Pavg används alltså inte till något i just detta fall — samma
    beteende som referensimplementationen pyfedwatch (fill_price_data).
    Det är inte ett fel, men värt att känna till vid felsökning av resultat.
    """
    n = len(months)
    for rec in months:
        if not rec.is_fomc_month:
            rec.p_start = rec.p_avg
            rec.p_end = rec.p_avg

    # Forward-pass: propagera en känd grannmånads pris framåt exakt ett steg.
    for i in range(1, n - 1):
        rec = months[i]
        if not rec.is_fomc_month:
            continue
        prev_end = months[i - 1].p_end
        if pd.isna(rec.p_start) and not pd.isna(prev_end):
            rec.p_start = prev_end

    # Backward-pass: lös resterande FOMC-månader bakifrån.
    for i in range(n - 2, 0, -1):
        rec = months[i]
        if not rec.is_fomc_month:
            continue
        next_start = months[i + 1].p_start
        if pd.isna(rec.p_end) and not pd.isna(next_start):
            rec.p_end = next_start

        if pd.isna(rec.p_start) and not rec.multi_meeting_month:
            _solve_month(rec)

    # Flermötesmånader behöver ALLTID de interna brytpunkterna beräknade
    # (segment_rates) för att Modul 3 ska kunna ge varje enskilt möte sin
    # egen fördelning — även när Pstart/Pend för hela månaden redan är kända
    # direkt från grannmånaderna (vanligast, se _solve_multi_meeting_month).
    for rec in months:
        if rec.multi_meeting_month and not rec.segment_rates:
            _solve_multi_meeting_month(rec, _days_in_month(rec))

    unresolved = [f"{r.year}-{r.month:02d}" for r in months if pd.isna(r.p_start) or pd.isna(r.p_end)]
    if unresolved:
        logger.warning("Kunde inte prispropagera fullt ut för månad(er): %s", ", ".join(unresolved))

    return months


def _days_in_month(rec: MonthRecord) -> int:
    return calendar.monthrange(rec.year, rec.month)[1]


def _solve_month(rec: MonthRecord) -> None:
    """Löser Pstart för en enmötesmånad givet Pavg och Pend, via dagviktad
    uppdelning. Anropas endast för enmötesmånader — flermötesmånader hanteras
    separat av _solve_multi_meeting_month (kräver alltid segment_rates,
    oavsett om Pstart/Pend redan är kända, se propagate_prices).
    """
    days_no = _days_in_month(rec)
    meeting_day = rec.meeting_end_dates[0].day if rec.meeting_end_dates else days_no
    m = days_no - meeting_day + 1  # dagar från och med mötesdagen t.o.m. månadsslut
    n_days = days_no - m  # dagar före mötesdagen
    if pd.isna(rec.p_end) or n_days <= 0:
        logger.warning(
            "Kan inte lösa Pstart för %d-%02d: saknar Pend eller ogiltig dagfördelning.",
            rec.year, rec.month,
        )
        return
    rec.p_start = (rec.p_avg * days_no - m * rec.p_end) / n_days


def _solve_multi_meeting_month(rec: MonthRecord, days_no: int) -> None:
    """Löser en flermötesmånad (N>=2 möten samma kontraktsmånad).

    Månadens enda observerbara ekvation (Pavg, en dagviktad blandning av
    N+1 interna segmenträntor) räcker matematiskt inte för att lösa ut N-1
    interna brytpunkter unikt utan ytterligare antaganden — det finns ingen
    finkornigare kontraktsdata inom en enskild kalendermånad att falla
    tillbaka på (till skillnad från spreaden mot NÄSTA kontraktsmånad, som
    bara ger en (1) extra ekvation, oavsett hur många interna brytpunkter
    som saknas).

    Vi löser Pstart/Pend mot grannmånaderna precis som för enmötesmånader
    (kräver att minst en av dem är känd; annars kan inget lösas). Med Pstart
    och Pend fastställda återstår N-1 interna brytpunkter men bara EN
    ekvation (Pavg) för dem — vi väljer då att ge alla interna segment
    (mellan första och sista mötet) SAMMA ränta R, vilket är den unika
    lösningen som gör den dagviktade Pavg-ekvationen EXAKT uppfylld utan att
    behöva gissa hur räntan fördelar sig mellan de enskilda interna mötena.
    Det är en uttrycklig APPROXIMATION för mötena MELLAN första och sista
    (flaggas via resolved_via_approximation) — inte en exakt CME-härledning
    — eftersom vi saknar en andra oberoende ekvation för att särskilja dem.
    """
    if pd.isna(rec.p_start) and pd.isna(rec.p_end):
        logger.warning(
            "%d-%02d: flermötesmånad (%d möten) saknar både Pstart och Pend — kan inte lösas.",
            rec.year, rec.month, len(rec.meeting_end_dates),
        )
        return

    days = [d.day for d in rec.meeting_end_dates]
    segment_days = [days[0] - 1] + [days[k + 1] - days[k] for k in range(len(days) - 1)] + [days_no - days[-1] + 1]

    if pd.isna(rec.p_start):
        # Endast Pend känt: anta att hela Pavg-avvikelsen från Pend härrör
        # linjärt bakåt i tiden (symmetriskt med enmötesfallet).
        rec.p_start = rec.p_avg + (rec.p_avg - rec.p_end) * (segment_days[-1] / max(sum(segment_days[:-1]), 1))
    if pd.isna(rec.p_end):
        rec.p_end = rec.p_avg + (rec.p_avg - rec.p_start) * (segment_days[0] / max(sum(segment_days[1:]), 1))

    n_meetings = len(rec.meeting_end_dates)
    if n_meetings == 1:
        rec.segment_rates = [rec.p_end]
    else:
        interior_days = sum(segment_days[1:-1])
        if interior_days > 0:
            interior_rate = (
                rec.p_avg * days_no - segment_days[0] * rec.p_start - segment_days[-1] * rec.p_end
            ) / interior_days
        else:
            interior_rate = (rec.p_start + rec.p_end) / 2
        rec.segment_rates = [interior_rate] * (n_meetings - 1) + [rec.p_end]

    rec.resolved_via_approximation = True
    logger.warning(
        "%d-%02d: flermötesmånad (%d möten) — interna mötesräntor mellan första "
        "och sista mötet approximerade som en gemensam ränta (ingen exakt "
        "lösning möjlig med endast månadens Pavg). Flaggat via resolved_via_approximation.",
        rec.year, rec.month, len(rec.meeting_end_dates),
    )

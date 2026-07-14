"""Modul 3, steg 4+6: lokala stegfördelningar per FOMC-möte (CME:s
heltal+mantissa-uppdelning ur metodologidokumentets steg 6-7) och full
flerstegs-deconvolution (convolution över hela mötessekvensen från
watch_date) — "FULLT MULTI-STEG", inte binärt/ternärt.

Om "fler än två utfall" (se spec, Modul 3 punkt 4):

CME:s metodologidokument beskriver steg 6-7 som en ENSKILD månads
heltal+mantissa-uppdelning — matematiskt ALLTID exakt två angränsande
25bp-utfall (det är den enda fördelning som kan matcha ett enda väntevärde
E[R] utan extra antaganden). Läser man steg 6-7 isolerat och naivt applicerar
dem möte för möte oberoende av varandra, blir VARJE mötes rapporterade
fördelning binär — även möten långt fram i tiden, vilket uppenbart är fel
(jämför CME:s egna publicerade "Conditional Meeting Probabilities" för möten
långt fram, se config/cme_validation_probabilities.csv, där sannolikhetsmassan
sprids över 5-9 nivåer).

Det korrekta sättet att generalisera (verifierat empiriskt mot
config/cme_validation_probabilities.csv, se tests/test_deconvolution.py) är
INTE att bredda den enskilda månadens lokala binära fördelning — det gav
sämre träffsäkerhet vid test — utan att KUMULATIVT convolvera varje mötes
binära lokala fördelning med samtliga FÖREGÅENDE mötens fördelningar i
sekvens från watch_date. Ett möte N stegs bort får då korrekt upp till N+1
möjliga utfallsnivåer, som en strukturell konsekvens av convolution — inte
av en påhittad lokal breddning. multi_outcome_flag nedan speglar precis
detta: True så fort mötets KUMULATIVA fördelning (efter convolution) har
fler än två utfallsnivåer med icke-försumbar sannolikhet.
"""

import logging
import math
from datetime import date

import pandas as pd

from fedwatch.config import BP_STEP
from fedwatch.deconvolution.pricing import build_month_frame, propagate_prices
from fedwatch.fomc.decisions import fetch_fred_series

logger = logging.getLogger(__name__)

# Tröskel (i sannolikhet, ej procent) för att en utfallsnivå ska räknas som
# "icke-försumbar" när multi_outcome_flag sätts.
SIGNIFICANT_PROB_THRESHOLD = 1e-4


def _local_step_distribution(change: float) -> dict:
    """CME:s/pyfedwatch:s heltal+mantissa-uppdelning för EN FOMC-månad.

    change = förväntat antal 25bp-steg vid mötet (kan vara negativt = sänkning),
    dvs pyfedwatch/CME:s "Change" = (Pstart-Pend)/BP_STEP*100.

    Ger alltid exakt två angränsande utfall (floor, floor+sign) med
    sannolikheter (1-mantissa, mantissa) — den unika tvåpunktsfördelning som
    matchar E[R] exakt givet endast ett väntevärde. Se moduldocstring för
    varför fler-än-två-utfall-generaliseringen sker via convolution
    (_convolve), inte här.
    """
    sign = 1 if change >= 0 else -1
    abs_change = abs(change)
    floor_steps = math.trunc(abs_change)
    mantissa = abs_change - floor_steps

    if mantissa == 0.0:
        return {sign * floor_steps * BP_STEP: 1.0}

    bp_floor = sign * floor_steps * BP_STEP
    bp_next = sign * (floor_steps + 1) * BP_STEP
    return {bp_floor: 1 - mantissa, bp_next: mantissa}


def _convolve(dist_a: dict, dist_b: dict) -> dict:
    out: dict = {}
    for bp_a, p_a in dist_a.items():
        for bp_b, p_b in dist_b.items():
            bp = bp_a + bp_b
            out[bp] = out.get(bp, 0.0) + p_a * p_b
    return out


def run_deconvolution(
    watch_date: date,
    meetings: pd.DataFrame,
    contracts: pd.DataFrame,
    current_rate_upper: float = None,
    current_rate_lower: float = None,
) -> pd.DataFrame:
    """Kör hela deconvolution-motorn.

    Producerar en sannolikhetsfördelning (absoluta target-rate-band) per
    kommande FOMC-möte, sett från watch_date, genom att kumulativt convolvera
    varje mötes lokala (binära) stegfördelning i tidsordning.

    current_rate_upper/lower: dagens target-rate-band (i procent, t.ex. 3.75
    och 3.50). Hämtas automatiskt från FRED (DFEDTARU/DFEDTARL) om ej angivet
    — samma källa som Modul 2 använder för att härleda faktiska FOMC-beslut.

    Output innehåller två radtyper (kolumn row_type), båda per möte:
      - 'cumulative': CME:s egen konvention (jämfört mot config/cme_validation_*
        i testerna) — ackumulerad förändring sedan watch_date, med absoluta
        rate_low/rate_high. cumulative_bp_change ifylld, local_bp_change tom.
      - 'local': fördelningen för STEGET vid just detta möte, oberoende av
        tidigare möten — detta är storheten Polymarkets möte-för-möte-marknader
        prisar in (se Modul 6/fedwatch.comparison). local_bp_change ifylld,
        cumulative_bp_change/rate_low/rate_high tomma (inte meningsfulla utan
        hela vägen dit).

    Övriga kolumner: watch_date, meeting_date, meeting_ordinal,
    probability_pct, multi_outcome_flag (endast satt på cumulative-rader),
    multi_meeting_month, approximated_month_split.
    """
    horizon_meetings = (
        meetings[meetings["end_date"].dt.date >= watch_date]
        .sort_values("end_date")
        .reset_index(drop=True)
    )
    if horizon_meetings.empty:
        raise ValueError("Inga kommande FOMC-möten på eller efter watch_date.")

    # Bakåtpropagering av en FOMC-månads Pstart kräver att åtminstone en
    # känd månad EFTER mötesmånaden finns i kontraktsdatan (en "buffert").
    # Möten vars månad sammanfaller med den sista tillgängliga kontraktsmånaden
    # kan därför inte lösas — de exkluderas här hellre än att tystas ner som
    # NaN längre in i pipelinen.
    max_contract_period = contracts[["contract_year", "contract_month"]].apply(tuple, axis=1).max()
    before_trim = len(horizon_meetings)
    horizon_meetings = horizon_meetings[
        horizon_meetings["end_date"].dt.date.apply(lambda d: (d.year, d.month) < max_contract_period)
    ]
    if len(horizon_meetings) < before_trim:
        logger.warning(
            "%d möte(n) exkluderade: saknar minst en kontraktsmånad efter mötesmånaden "
            "att bakåtpropagera mot (kontraktsdata sträcker sig t.o.m. %s).",
            before_trim - len(horizon_meetings), max_contract_period,
        )
    if horizon_meetings.empty:
        raise ValueError("Inga möten kvar med tillräcklig kontraktsbuffert efter trimning.")

    if current_rate_upper is None or current_rate_lower is None:
        upper_series = fetch_fred_series("DFEDTARU")
        lower_series = fetch_fred_series("DFEDTARL")
        current_rate_upper = float(upper_series.loc[: pd.Timestamp(watch_date)].iloc[-1])
        current_rate_lower = float(lower_series.loc[: pd.Timestamp(watch_date)].iloc[-1])

    anchor_price = 100 - (current_rate_upper + current_rate_lower) / 2
    months = build_month_frame(watch_date, horizon_meetings, contracts, anchor_price=anchor_price)
    months = propagate_prices(months)
    month_lookup = {(m.year, m.month): m for m in months}

    rows = []
    cumulative_dist = {0: 1.0}
    for ordinal, (_, meeting) in enumerate(horizon_meetings.iterrows(), start=1):
        meeting_date = meeting["end_date"].date()
        month_rec = month_lookup[(meeting_date.year, meeting_date.month)]

        if month_rec.multi_meeting_month:
            idx_in_month = month_rec.meeting_end_dates.index(meeting_date)
            seg_start = (
                month_rec.p_start if idx_in_month == 0 else month_rec.segment_rates[idx_in_month - 1]
            )
            seg_end = month_rec.segment_rates[idx_in_month] if month_rec.segment_rates else float("nan")
        else:
            seg_start, seg_end = month_rec.p_start, month_rec.p_end

        if pd.isna(seg_start) or pd.isna(seg_end):
            logger.warning("Möte %s: saknar prisdata efter propagering, hoppar över.", meeting_date)
            continue

        # CME/pyfedwatch: Change = (E[R]_end - E[R]_start) uttryckt i antal
        # BP_STEP-steg = ((100-Pend)-(100-Pstart))/BP_STEP*100 = (Pstart-Pend)/BP_STEP*100.
        change = (seg_start - seg_end) / BP_STEP * 100

        local_dist = _local_step_distribution(change)
        cumulative_dist = _convolve(cumulative_dist, local_dist)

        n_significant = sum(1 for p in cumulative_dist.values() if p > SIGNIFICANT_PROB_THRESHOLD)
        multi_outcome = n_significant > 2

        for bp, prob in sorted(cumulative_dist.items()):
            rows.append({
                "watch_date": watch_date,
                "meeting_date": meeting_date,
                "meeting_ordinal": ordinal,
                "row_type": "cumulative",
                "cumulative_bp_change": bp,
                "local_bp_change": None,
                "rate_low": round(current_rate_lower + bp / 100, 4),
                "rate_high": round(current_rate_upper + bp / 100, 4),
                "probability_pct": round(prob * 100, 6),
                "multi_outcome_flag": multi_outcome,
                "multi_meeting_month": month_rec.multi_meeting_month,
                "approximated_month_split": month_rec.resolved_via_approximation,
            })

        # "local" rader: sannolikhetsfördelningen för STEGET vid just detta
        # möte (oberoende av tidigare möten sedan watch_date) — detta är
        # storheten Polymarkets möte-för-möte-marknader ("increase by 25bps
        # after the July meeting?") faktiskt prisar in, till skillnad från
        # cumulative-raderna ovan (som är CME:s egen konvention och avser
        # ackumulerad förändring sedan watch_date). rate_low/rate_high är
        # inte meningsfulla i absoluta tal här (kräver hela vägen dit) och
        # lämnas tomma — se fedwatch.comparison för hur detta används.
        for bp, prob in sorted(local_dist.items()):
            rows.append({
                "watch_date": watch_date,
                "meeting_date": meeting_date,
                "meeting_ordinal": ordinal,
                "row_type": "local",
                "cumulative_bp_change": None,
                "local_bp_change": bp,
                "rate_low": None,
                "rate_high": None,
                "probability_pct": round(prob * 100, 6),
                "multi_outcome_flag": False,
                "multi_meeting_month": month_rec.multi_meeting_month,
                "approximated_month_split": month_rec.resolved_via_approximation,
            })

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result[result["probability_pct"] > SIGNIFICANT_PROB_THRESHOLD * 100].reset_index(drop=True)

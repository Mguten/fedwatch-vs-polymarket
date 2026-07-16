"""Implementerar entry-regeln från STRATEGY.md §4 mot LIVE-data (investing.com
+ Polymarkets aktuella priser) och håller reda på vilka signaler som redan
notifierats, så samma öppna läge inte spammas dagligen.

Detta är EXAKT samma regel som backtestades och formaliserades i
STRATEGY.md — se den filen för fullständiga definitioner (§3, §10) och
kända begränsningar (§9) innan den här signalen används för riktiga trades.
"""

import json
import logging
from datetime import date
from pathlib import Path

import pandas as pd

from fedwatch.comparison.compare import _fedfunds_probability_for

logger = logging.getLogger(__name__)


def find_leading_level_signals(
    fedfunds_local: pd.DataFrame,
    polymarket_current: pd.DataFrame,
    threshold_pct: float,
    window_days: int = 90,
    as_of: date = None,
) -> pd.DataFrame:
    """Hittar möten där den LEDANDE nivån (högst p bland handelsbara nivåer,
    STRATEGY.md §3) uppfyller entry-regeln (§4): p >= threshold_pct OCH p > P.

    fedfunds_local: kolumner meeting_date, local_bp_change, probability_pct
    (t.ex. från fedwatch.livesource.investing.local_steps_from_cumulative,
    eller row_type=='local' från fedwatch.deconvolution.engine.run_deconvolution).

    polymarket_current: kolumner meeting_date, event_id, bp_delta, open_ended,
    question, polymarket_probability_pct (t.ex. från
    fedwatch.polymarket.history.fetch_confirmed_current_prices).

    Output-kolumner: meeting_date, bp_delta, open_ended, event_id, question,
    fedfunds_probability_pct, polymarket_probability_pct, edge_pp.
    En rad per möte som HAR en kvalificerande ledande nivå (inte en rad per
    handelsbar nivå — bara den ledande är relevant för entry-beslutet).
    """
    if as_of is None:
        as_of = date.today()
    if fedfunds_local.empty or polymarket_current.empty:
        return pd.DataFrame(columns=[
            "meeting_date", "bp_delta", "open_ended", "event_id", "question",
            "fedfunds_probability_pct", "polymarket_probability_pct", "edge_pp",
        ])

    local = fedfunds_local.copy()
    local["meeting_date"] = pd.to_datetime(local["meeting_date"]).dt.date
    pm = polymarket_current.copy()
    pm["meeting_date"] = pd.to_datetime(pm["meeting_date"]).dt.date

    rows = []
    for meeting_date, pm_group in pm.groupby("meeting_date"):
        days_out = (meeting_date - as_of).days
        if not (0 <= days_out <= window_days):
            continue

        local_group = local[local["meeting_date"] == meeting_date]
        if local_group.empty:
            continue
        series = local_group.set_index("local_bp_change")["probability_pct"]

        candidates = []
        for _, pm_row in pm_group.iterrows():
            p = _fedfunds_probability_for(series, int(pm_row["bp_delta"]), bool(pm_row["open_ended"]))
            if p is None:
                continue
            candidates.append({
                "meeting_date": meeting_date,
                "bp_delta": int(pm_row["bp_delta"]),
                "open_ended": bool(pm_row["open_ended"]),
                "event_id": pm_row["event_id"],
                "question": pm_row["question"],
                "fedfunds_probability_pct": p,
                "polymarket_probability_pct": pm_row["polymarket_probability_pct"],
            })

        if not candidates:
            continue

        leader = max(candidates, key=lambda c: c["fedfunds_probability_pct"])
        p, P = leader["fedfunds_probability_pct"], leader["polymarket_probability_pct"]
        if p >= threshold_pct and p > P:
            leader["edge_pp"] = p - P
            rows.append(leader)

    return pd.DataFrame(rows)


def _state_key(row: pd.Series) -> str:
    return f"{row['meeting_date']}|{row['bp_delta']}|{row['open_ended']}"


def load_notify_state(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_notify_state(state: dict, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True))


def filter_new_signals(signals: pd.DataFrame, state: dict, as_of: date = None) -> tuple:
    """Jämför dagens kvalificerande signaler mot tidigare notifierat state.

    Notifierar bara när ett mötes LEDANDE nivå är NY (första gången mötet
    kvalificerar) eller har BYTTS (övertagen, STRATEGY.md §5a) jämfört med
    senast notifierade nivå för samma möte — inte varje dag positionen
    fortsätter kvalificera.

    Returnerar (new_signals_df, updated_state). Rensar även bort möten som
    redan passerat ur staten (de är avgjorda, se §5b).
    """
    if as_of is None:
        as_of = date.today()

    updated_state = {
        key: value for key, value in state.items()
        if date.fromisoformat(key.split("|")[0]) >= as_of
    }

    if signals.empty:
        return signals, updated_state

    new_rows = []
    for _, row in signals.iterrows():
        meeting_key = str(row["meeting_date"])
        level_key = f"{row['bp_delta']}|{row['open_ended']}"
        if updated_state.get(meeting_key) == level_key:
            continue
        new_rows.append(row)
        updated_state[meeting_key] = level_key

    new_signals = pd.DataFrame(new_rows) if new_rows else signals.iloc[0:0]
    return new_signals, updated_state


def format_signal_message(row: pd.Series) -> str:
    bucket_label = f"{'≥' if row['bp_delta'] >= 0 else '≤'}{row['bp_delta']:+d}bp" if row["open_ended"] else f"{row['bp_delta']:+d}bp"
    return (
        f"*FedFunds-signal: köpläge identifierat*\n\n"
        f"Möte: {row['meeting_date']}\n"
        f"Nivå: {bucket_label} ({row['question']})\n"
        f"Vår modell (p): {row['fedfunds_probability_pct']:.1f}%\n"
        f"Polymarket (P): {row['polymarket_probability_pct']:.1f}%\n"
        f"Edge (p−P): {row['edge_pp']:+.1f}pp\n\n"
        f"Regel: STRATEGY.md §4 (p≥tröskel och p>P). Detta är forskning, inte "
        f"en rekommendation — se STRATEGY.md §9 för kända begränsningar innan "
        f"du agerar på detta."
    )

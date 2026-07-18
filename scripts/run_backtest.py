"""Backtestar handelsstrategin i docs/STRATEGY.md mot output/fedfunds_vs_polymarket.csv.

Implementerar reglerna i docs/STRATEGY.md §3-6 rakt av: leder-nivå, entry
(p>=T och p>P), exit (övertagen eller mötet avgörs), PnL per 1 kr insats.
Kräver att `python scripts/run_pipeline.py` redan körts (så att
output/fedfunds_vs_polymarket.csv finns och är färsk).

Kör (från repo-roten): python scripts/run_backtest.py [tröskel ...]
Utan argument körs standardtrösklarna 50/60/70% och en detaljerad
exit-typ-nedbrytning (övertagen vs. avgörs vid mötet) för 60%.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from fedwatch.fomc.dates import get_fomc_meetings
from fedwatch.fomc.decisions import attach_decisions

OUTPUT_CSV = "output/fedfunds_vs_polymarket.csv"
WINDOW_DAYS = 90


def load_settled_window() -> tuple[pd.DataFrame, pd.Series]:
    df = pd.read_csv(OUTPUT_CSV, parse_dates=["meeting_date", "date"])
    df["days_to_meeting"] = (df["meeting_date"] - df["date"]).dt.days
    df = df[(df["days_to_meeting"] >= 0) & (df["days_to_meeting"] <= WINDOW_DAYS)].copy()
    df["meeting_date_only"] = df["meeting_date"].dt.date

    meetings = attach_decisions(get_fomc_meetings())
    actual_by_meeting = meetings.set_index(meetings["end_date"].dt.date)["decision_bps_upper"]

    df["actual_known"] = df["meeting_date_only"].map(lambda d: not pd.isna(actual_by_meeting.get(d)))
    return df[df["actual_known"]].copy(), actual_by_meeting


def is_actual_outcome(actual_by_meeting: pd.Series, meeting_date, bp_delta: int, open_ended: bool) -> bool:
    actual = int(actual_by_meeting[meeting_date])
    if open_ended:
        return (bp_delta >= 0 and actual >= bp_delta) or (bp_delta < 0 and actual <= bp_delta)
    return actual == bp_delta


def run_backtest(settled: pd.DataFrame, actual_by_meeting: pd.Series, threshold: float) -> pd.DataFrame:
    """threshold in [0, 1]. Returns one row per trade (docs/STRATEGY.md §4-5)."""
    trades = []
    for meeting_date, g in settled.groupby("meeting_date_only"):
        position = None  # {"bucket": int, "entry_price": float}
        for d in sorted(g["date"].unique()):
            day = g[g["date"] == d].sort_values("fedfunds_probability_pct", ascending=False)
            leader = day.iloc[0]
            leader_bucket = leader["bp_delta"]
            leader_p = leader["fedfunds_probability_pct"] / 100.0
            leader_P = leader["polymarket_probability_pct"] / 100.0

            if position is not None and position["bucket"] != leader_bucket:
                owned = day[day["bp_delta"] == position["bucket"]]
                exit_price = (
                    owned.iloc[0]["polymarket_probability_pct"] / 100.0
                    if not owned.empty
                    else position["entry_price"]
                )
                trades.append({
                    "meeting": meeting_date,
                    "bucket": position["bucket"],
                    "entry_price": position["entry_price"],
                    "exit_type": "overtagen",
                    "exit_value": exit_price,
                    "exit_date": d,
                    "pnl": exit_price / position["entry_price"] - 1.0,
                })
                position = None

            if position is None and leader_p >= threshold and leader_p > leader_P:
                position = {"bucket": leader_bucket, "entry_price": leader_P}

        if position is not None:
            open_ended = bool(g[g["bp_delta"] == position["bucket"]].iloc[0]["open_ended"])
            payoff = 1.0 if is_actual_outcome(actual_by_meeting, meeting_date, position["bucket"], open_ended) else 0.0
            trades.append({
                "meeting": meeting_date,
                "bucket": position["bucket"],
                "entry_price": position["entry_price"],
                "exit_type": "avgörs",
                "exit_date": d,
                "exit_value": payoff,
                "pnl": payoff / position["entry_price"] - 1.0,
            })

    return pd.DataFrame(trades)


def summarize(trades: pd.DataFrame, n_meetings_settled: int) -> dict:
    if trades.empty:
        return {"n_trades": 0}
    per_meeting = trades.groupby("meeting")["pnl"].sum()
    return {
        "n_trades": len(trades),
        "n_meetings_settled": n_meetings_settled,
        "n_meetings_traded": trades["meeting"].nunique(),
        "n_meetings_negative": int((per_meeting < 0).sum()),
        "mean_pnl_per_meeting": per_meeting.mean(),
        "hit_rate": (trades["pnl"] > 0).mean(),
    }


def main() -> None:
    thresholds = [float(a) / 100 for a in sys.argv[1:]] or [0.5, 0.6, 0.7]
    settled, actual_by_meeting = load_settled_window()

    print(f"{'Tröskel':>8} {'Trades':>7} {'Möten':>6} {'Neg. PnL':>9} {'Snitt PnL/möte':>15} {'Hit rate':>9}")
    for T in thresholds:
        trades = run_backtest(settled, actual_by_meeting, T)
        s = summarize(trades, settled["meeting_date_only"].nunique())
        print(
            f"{T:>7.0%} {s['n_trades']:>7} {s['n_meetings_settled']:>6} "
            f"{s['n_meetings_negative']:>9} {s['mean_pnl_per_meeting']:>14.2f}kr {s['hit_rate']:>8.1%}"
        )

    ref_T = 0.6 if 0.6 in thresholds else thresholds[0]
    trades = run_backtest(settled, actual_by_meeting, ref_T)
    print(f"\nExit-typ-nedbrytning vid T={ref_T:.0%}:")
    print(trades.groupby("exit_type")["pnl"].agg(["count", "mean", "min", "max"]).round(4))

    total_pnl = trades.groupby("meeting")["pnl"].sum()
    sept_2024 = pd.Timestamp("2024-09-18").date()
    if sept_2024 in total_pnl.index:
        share = total_pnl[sept_2024] / total_pnl.sum()
        print(f"\nSeptember 2024 andel av total PnL vid T={ref_T:.0%}: {share:.1%}")


if __name__ == "__main__":
    main()

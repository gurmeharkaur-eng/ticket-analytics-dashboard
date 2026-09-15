"""The MIS-style time-period matrix engine: D-1..D-7, W-1..W-4, MTD, M-1..M-3
columns, metrics/segments as rows, color-coded red/amber/green against the
same benchmark and thresholds used everywhere else in the app (so a cell
flagged red here means the same thing as a red flag in the mined insights).

Data-availability note: these periods only contain real, distinct numbers to
the extent the loaded raw data actually spans that far back. A period with
zero tickets shows as "-", not a misleading 0%/0-colored cell. See
`period_coverage` for a per-period ticket count the UI uses to warn when a
period is empty.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import (
    HIGH_PRIORITY_DEVIATION_PP, MEDIUM_PRIORITY_DEVIATION_PP, OPPORTUNITY_DEVIATION_PP,
    TAT_DEVIATION_FLAG_PCT,
)
from src.performance import Benchmark

RED = "#FCA5A5"
AMBER = "#FDE68A"
GREEN = "#86EFAC"
NO_DATA = "-"

# Resolution Rate / In-TAT% / Avg TAT for the freshest 1-2 days are not a
# fair read: most of a "today" or "yesterday" cohort's tickets haven't had
# time to resolve yet, so Resolution Rate reads artificially LOW (censored -
# not actually underperformance) while Avg TAT of the few that HAVE already
# resolved reads artificially LOW too (survivorship bias - only the fastest
# tickets close same-day). Coloring these periods by the same rule as mature
# ones would flag "today" red almost every time regardless of true
# performance, training the reader to ignore the color system. Raw counts
# (Volume, Backlog#) aren't subject to this bias and stay colored/uncolored
# on the normal rule.
IMMATURE_RATE_PERIODS = {"D-1", "D-2"}


def period_definitions(as_of: pd.Timestamp) -> list[tuple[str, pd.Timestamp, pd.Timestamp]]:
    """[(label, start_date, end_date)], both bounds inclusive, whole days."""
    as_of_day = pd.Timestamp(as_of).normalize()
    periods = []
    for i in range(1, 8):
        d = as_of_day - pd.Timedelta(days=i - 1)
        periods.append((f"D-{i}", d, d))
    for w in range(1, 5):
        end = as_of_day - pd.Timedelta(days=7 * (w - 1))
        start = end - pd.Timedelta(days=6)
        periods.append((f"W-{w}", start, end))
    month_start = as_of_day.replace(day=1)
    periods.append(("MTD", month_start, as_of_day))
    for m in range(1, 4):
        this_month_start = month_start - pd.DateOffset(months=m - 1)
        prev_month_start = this_month_start - pd.DateOffset(months=1)
        prev_month_end = this_month_start - pd.Timedelta(days=1)
        periods.append((f"M-{m}", prev_month_start, prev_month_end))
    return periods


def period_mask(c: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    created_day = c["Created"].dt.normalize()
    return (created_day >= start) & (created_day <= end)


def period_coverage(c: pd.DataFrame, periods: list[tuple[str, pd.Timestamp, pd.Timestamp]]) -> dict[str, int]:
    """Actual ticket count per period - used to warn the reader when a
    period (e.g. M-3) has too little or no data behind it to trust."""
    return {label: int(period_mask(c, start, end).sum()) for label, start, end in periods}


def _rate_color(dev: float, higher_is_better: bool = True) -> str | None:
    if pd.isna(dev):
        return None
    d = dev if higher_is_better else -dev
    if d <= -HIGH_PRIORITY_DEVIATION_PP:
        return RED
    if d <= -MEDIUM_PRIORITY_DEVIATION_PP:
        return AMBER
    if d >= OPPORTUNITY_DEVIATION_PP:
        return GREEN
    return None


def _tat_color(value: float, benchmark: float) -> str | None:
    if pd.isna(value) or pd.isna(benchmark) or benchmark == 0:
        return None
    rel = (value - benchmark) / benchmark
    if rel >= TAT_DEVIATION_FLAG_PCT:
        return RED
    if rel >= TAT_DEVIATION_FLAG_PCT / 2:
        return AMBER
    if rel <= -TAT_DEVIATION_FLAG_PCT / 2:
        return GREEN
    return None


def overall_matrix_rows(c: pd.DataFrame, periods: list[tuple[str, pd.Timestamp, pd.Timestamp]],
                         bm: Benchmark) -> list[dict]:
    bm_in_tat = c["InTAT"].mean()
    rows_def = [
        ("Total Tickets #", "count", None, None),
        ("Backlog #", "backlog_count", None, None),
        ("Backlog %", "backlog_pct", bm.total_backlog / bm.total if bm.total else 0, False),
        ("Resolved+Closed %", "resolution_rate", bm.resolution_rate, True),
        ("Resolved In TAT %", "in_tat_pct", bm_in_tat, True),
        ("Resolved Out of TAT %", "out_tat_pct", 1 - bm_in_tat if pd.notna(bm_in_tat) else np.nan, False),
        ("Median Resolution TAT (hrs)", "median_res_tat", bm.median_res_tat, "tat"),
        ("Median First Response TAT (hrs)", "median_fr_tat", bm.median_fr_tat, "tat"),
    ]
    rows = []
    for label, kind, bench, higher_is_better in rows_def:
        values = {}
        for plabel, start, end in periods:
            sub = c[period_mask(c, start, end)]
            n = len(sub)
            immature = plabel in IMMATURE_RATE_PERIODS
            if n == 0:
                values[plabel] = (NO_DATA, None)
                continue
            if kind == "count":
                values[plabel] = (f"{n:,}", None)
            elif kind == "backlog_count":
                values[plabel] = (f"{int(sub['Backlog'].sum()):,}", None)
            elif kind == "backlog_pct":
                v = sub["Backlog"].mean()
                values[plabel] = (f"{v:.0%}", None if immature else _rate_color(v - bench, higher_is_better))
            elif kind == "resolution_rate":
                v = 1 - sub["Backlog"].mean()
                values[plabel] = (f"{v:.0%}", None if immature else _rate_color(v - bench, higher_is_better))
            elif kind == "in_tat_pct":
                v = sub["InTAT"].mean()
                values[plabel] = (NO_DATA, None) if pd.isna(v) else \
                    (f"{v:.0%}", None if immature else _rate_color(v - bench, higher_is_better))
            elif kind == "out_tat_pct":
                v = sub["InTAT"].mean()
                values[plabel] = (NO_DATA, None) if pd.isna(v) else \
                    (f"{1 - v:.0%}", None if immature else _rate_color((1 - v) - bench, higher_is_better))
            elif kind in ("median_res_tat", "median_fr_tat"):
                col = "RESTAT" if kind == "median_res_tat" else "FRTAT"
                v = sub[col].median()
                values[plabel] = (NO_DATA, None) if pd.isna(v) else \
                    (f"{v:.1f}h", None if immature else _tat_color(v, bench))
        rows.append({"label": label, "values": values})
    return rows


def csat_row(c: pd.DataFrame, periods: list[tuple[str, pd.Timestamp, pd.Timestamp]]) -> dict:
    """Shown separately from the main matrix, unscored (no color) below a
    minimum response count - survey volume is too thin here (<1% response
    rate) to trust a per-period color flag."""
    values = {}
    for plabel, start, end in periods:
        sub = c[period_mask(c, start, end)]
        s = sub["SurveySentiment"].dropna()
        n = len(s)
        if n == 0:
            values[plabel] = (NO_DATA, None)
            continue
        pos = (s == "Positive").sum()
        csat = pos / n
        values[plabel] = (f"{csat:.0%} (n={n})", None)
    return {"label": "CSAT (n=responses)", "values": values}


def segment_trend_rows(c: pd.DataFrame, dim_col: str, segment_labels: list[str],
                        periods: list[tuple[str, pd.Timestamp, pd.Timestamp]], bm: Benchmark) -> list[dict]:
    """Volume + Resolution Rate row pair per segment, for the given curated
    label list (caller decides curation - top-N-by-volume plus flagged)."""
    vol: dict[str, dict] = {seg: {} for seg in segment_labels}
    rate: dict[str, dict] = {seg: {} for seg in segment_labels}
    for plabel, start, end in periods:
        sub = c[period_mask(c, start, end)]
        grp = sub.groupby(dim_col, observed=True)
        counts = grp.size()
        backlog_mean = grp["Backlog"].mean()
        immature = plabel in IMMATURE_RATE_PERIODS
        for seg in segment_labels:
            n = int(counts.get(seg, 0))
            vol[seg][plabel] = (f"{n:,}" if n else NO_DATA, None)
            if n == 0:
                rate[seg][plabel] = (NO_DATA, None)
            else:
                rr = 1 - backlog_mean.get(seg, np.nan)
                rate[seg][plabel] = (f"{rr:.0%}", None if immature else _rate_color(rr - bm.resolution_rate, True))
    rows = []
    for seg in segment_labels:
        rows.append({"label": f"{seg} - Volume", "values": vol[seg]})
        rows.append({"label": f"{seg} - Resolution Rate", "values": rate[seg]})
    return rows


def build_matrix(rows: list[dict], periods: list[tuple[str, pd.Timestamp, pd.Timestamp]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (display_df, color_df) - both indexed by row label, columned
    by period label, same shape. display_df holds pre-formatted text;
    color_df holds a CSS 'background-color: #xxxxxx' string or ''."""
    labels = [r["label"] for r in rows]
    period_labels = [p[0] for p in periods]
    data = pd.DataFrame(index=labels, columns=period_labels, dtype=object)
    colors = pd.DataFrame("", index=labels, columns=period_labels, dtype=object)
    for r in rows:
        for plabel, (txt, color) in r["values"].items():
            data.loc[r["label"], plabel] = txt
            colors.loc[r["label"], plabel] = f"background-color: {color}" if color else ""
    return data, colors

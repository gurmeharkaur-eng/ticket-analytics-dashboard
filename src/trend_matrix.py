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

# Hierarchy-level color for the "Segment" label column (Group/Type/Sales
# Person), independent of the per-cell performance colors. Streamlit's
# dataframe grid only renders Styler cell-background styling, not pandas'
# Styler.apply_index() - confirmed by testing - so this has to be a real
# data column colored the same way the performance cells are, not an
# index-styling trick.
LEVEL_COLOR = {
    0: "background-color: #1F2937; color: #FFFFFF; font-weight: 700",  # Group
    1: "background-color: #DBEAFE; color: #1E3A8A; font-weight: 600",  # Type
    2: "background-color: #EDE9FE; color: #5B21B6",                    # Sales Person
}

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
        ("Median First Response TAT (hrs)", "median_fr_tat", bm.median_fr_tat, "tat"),
        ("Median Resolution TAT (hrs)", "median_res_tat", bm.median_res_tat, "tat"),
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


_PSEUDO_SALES_PERSON = {"No Seller ID", "Unmapped Seller", "Unassigned Rep"}
# A real Unicode non-breaking space, not the HTML entity "&nbsp;" - these row
# labels go through Streamlit's dataframe grid (plain text), which doesn't
# decode HTML the way st.markdown does, so a literal "&nbsp;" would show up
# as 6 literal characters instead of an indent.
INDENT = "    "


def _entity_tat_rows(c: pd.DataFrame, mask: pd.Series, label: str,
                      periods: list[tuple[str, pd.Timestamp, pd.Timestamp]],
                      tat_col: str, bm_tat: float, indent: int) -> list[dict]:
    """Volume + Median TAT row pair for one entity, already isolated by
    `mask` (a Group, a Group x Type, or a Group x Type x Sales Person)."""
    vol_values, tat_values = {}, {}
    for plabel, start, end in periods:
        sub = c[period_mask(c, start, end) & mask]
        n = len(sub)
        immature = plabel in IMMATURE_RATE_PERIODS
        vol_values[plabel] = (f"{n:,}" if n else NO_DATA, None)
        if n == 0:
            tat_values[plabel] = (NO_DATA, None)
        else:
            v = sub[tat_col].median()
            tat_values[plabel] = (NO_DATA, None) if pd.isna(v) else \
                (f"{v:.1f}h", None if immature else _tat_color(v, bm_tat))
    pad = INDENT * indent
    return [
        {"label": f"{pad}{label} - Volume", "values": vol_values, "level": indent},
        {"label": f"{pad}{label} - Median TAT", "values": tat_values, "level": indent},
    ]


def group_summary_rows(c: pd.DataFrame, periods: list[tuple[str, pd.Timestamp, pd.Timestamp]],
                        tat_col: str, bm_tat: float, group_labels: list[str]) -> list[dict]:
    """One Volume + Median TAT row pair per Group - the always-visible
    top-level summary. Types and Sales Persons underneath are drilled into
    via per-Group / per-Type expanders in the UI (see type_summary_rows /
    person_rows_for_type), not shown here, so this stays short and
    readable regardless of how many Types or reps exist underneath."""
    rows: list[dict] = []
    for g in group_labels:
        g_mask = c["Group"] == g
        rows += _entity_tat_rows(c, g_mask, g, periods, tat_col, bm_tat, indent=0)
    return rows


def types_under_group(c: pd.DataFrame, group: str) -> list[str]:
    """Types under one Group, ranked by ticket volume - drives which
    per-Type expander to render, and in what order."""
    return c.loc[c["Group"] == group, "Type"].value_counts().index.tolist()


def type_summary_rows(c: pd.DataFrame, periods: list[tuple[str, pd.Timestamp, pd.Timestamp]],
                       tat_col: str, bm_tat: float, group: str) -> list[dict]:
    """One Volume + Median TAT row pair per Type under `group` - shown inside
    that Group's expander. Every Type gets its own row (no "Other Types"
    bucket needed: nothing is capped), so this always sums to the Group's
    total shown one level up."""
    rows: list[dict] = []
    g_mask = c["Group"] == group
    for t in types_under_group(c, group):
        gt_mask = g_mask & (c["Type"] == t)
        rows += _entity_tat_rows(c, gt_mask, t, periods, tat_col, bm_tat, indent=1)
    return rows


def person_rows_for_type(c: pd.DataFrame, periods: list[tuple[str, pd.Timestamp, pd.Timestamp]],
                          tat_col: str, bm_tat: float, group: str, type_: str) -> list[dict]:
    """One Volume + Median TAT row pair per named Sales Person working this
    Group x Type - shown inside that Type's expander. Every real, named
    Sales Person gets a row; ticket ownership with no resolvable person (No
    Seller ID / Unmapped Seller / Unassigned Rep) rolls up into a single
    "Other Reps" row since there's no name to list, so this Type's total
    (shown one level up) always equals the sum of the rows shown here."""
    gt_mask = (c["Group"] == group) & (c["Type"] == type_)
    sp_counts = c.loc[gt_mask, "SalesPerson"].value_counts()
    sp_counts = sp_counts[~sp_counts.index.isin(_PSEUDO_SALES_PERSON)]
    persons = sp_counts.index.tolist()

    rows: list[dict] = []
    for sp in persons:
        gtsp_mask = gt_mask & (c["SalesPerson"] == sp)
        rows += _entity_tat_rows(c, gtsp_mask, sp, periods, tat_col, bm_tat, indent=2)

    other_sp_mask = gt_mask & ~c["SalesPerson"].isin(persons)
    if other_sp_mask.any():
        rows += _entity_tat_rows(c, other_sp_mask, "Other Reps", periods, tat_col, bm_tat, indent=2)
    return rows


def build_matrix(rows: list[dict], periods: list[tuple[str, pd.Timestamp, pd.Timestamp]]
                  ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (display_df, color_df), same shape: a "Segment" column (the
    row label, as real data - NOT the DataFrame index, since Streamlit's
    dataframe grid doesn't render index-level Styler colors) followed by one
    column per period. display_df holds pre-formatted text; color_df holds
    a CSS 'background-color: ...' string or '' per cell, including the
    Segment column - where a row dict carries a "level" key (0/1/2 =
    Group/Type/Sales Person), the Segment cell is colored via LEVEL_COLOR;
    otherwise it's uncolored."""
    period_labels = [p[0] for p in periods]
    data = pd.DataFrame({"Segment": [r["label"] for r in rows]})
    colors = pd.DataFrame({"Segment": [LEVEL_COLOR.get(r.get("level"), "") for r in rows]})
    for plabel in period_labels:
        data[plabel] = [r["values"].get(plabel, (NO_DATA, None))[0] for r in rows]
        colors[plabel] = [
            (f"background-color: {r['values'].get(plabel, (None, None))[1]}"
             if r["values"].get(plabel, (None, None))[1] else "")
            for r in rows
        ]
    return data, colors

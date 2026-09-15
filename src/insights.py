"""Executive Summary: key figures, the data-driven narrative, and the
Actionable Items table. Mirrors the Excel workbook's Executive Summary tab -
every sentence and every action row is built from a computed figure, never
a fixed template with fixed numbers.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from config import TOP_N_FOR_TAT_OUTLIER_GUARD
from src.aggregations import group_level_table, sales_person_table, type_level_table


@dataclass
class KeyFigures:
    top_group_vol_name: str
    top_group_vol_count: int
    top_group_vol_pct: float
    top_group_bl_name: str
    top_group_bl_count: int
    top_group_bl_pct: float
    top_type_vol_name: str
    top_type_vol_count: int
    top_named_type_name: str
    top_named_type_count: int
    top_named_type_pct: float
    slow_group_name: str
    slow_group_restat: float
    top_rep_bl_name: str
    top_rep_bl_count: int
    unmapped_pct: float
    backlog7d_count: int
    backlog7d_pct: float
    oldest_backlog_days: float


def compute_key_figures(c: pd.DataFrame, reps: list[str]) -> KeyFigures:
    total = len(c)
    total_backlog = int(c["Backlog"].sum())

    ga = group_level_table(c)  # already sorted by volume desc
    top_vol = ga.iloc[0]
    ga_by_bl = ga.sort_values("Total Backlog", ascending=False)
    top_bl = ga_by_bl.iloc[0]

    ta = type_level_table(c)  # sorted by volume desc
    top_type = ta.iloc[0]
    named = ta[ta["Type"] != "Unknown"]
    top_named = named.iloc[0] if len(named) else top_type

    top_n = ga.head(TOP_N_FOR_TAT_OUTLIER_GUARD)
    slow_row = top_n.loc[top_n["Avg Resolution TAT"].idxmax()]

    sp = sales_person_table(c, reps)
    sp_reps_only = sp[sp["SalesPerson"].isin(reps)]
    top_rep = sp_reps_only.loc[sp_reps_only["Total Backlog"].idxmax()] if len(sp_reps_only) else None

    unmapped = c["MappingStatus"].isin(["No Seller ID", "Unmapped Seller"]).sum()

    bl = c[c["Backlog"] == 1]
    backlog7d = bl["AgeBucket"].isin(["7-14 Days", "14-30 Days", ">30 Days"]).sum()
    oldest = bl["AgeDays"].max() if len(bl) else 0.0

    return KeyFigures(
        top_group_vol_name=top_vol["Group"], top_group_vol_count=int(top_vol["Total Raised"]),
        top_group_vol_pct=float(top_vol["% of Total"]),
        top_group_bl_name=top_bl["Group"], top_group_bl_count=int(top_bl["Total Backlog"]),
        top_group_bl_pct=(top_bl["Total Backlog"] / total_backlog) if total_backlog else 0.0,
        top_type_vol_name=top_type["Type"], top_type_vol_count=int(top_type["Total Raised"]),
        top_named_type_name=top_named["Type"], top_named_type_count=int(top_named["Total Raised"]),
        top_named_type_pct=float(top_named["% of Total"]),
        slow_group_name=slow_row["Group"], slow_group_restat=float(slow_row["Avg Resolution TAT"]),
        top_rep_bl_name=(top_rep["SalesPerson"] if top_rep is not None else "n/a"),
        top_rep_bl_count=(int(top_rep["Total Backlog"]) if top_rep is not None else 0),
        unmapped_pct=(unmapped / total) if total else 0.0,
        backlog7d_count=int(backlog7d),
        backlog7d_pct=(backlog7d / total_backlog) if total_backlog else 0.0,
        oldest_backlog_days=float(oldest) if pd.notna(oldest) else 0.0,
    )


def build_narrative(kf: KeyFigures) -> list[str]:
    return [
        f"{kf.top_group_vol_name} is the highest-volume Group with {kf.top_group_vol_count:,} tickets "
        f"({kf.top_group_vol_pct:.1%} of all tickets); {kf.top_group_bl_name} carries the most backlog: "
        f"{kf.top_group_bl_count:,} tickets ({kf.top_group_bl_pct:.1%} of total backlog).",

        f"{kf.slow_group_name} has the slowest average Resolution TAT among the highest-volume Groups, "
        f"at {kf.slow_group_restat:.1f} hours - investigate root cause before it grows.",

        f"{kf.backlog7d_count:,} backlog tickets ({kf.backlog7d_pct:.1%} of current backlog) are already "
        f"more than 7 days old; the oldest open ticket is {kf.oldest_backlog_days:.0f} days old.",

        f"{kf.unmapped_pct:.1%} of all tickets cannot be attributed to a Sales Person (no Seller ID, or "
        f"Seller ID not present in the mapping sheet) - workload and backlog cannot be fully allocated for these.",

        f"Among Sales Reps, {kf.top_rep_bl_name} is carrying the largest backlog on file: "
        f"{kf.top_rep_bl_count:,} open tickets.",
    ]


def build_actionable_items(kf: KeyFigures) -> pd.DataFrame:
    rows = [
        ("High", f"{kf.top_group_bl_name} carries the largest share of current backlog",
         f"{kf.top_group_bl_count:,} tickets, {kf.top_group_bl_pct:.1%} of total backlog",
         "Prioritize this Group's backlog queue first (start with Pending, then Open), especially tickets "
         "aged over 7 days.",
         f"Clearing this queue would cut total backlog by up to {kf.top_group_bl_pct:.1%}"),

        ("High", f"{kf.slow_group_name} has the slowest Resolution TAT among high-volume Groups",
         f"{kf.slow_group_restat:.1f} hours average resolution time",
         "Set up an escalation path / SLA review for this Group; identify the specific Types driving the "
         "delay (see Group Analysis > Group x Type table).",
         "Bringing this Group's TAT toward the overall average would materially improve overall "
         "Resolution TAT."),

        ("High", "Backlog ageing beyond 7 days",
         f"{kf.backlog7d_count:,} tickets ({kf.backlog7d_pct:.1%} of backlog), oldest is "
         f"{kf.oldest_backlog_days:.0f} days old",
         "Run an ageing-based clearance plan: work oldest-first within each Group, starting with Pending "
         "and Re-Opened tickets.",
         "Directly reduces the tickets most likely to be driving customer escalations and SLA breaches."),

        ("Medium", "Sales Person attribution gap",
         f"{kf.unmapped_pct:.1%} of tickets have no Seller ID or an unmapped Seller ID",
         "Refresh/expand the Seller -> Sales Person mapping sheet; without it, workload and backlog cannot "
         "be allocated to the responsible rep for a large share of tickets.",
         "Improves accuracy of every Sales Person cut in this dashboard and enables rep-level "
         "accountability."),

        ("Medium", f"{kf.top_rep_bl_name} has the largest individual backlog among Sales Reps",
         f"{kf.top_rep_bl_count:,} open tickets on file",
         "Review workload allocation for this rep - confirm whether this reflects a larger seller book "
         "(workload) or a genuine backlog issue before reassigning.",
         "Prevents a single rep's backlog from becoming a bottleneck; may surface a need to rebalance "
         "seller assignments."),

        ("Low", "Type-level concentration",
         f"{kf.top_named_type_name} is the highest-volume named Type: {kf.top_named_type_count:,} tickets "
         f"({kf.top_named_type_pct:.1%} of total)",
         "Review this Type's TAT and backlog% in Type Analysis; if backlog% is high, consider a dedicated "
         "queue or macro/template response.",
         "Even a small TAT improvement on the highest-volume Type moves the overall average meaningfully."),
    ]
    return pd.DataFrame(rows, columns=["Priority", "Problem / Finding", "Evidence", "Recommended Action", "Expected Impact"])

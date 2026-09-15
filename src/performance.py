"""Group x Type performance & actionable-insight mining.

This is the code behind the CRO -> HOD -> L1 leadership dashboard: it turns
the raw Group / Type cuts into a decision-support view - ranked,
benchmarked, flagged, and reduced to a prioritized list of specific,
data-backed findings. Sales Person / Seller-level analysis intentionally
lives outside this module (and outside the primary dashboard) - the
dashboard's scope is Group and Type performance only.

Core metric: Resolution Rate = 1 - Backlog Rate (share of a segment's
tickets that are NOT currently stuck in backlog). This is the ticket-support
equivalent of a "conversion rate" - higher is better - and is compared
against the overall benchmark to flag over/under-performing segments.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from config import (
    HIGH_PRIORITY_DEVIATION_PP, MAX_ACTIONABLE_INSIGHTS, MEDIUM_PRIORITY_DEVIATION_PP,
    MIN_SEGMENT_VOLUME, OPPORTUNITY_DEVIATION_PP, TAT_DEVIATION_FLAG_PCT,
)
from src.aggregations import combo_ageing_over, group_level_table, group_type_combo_table, type_level_table


@dataclass
class Benchmark:
    total: int
    total_backlog: int
    resolution_rate: float
    avg_res_tat: float
    avg_fr_tat: float
    median_res_tat: float
    median_fr_tat: float


def compute_benchmark(c: pd.DataFrame) -> Benchmark:
    total = len(c)
    backlog = int(c["Backlog"].sum())
    return Benchmark(
        total=total, total_backlog=backlog,
        resolution_rate=1 - (backlog / total if total else 0.0),
        avg_res_tat=float(c["RESTAT"].mean()),
        avg_fr_tat=float(c["FRTAT"].mean()),
        median_res_tat=float(c["RESTAT"].median()),
        median_fr_tat=float(c["FRTAT"].median()),
    )


def _add_perf_cols(df: pd.DataFrame, bm: Benchmark, vol_col: str = "Total Raised",
                    backlog_col: str = "Total Backlog",
                    res_tat_col: str = "Median Resolution TAT") -> pd.DataFrame:
    out = df.copy()
    out["Resolution Rate"] = 1 - (out[backlog_col] / out[vol_col].replace(0, np.nan))
    out["Resolution Rate"] = out["Resolution Rate"].fillna(1.0)
    out["RR vs Benchmark (pp)"] = out["Resolution Rate"] - bm.resolution_rate
    out["TAT vs Benchmark (%)"] = (out[res_tat_col] - bm.median_res_tat) / bm.median_res_tat if bm.median_res_tat else np.nan
    out["Impact Score"] = out[vol_col] * out["RR vs Benchmark (pp)"].abs()
    out["Meets Min Volume"] = out[vol_col] >= MIN_SEGMENT_VOLUME

    def _flag(row):
        if not row["Meets Min Volume"]:
            return ""
        if row["RR vs Benchmark (pp)"] <= -HIGH_PRIORITY_DEVIATION_PP:
            return "High Priority"
        if row["RR vs Benchmark (pp)"] <= -MEDIUM_PRIORITY_DEVIATION_PP:
            return "Medium Priority"
        if row["RR vs Benchmark (pp)"] >= OPPORTUNITY_DEVIATION_PP:
            return "Opportunity"
        return ""

    out["Flag"] = out.apply(_flag, axis=1)
    out["Rank (by Volume)"] = out[vol_col].rank(ascending=False, method="min").astype(int)
    return out.sort_values(vol_col, ascending=False).reset_index(drop=True)


def group_rollup_performance(c: pd.DataFrame, bm: Benchmark | None = None) -> pd.DataFrame:
    bm = bm or compute_benchmark(c)
    return _add_perf_cols(group_level_table(c), bm)


def group_type_performance(c: pd.DataFrame, bm: Benchmark | None = None) -> pd.DataFrame:
    bm = bm or compute_benchmark(c)
    combo = group_type_combo_table(c)
    combo["% of Total"] = combo["Total Raised"] / bm.total if bm.total else 0.0
    return _add_perf_cols(combo, bm)


def type_performance(c: pd.DataFrame, bm: Benchmark | None = None) -> pd.DataFrame:
    bm = bm or compute_benchmark(c)
    return _add_perf_cols(type_level_table(c), bm)


def best_worst(df: pd.DataFrame, name_col: str, n: int = 3) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Top N and bottom N segments by RR vs Benchmark, restricted to segments
    that meet the minimum sample size - the "Best-performing" / "Worst-
    performing" highlight lists at HOD and L1 level."""
    scored = df[df["Meets Min Volume"]]
    if scored.empty:
        return scored, scored
    best = scored.sort_values("RR vs Benchmark (pp)", ascending=False).head(n)
    worst = scored.sort_values("RR vs Benchmark (pp)", ascending=True).head(n)
    return best.reset_index(drop=True), worst.reset_index(drop=True)


def _fmt_pp(x: float) -> str:
    sign = "+" if x >= 0 else ""
    return f"{sign}{x * 100:.1f}pp"


def mine_actionable_insights(c: pd.DataFrame, bm: Benchmark | None = None) -> pd.DataFrame:
    """Scans Group x Type combos for segments that cross the volume +
    deviation thresholds, and turns each into a specific, quantified
    finding. Causal language is deliberately hedged ('potential driver',
    'requires investigation') - the data proves the WHAT and HOW BIG, not
    the WHY."""
    bm = bm or compute_benchmark(c)
    findings = []

    def _add(priority, owner, finding, evidence, impact, action, impact_score):
        findings.append({
            "Priority": priority, "Area": "Group x Type", "Owner / Segment": owner,
            "Finding": finding, "Evidence": evidence, "Impact": impact,
            "Recommended Action": action, "_impact": impact_score,
        })

    gt = group_type_performance(c, bm)
    gt_flagged = gt[gt["Flag"] != ""]
    for _, row in gt_flagged.sort_values("Impact Score", ascending=False).iterrows():
        extra = int(round(row["Total Raised"] * abs(row["RR vs Benchmark (pp)"])))
        tat_note = ""
        if pd.notna(row["TAT vs Benchmark (%)"]) and abs(row["TAT vs Benchmark (%)"]) >= TAT_DEVIATION_FLAG_PCT:
            direction = "slower" if row["TAT vs Benchmark (%)"] > 0 else "faster"
            tat_note = (f" Resolution TAT is also a potential contributor: {abs(row['TAT vs Benchmark (%)']):.0%} "
                        f"{direction} than benchmark ({row['Median Resolution TAT']:.1f}h vs "
                        f"{bm.median_res_tat:.1f}h).")
        if row["Flag"] == "Opportunity":
            _add("Opportunity", row["Group | Type"],
                 f"{row['Group | Type']} contributes {row['% of Total']:.0%} of all tickets and resolves them "
                 f"{_fmt_pp(row['RR vs Benchmark (pp)'])} above the overall benchmark",
                 f"Resolution rate {row['Resolution Rate']:.1%} vs {bm.resolution_rate:.1%} benchmark, "
                 f"{row['Total Raised']:,} tickets ({row['% of Total']:.1%} of total volume).",
                 f"A best-practice pattern worth scaling - if replicated, comparable segments could close a "
                 f"meaningful share of their gap to this rate.{tat_note}",
                 "Potential driver - requires investigation: study what this queue is doing differently "
                 "(staffing, templates, escalation speed) before generalizing.",
                 row["Impact Score"])
        else:
            _add(row["Flag"], row["Group | Type"],
                 f"{row['Group | Type']} contributes {row['% of Total']:.0%} of all tickets but performs "
                 f"{_fmt_pp(row['RR vs Benchmark (pp)'])} vs the overall benchmark",
                 f"Resolution rate {row['Resolution Rate']:.1%} vs {bm.resolution_rate:.1%} benchmark, "
                 f"{row['Total Raised']:,} tickets ({row['% of Total']:.1%} of total volume), "
                 f"{row['Total Backlog']:,} currently backlogged.",
                 f"~{extra:,} tickets in this segment are backlogged beyond what the benchmark rate would predict.{tat_note}",
                 "Pattern to investigate: review handling/process/staffing for this specific Group x Type queue; "
                 "consider a dedicated clearance push or escalation path.",
                 row["Impact Score"])

    df = pd.DataFrame(findings)
    if df.empty:
        return df
    df = df.sort_values("_impact", ascending=False)
    # Quota-based selection so the list always shows a mix of problems AND
    # opportunities (not just whichever tier happens to have the most
    # high-impact segments) - roughly half High Priority, the rest split
    # between Medium Priority and Opportunity.
    quotas = {
        "High Priority": max(1, round(MAX_ACTIONABLE_INSIGHTS * 0.5)),
        "Medium Priority": max(1, round(MAX_ACTIONABLE_INSIGHTS * 0.2)),
        "Opportunity": max(1, round(MAX_ACTIONABLE_INSIGHTS * 0.3)),
    }
    picked = []
    for tier, quota in quotas.items():
        picked.append(df[df["Priority"] == tier].head(quota))
    out = pd.concat(picked)
    if len(out) < MAX_ACTIONABLE_INSIGHTS:
        remainder = df.drop(out.index).head(MAX_ACTIONABLE_INSIGHTS - len(out))
        out = pd.concat([out, remainder])
    priority_rank = {"High Priority": 0, "Medium Priority": 1, "Opportunity": 2}
    out = out.assign(_prank=out["Priority"].map(priority_rank)) \
             .sort_values(["_prank", "_impact"], ascending=[True, False]) \
             .drop(columns=["_prank"])
    return out.head(MAX_ACTIONABLE_INSIGHTS).reset_index(drop=True)


def attribution_quality(c: pd.DataFrame) -> dict:
    """Data-quality / accountability metrics the CEO/CRO view needs: what
    share of tickets can't be reliably attributed to a Type or an owner,
    and how many were re-opened - signals that undermine trust in every
    other metric if left unmonitored."""
    total = len(c)
    unknown_type = int((c["Type"] == "Unknown").sum())
    no_group = int((c["Group"] == "No Group").sum())
    unattributed_owner = int(c["MappingStatus"].isin(["No Seller ID", "Unmapped Seller"]).sum())
    reopened = int(c["Status"].str.upper().str.strip().isin(["RE-OPENED", "REOPENED"]).sum())
    return {
        "total": total,
        "unknown_type": unknown_type, "unknown_type_rate": unknown_type / total if total else 0.0,
        "no_group": no_group, "no_group_rate": no_group / total if total else 0.0,
        "unattributed_owner": unattributed_owner,
        "unattributed_owner_rate": unattributed_owner / total if total else 0.0,
        "reopened": reopened, "reopened_rate": reopened / total if total else 0.0,
    }


def executive_problem_statement(c: pd.DataFrame, bm: Benchmark | None = None, n: int = 8
                                 ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Top-N quantified Group x Type risks for the CEO/CRO 'Executive
    Problem Statement' table, ranked by the same Impact Score (volume x
    performance gap) used everywhere else in the app, enriched with each
    combo's >7-day-aged backlog. Returned alongside a SEPARATE small table
    of low-volume TAT outliers (below the minimum sample size to trust,
    but with a large deviation) - real, but never mixed into the
    structural-risk ranking, so a 2-ticket segment can't crowd out a
    genuine 500-ticket problem."""
    bm = bm or compute_benchmark(c)
    gt = group_type_performance(c, bm).copy()
    aged7 = combo_ageing_over(c, ("7-14 Days", "14-30 Days", ">30 Days"))
    gt[">7-day backlog"] = [int(aged7.get((r.Group, r.Type), 0)) for r in gt.itertuples()]

    flagged = gt[gt["Flag"] != ""].sort_values("Impact Score", ascending=False).head(n)
    rows = []
    for _, r in flagged.iterrows():
        extra = int(round(r["Total Raised"] * abs(r["RR vs Benchmark (pp)"])))
        if r["Flag"] == "Opportunity":
            implication = (f"Best-practice pattern - {r['Resolution Rate']:.1%} resolution rate vs "
                            f"{bm.resolution_rate:.1%} benchmark on {int(r['Total Raised']):,} tickets.")
            decision = "Study what this queue is doing differently before generalizing to other segments."
        else:
            implication = (f"~{extra:,} tickets backlogged beyond what the benchmark rate would predict; "
                            f"{r['>7-day backlog']:,} already aged past 7 days.")
            decision = ("Review handling/process/staffing for this Group x Type queue; consider a dedicated "
                         "clearance push or escalation path.")
        rows.append({
            "Priority": r["Flag"], "Group": r["Group"], "Type": r["Type"],
            "Volume": int(r["Total Raised"]), "Backlog": int(r["Total Backlog"]),
            "Backlog %": r["% Backlog"], "Avg FR TAT": r["Avg First Resp TAT"],
            "Avg Resolution TAT": r["Avg Resolution TAT"], ">7-day backlog": r[">7-day backlog"],
            "Business Implication": implication, "Decision Required": decision,
        })
    problem_df = pd.DataFrame(rows)

    low_vol = gt[(~gt["Meets Min Volume"]) & (gt["RR vs Benchmark (pp)"].abs() >= HIGH_PRIORITY_DEVIATION_PP)] \
        .sort_values("RR vs Benchmark (pp)")[["Group", "Type", "Total Raised", "Resolution Rate", "RR vs Benchmark (pp)"]]
    return problem_df, low_vol.reset_index(drop=True)

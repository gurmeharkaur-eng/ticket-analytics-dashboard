"""Group x Type x Sales performance & actionable-insight mining.

This is the code behind the consolidated 'Group, Type & Sales Performance'
tab: it turns the raw Group/Type/Sales Person cuts into a decision-support
view - ranked, benchmarked, flagged, and reduced to a prioritized list of
specific, data-backed findings.

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
    CURATED_TOP_N, HIGH_PRIORITY_DEVIATION_PP, MAX_ACTIONABLE_INSIGHTS, MEDIUM_PRIORITY_DEVIATION_PP,
    MIN_SEGMENT_VOLUME, OPPORTUNITY_DEVIATION_PP, TAT_DEVIATION_FLAG_PCT,
)
from src.aggregations import group_level_table, group_type_combo_table, sales_person_table, type_level_table


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
                    backlog_col: str = "Total Backlog", res_tat_col: str = "Avg Resolution TAT") -> pd.DataFrame:
    out = df.copy()
    out["Resolution Rate"] = 1 - (out[backlog_col] / out[vol_col].replace(0, np.nan))
    out["Resolution Rate"] = out["Resolution Rate"].fillna(1.0)
    out["RR vs Benchmark (pp)"] = out["Resolution Rate"] - bm.resolution_rate
    out["TAT vs Benchmark (%)"] = (out[res_tat_col] - bm.avg_res_tat) / bm.avg_res_tat if bm.avg_res_tat else np.nan
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


def curate(df: pd.DataFrame, vol_col: str = "Total Raised", n: int = CURATED_TOP_N) -> pd.DataFrame:
    """Top-N by volume, UNIONED with any flagged row outside the top N - a
    real problem is never hidden just because the segment isn't top-volume.
    This is what keeps 'Performance Drivers' tables from turning into the
    full 21/82/89-row dump; the full tables still exist for reconciliation
    (Data Quality tab) and full detail (Detailed Data tab)."""
    top = df.head(n)
    extra = df[(df["Flag"] != "") & (~df.index.isin(top.index))] if "Flag" in df.columns else df.iloc[0:0]
    out = pd.concat([top, extra]).sort_values(vol_col, ascending=False)
    return out.reset_index(drop=True)


def classify_quadrant(df: pd.DataFrame, vol_col: str = "Total Raised") -> pd.DataFrame:
    """Volume x Performance quadrant, only for segments meeting the minimum
    sample size (everything else is 'Not enough data'). High/Low volume
    split is the median volume among segments that meet the minimum - i.e.
    relative to peers actually being compared, not an arbitrary cutoff.
    'Good'/'Poor' require a meaningful deviation (the same threshold used
    for flagging elsewhere) - a segment only marginally above or below
    benchmark is 'Near Benchmark', not forced into a quadrant."""
    out = df.copy()
    scored = out[out["Meets Min Volume"]]
    vol_median = scored[vol_col].median() if len(scored) else 0

    def _label(row):
        if not row["Meets Min Volume"]:
            return "Not enough data"
        high_vol = row[vol_col] >= vol_median
        dev = row["RR vs Benchmark (pp)"]
        if dev >= OPPORTUNITY_DEVIATION_PP:
            return "Best Practice - Scale" if high_vol else "Potential Opportunity"
        if dev <= -MEDIUM_PRIORITY_DEVIATION_PP:
            return "High Priority" if high_vol else "Low Priority"
        return "Near Benchmark"

    out["Quadrant"] = out.apply(_label, axis=1)
    return out


def sales_performance(c: pd.DataFrame, reps: list[str], bm: Benchmark | None = None) -> pd.DataFrame:
    bm = bm or compute_benchmark(c)
    sp = sales_person_table(c, reps).rename(columns={"SalesPerson": "Sales Person"})
    sp = sp[sp["Sales Person"].isin(reps)].reset_index(drop=True)  # reps only, not the 3 pseudo categories
    out = _add_perf_cols(sp, bm)

    vol_median = out["Total Raised"].median()

    def _segment(row):
        if not row["Meets Min Volume"]:
            return "Low volume (not enough tickets to assess)"
        high_vol = row["Total Raised"] >= vol_median
        if row["RR vs Benchmark (pp)"] >= OPPORTUNITY_DEVIATION_PP:
            return "Low-volume, high-performing" if not high_vol else "High performer"
        # Uses the same -5pp threshold as the Medium Priority Flag (not the
        # stricter -10pp High Priority one) so a rep never gets tagged
        # "Typical" in one place while being flagged as a problem elsewhere.
        if row["RR vs Benchmark (pp)"] <= -MEDIUM_PRIORITY_DEVIATION_PP:
            return "High-volume, low-performing" if high_vol else "Low performer"
        return "Typical / near benchmark"

    out["Segment"] = out.apply(_segment, axis=1)
    return out


def rep_primary_group_outliers(c: pd.DataFrame, reps: list[str], bm: Benchmark | None = None,
                                top_n: int = 5) -> pd.DataFrame:
    """For reps with enough tickets in their single largest Group, compare
    their Resolution Rate there to that Group's own average - surfaces reps
    who are unusually strong or weak within the specific segment they
    actually work, not just against the company-wide benchmark."""
    bm = bm or compute_benchmark(c)
    rows = []
    reps_c = c[c["SalesPerson"].isin(reps)]
    for rep, sub in reps_c.groupby("SalesPerson", observed=True):
        by_group = sub["Group"].value_counts()
        if by_group.empty:
            continue
        primary_group = by_group.index[0]
        rep_in_group = sub[sub["Group"] == primary_group]
        if len(rep_in_group) < MIN_SEGMENT_VOLUME:
            continue
        group_all = c[c["Group"] == primary_group]
        if len(group_all) < MIN_SEGMENT_VOLUME:
            continue
        rep_rr = 1 - rep_in_group["Backlog"].mean()
        group_rr = 1 - group_all["Backlog"].mean()
        dev = rep_rr - group_rr
        if abs(dev) < MEDIUM_PRIORITY_DEVIATION_PP:
            continue
        rows.append({
            "Sales Person": rep, "Primary Group": primary_group,
            "Tickets in Primary Group": len(rep_in_group),
            "Rep Resolution Rate (this Group)": rep_rr,
            "Group Average Resolution Rate": group_rr,
            "Deviation (pp)": dev,
            "Direction": "Stronger than Group average" if dev > 0 else "Weaker than Group average",
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.reindex(df["Deviation (pp)"].abs().sort_values(ascending=False).index).head(top_n).reset_index(drop=True)


def _impact_pick(df: pd.DataFrame, positive: bool):
    """Row with the largest Impact Score among positive (or negative) deviations
    - i.e. impact-weighted, not just the most extreme percentage."""
    sub = df[df["RR vs Benchmark (pp)"] > 0] if positive else df[df["RR vs Benchmark (pp)"] < 0]
    if sub.empty:
        return None
    return sub.loc[sub["Impact Score"].idxmax()]


def performance_snapshot(c: pd.DataFrame, reps: list[str], bm: Benchmark | None = None) -> dict:
    """Best/worst Group, Type, and Sales Rep by Resolution Rate (impact-weighted
    among segments meeting the minimum sample size) - the 'Performance
    Snapshot' at the top of the section."""
    bm = bm or compute_benchmark(c)
    grp = group_rollup_performance(c, bm).pipe(lambda d: d[d["Meets Min Volume"]])
    typ = type_performance(c, bm).pipe(lambda d: d[d["Meets Min Volume"]])
    sp = sales_performance(c, reps, bm).pipe(lambda d: d[d["Meets Min Volume"]])

    def _best_worst(df, name_col):
        if df.empty:
            return None, None
        best = df.loc[df["RR vs Benchmark (pp)"].idxmax()]
        worst = df.loc[df["RR vs Benchmark (pp)"].idxmin()]
        return best, worst

    best_group, worst_group = _best_worst(grp, "Group")
    best_type, worst_type = _best_worst(typ, "Type")
    best_rep, _ = _best_worst(sp, "Sales Person")

    return {
        "benchmark": bm, "best_group": best_group, "worst_group": worst_group,
        "best_type": best_type, "worst_type": worst_type, "best_rep": best_rep,
    }


def key_findings(c: pd.DataFrame, reps: list[str], bm: Benchmark | None = None) -> dict:
    bm = bm or compute_benchmark(c)
    gt_scored = group_type_performance(c, bm).pipe(lambda d: d[d["Meets Min Volume"]])
    sp_scored = sales_performance(c, reps, bm).pipe(lambda d: d[d["Meets Min Volume"]])

    return {
        "benchmark": bm,
        "biggest_positive_gt": _impact_pick(gt_scored, True),
        "biggest_risk_gt": _impact_pick(gt_scored, False),
        "biggest_positive_rep": _impact_pick(sp_scored, True),
        "biggest_risk_rep": _impact_pick(sp_scored, False),
    }


def _fmt_pp(x: float) -> str:
    sign = "+" if x >= 0 else ""
    return f"{sign}{x * 100:.1f}pp"


def mine_actionable_insights(c: pd.DataFrame, reps: list[str], bm: Benchmark | None = None) -> pd.DataFrame:
    """Systematically scans Group x Type, Sales Rep, and Rep-within-Group cuts
    for segments that cross the volume + deviation thresholds, and turns each
    into a specific, quantified finding. Causal language is deliberately
    hedged ('potential driver', 'requires investigation') - the data proves
    the WHAT and HOW BIG, not the WHY."""
    bm = bm or compute_benchmark(c)
    findings = []

    def _add(priority, area, owner, finding, evidence, impact, action, impact_score):
        findings.append({
            "Priority": priority, "Area": area, "Owner / Segment": owner,
            "Finding": finding, "Evidence": evidence, "Impact": impact,
            "Recommended Action": action, "_impact": impact_score,
        })

    # --- Group x Type combos: problems and opportunities --------------------
    gt = group_type_performance(c, bm)
    gt_flagged = gt[gt["Flag"] != ""]
    for _, row in gt_flagged.sort_values("Impact Score", ascending=False).iterrows():
        extra = int(round(row["Total Raised"] * abs(row["RR vs Benchmark (pp)"])))
        tat_note = ""
        if pd.notna(row["TAT vs Benchmark (%)"]) and abs(row["TAT vs Benchmark (%)"]) >= TAT_DEVIATION_FLAG_PCT:
            direction = "slower" if row["TAT vs Benchmark (%)"] > 0 else "faster"
            tat_note = f" Resolution TAT is also a potential contributor: {abs(row['TAT vs Benchmark (%)']):.0%} {direction} than benchmark ({row['Avg Resolution TAT']:.1f}h vs {bm.avg_res_tat:.1f}h)."
        if row["Flag"] == "Opportunity":
            _add("Opportunity", "Group x Type", row["Group | Type"],
                 f"{row['Group | Type']} contributes {row['% of Total']:.0%} of all tickets and resolves them "
                 f"{_fmt_pp(row['RR vs Benchmark (pp)'])} above the overall benchmark",
                 f"Resolution rate {row['Resolution Rate']:.1%} vs {bm.resolution_rate:.1%} benchmark, "
                 f"{row['Total Raised']:,} tickets ({row['% of Total']:.1%} of total volume).",
                 f"A best-practice pattern worth scaling - if replicated, comparable segments could close a "
                 f"meaningful share of their gap to this rate.{tat_note}",
                 "Potential driver - requires investigation: study what this queue/team is doing differently "
                 "(staffing, templates, escalation speed) before generalizing.",
                 row["Impact Score"])
        else:
            _add(row["Flag"], "Group x Type", row["Group | Type"],
                 f"{row['Group | Type']} contributes {row['% of Total']:.0%} of all tickets but performs "
                 f"{_fmt_pp(row['RR vs Benchmark (pp)'])} vs the overall benchmark",
                 f"Resolution rate {row['Resolution Rate']:.1%} vs {bm.resolution_rate:.1%} benchmark, "
                 f"{row['Total Raised']:,} tickets ({row['% of Total']:.1%} of total volume), "
                 f"{row['Total Backlog']:,} currently backlogged.",
                 f"~{extra:,} tickets in this segment are backlogged beyond what the benchmark rate would predict.{tat_note}",
                 "Pattern to investigate: review handling/process/staffing for this specific Group x Type queue; "
                 "consider a dedicated clearance push or escalation path.",
                 row["Impact Score"])

    # --- Sales reps: problems and opportunities ------------------------------
    sp = sales_performance(c, reps, bm)
    sp_flagged = sp[sp["Flag"] != ""]
    for _, row in sp_flagged.sort_values("Impact Score", ascending=False).iterrows():
        extra = int(round(row["Total Raised"] * abs(row["RR vs Benchmark (pp)"])))
        if row["Flag"] == "Opportunity":
            _add("Opportunity", "Sales Rep", row["Sales Person"],
                 f"{row['Sales Person']} resolves tickets {_fmt_pp(row['RR vs Benchmark (pp)'])} above benchmark "
                 f"on {row['Total Raised']:,} tickets",
                 f"Resolution rate {row['Resolution Rate']:.1%} vs {bm.resolution_rate:.1%} benchmark. "
                 f"Segment: {row['Segment']}.",
                 "A rep materially outperforming benchmark at meaningful volume is a best-practice source.",
                 f"Potential driver - requires investigation: have {row['Sales Person']} share their approach "
                 f"(response cadence, escalation habits) with reps flagged as underperforming in the same Group(s).",
                 row["Impact Score"])
        else:
            _add(row["Flag"], "Sales Rep", row["Sales Person"],
                 f"{row['Sales Person']} performs {_fmt_pp(row['RR vs Benchmark (pp)'])} vs benchmark on "
                 f"{row['Total Raised']:,} tickets ({row['Segment']})",
                 f"Resolution rate {row['Resolution Rate']:.1%} vs {bm.resolution_rate:.1%} benchmark, "
                 f"{row['Total Backlog']:,} backlogged.",
                 f"~{extra:,} tickets tied to this rep are backlogged beyond the benchmark rate - "
                 + ("a high-volume rep, so this materially affects overall backlog." if row["Segment"] == "High-volume, low-performing"
                    else "a meaningful, addressable gap."),
                 ("Pattern to investigate: review this rep's workload allocation and queue mix - confirm whether "
                  "this is a genuine performance gap or a harder book of sellers/tickets before coaching." if row["Segment"] == "High-volume, low-performing"
                  else "Pair with a high performer or review their ticket queue for process gaps."),
                 row["Impact Score"])

    # --- Rep x Primary Group outliers ---------------------------------------
    outliers = rep_primary_group_outliers(c, reps, bm)
    for _, row in outliers.iterrows():
        direction_word = "outperforming" if row["Deviation (pp)"] > 0 else "underperforming"
        priority = "Opportunity" if row["Deviation (pp)"] > 0 else (
            "High Priority" if row["Deviation (pp)"] <= -HIGH_PRIORITY_DEVIATION_PP else "Medium Priority")
        _add(priority, "Sales Rep x Group", f"{row['Sales Person']} in {row['Primary Group']}",
             f"{row['Sales Person']} is {direction_word} {row['Primary Group']} peers by "
             f"{_fmt_pp(row['Deviation (pp)'])}, not just the company benchmark",
             f"{row['Rep Resolution Rate (this Group)']:.1%} resolution rate vs {row['Group Average Resolution Rate']:.1%} "
             f"{row['Primary Group']} average, on {row['Tickets in Primary Group']:,} tickets in this Group.",
             "This isolates the rep's performance from the company-wide benchmark, comparing them only to peers "
             "working the same Group - a fairer, segment-specific read on individual performance.",
             ("Recognize and document what this rep is doing differently within this Group." if row["Deviation (pp)"] > 0
              else f"Targeted coaching or workload review for {row['Sales Person']} specifically within {row['Primary Group']}."),
             row["Tickets in Primary Group"] * abs(row["Deviation (pp)"]) * 5)  # weighted to compete fairly with larger cuts

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
    # `_impact` is kept (not dropped) so callers combining this list with
    # other mined-insight lists (e.g. report.py's Group x Type + Sales Rep +
    # Seller merge) can still sort the combined pool consistently. Drop it
    # at display time if rendering this DataFrame directly as a table.
    return out.head(MAX_ACTIONABLE_INSIGHTS).reset_index(drop=True)


def management_focus(insights_df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """The top N findings for the 'Management Focus' headline panel - already
    sorted by priority tier then business impact, so this is simply the head
    of the full mined list."""
    return insights_df.head(n)

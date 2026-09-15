"""TAT diagnostics: where delay is concentrated, how severe it is, and what
segments/owners disproportionately drive it.

Core technique: CONCENTRATION RATIO = (segment's share of a slow-TAT bucket)
/ (segment's share of overall ticket volume). A ratio of 1.0 means the
segment is represented in the slow bucket exactly proportional to its size;
above ~1.3 means it's genuinely overrepresented among the delayed tickets,
not just large. This is what lets a mid-size segment outrank a huge one that
merely has more tickets everywhere, including the slow bucket.
"""
from __future__ import annotations

import pandas as pd

from config import (
    MAX_TAT_INSIGHTS, MIN_BUCKET_VOLUME_FOR_FLAG, MIN_SEGMENT_VOLUME,
    TAT_CONCENTRATION_RATIO_FLAG, TAT_DEVIATION_FLAG_PCT,
)
from src import aggregations as agg
from src.performance import Benchmark, compute_benchmark, group_rollup_performance, \
    sales_performance, type_performance


def tat_snapshot(c: pd.DataFrame, bm: Benchmark | None = None) -> dict:
    bm = bm or compute_benchmark(c)
    total = len(c)
    fr_over24 = int((c["FRBucket"] == ">24h").sum())
    res_over24 = int((c["RESBucket"] == ">24h").sum())
    return {
        "avg_fr_tat": bm.avg_fr_tat, "avg_res_tat": bm.avg_res_tat,
        "median_fr_tat": float(c["FRTAT"].median()), "median_res_tat": float(c["RESTAT"].median()),
        "fr_over24_count": fr_over24, "fr_over24_pct": fr_over24 / total if total else 0.0,
        "res_over24_count": res_over24, "res_over24_pct": res_over24 / total if total else 0.0,
        "fr_valid": int(c["FRTAT"].notna().sum()), "res_valid": int(c["RESTAT"].notna().sum()),
    }


def concentration_table(c: pd.DataFrame, dim_col: str, bucket_col: str,
                         target_bucket: str = ">24h") -> pd.DataFrame:
    """Volume vs slow-bucket share, by Group or Type."""
    total_vol = len(c)
    total_in_bucket = int((c[bucket_col] == target_bucket).sum())
    vol_by_dim = c[dim_col].value_counts()
    bucket_by_dim = c[c[bucket_col] == target_bucket][dim_col].value_counts()

    rows = []
    for d in vol_by_dim.index:
        vol = int(vol_by_dim[d])
        in_bucket = int(bucket_by_dim.get(d, 0))
        vol_share = vol / total_vol if total_vol else 0.0
        bucket_share = in_bucket / total_in_bucket if total_in_bucket else 0.0
        ratio = (bucket_share / vol_share) if vol_share else 0.0
        flagged = (vol >= MIN_SEGMENT_VOLUME and in_bucket >= MIN_BUCKET_VOLUME_FOR_FLAG
                   and ratio >= TAT_CONCENTRATION_RATIO_FLAG)
        rows.append({
            dim_col: d, "Volume": vol, "% of Total Volume": vol_share,
            f"Tickets {target_bucket}": in_bucket, f"% of All {target_bucket} Tickets": bucket_share,
            "Concentration Ratio": ratio, "Disproportionate?": "Yes" if flagged else "",
        })
    df = pd.DataFrame(rows).sort_values(f"Tickets {target_bucket}", ascending=False).reset_index(drop=True)
    return df


def owner_tat_outliers(c: pd.DataFrame, reps: list[str], bm: Benchmark | None = None) -> pd.DataFrame:
    """Reps whose average Resolution TAT is meaningfully slower than benchmark
    at a volume that matters - a distinct signal from resolution RATE (a rep
    can keep backlog low by working fast on some tickets while still being
    slow on average, or vice versa)."""
    bm = bm or compute_benchmark(c)
    sp = sales_performance(c, reps, bm)
    sp = sp[sp["Meets Min Volume"] & sp["TAT vs Benchmark (%)"].notna()]
    out = sp[sp["TAT vs Benchmark (%)"] >= TAT_DEVIATION_FLAG_PCT].copy()
    out["TAT Impact Score"] = out["Total Raised"] * out["TAT vs Benchmark (%)"]
    return out.sort_values("TAT Impact Score", ascending=False)[
        ["Sales Person", "Total Raised", "Avg Resolution TAT", "TAT vs Benchmark (%)", "Resolution Rate"]
    ].reset_index(drop=True)


def ageing_concentration(c: pd.DataFrame, dim_col: str, age_buckets=("14-30 Days", ">30 Days")) -> pd.DataFrame:
    """Same concentration logic, applied to aged backlog instead of a TAT
    bucket - surfaces where old, stuck tickets are piling up disproportionately
    to a segment's overall backlog share. `age_buckets` should be a
    suffix-contiguous slice of AGE_BUCKETS (e.g. the two oldest, or the three
    oldest) - the column label is derived from it automatically."""
    col_label = f"Aged Backlog ({age_buckets[0].split()[0].lstrip('>').split('-')[0]}+ days)" \
        if "-" in age_buckets[0] else f"Aged Backlog ({age_buckets[0]})"
    bl = c[c["Backlog"] == 1]
    total_backlog = len(bl)
    aged = bl[bl["AgeBucket"].isin(age_buckets)]
    total_aged = len(aged)
    backlog_by_dim = bl[dim_col].value_counts()
    aged_by_dim = aged[dim_col].value_counts()

    rows = []
    for d in backlog_by_dim.index:
        seg_backlog = int(backlog_by_dim[d])
        seg_aged = int(aged_by_dim.get(d, 0))
        backlog_share = seg_backlog / total_backlog if total_backlog else 0.0
        aged_share = seg_aged / total_aged if total_aged else 0.0
        ratio = (aged_share / backlog_share) if backlog_share else 0.0
        flagged = (seg_backlog >= MIN_SEGMENT_VOLUME and seg_aged >= MIN_BUCKET_VOLUME_FOR_FLAG
                   and ratio >= TAT_CONCENTRATION_RATIO_FLAG)
        rows.append({
            dim_col: d, "Total Backlog": seg_backlog, "% of Total Backlog": backlog_share,
            col_label: seg_aged, "% of All Aged Backlog": aged_share,
            "Concentration Ratio": ratio, "Disproportionate?": "Yes" if flagged else "",
        })
    df = pd.DataFrame(rows).sort_values(col_label, ascending=False).reset_index(drop=True)
    df.attrs["age_col"] = col_label
    return df


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def mine_tat_insights(c: pd.DataFrame, reps: list[str], bm: Benchmark | None = None) -> pd.DataFrame:
    bm = bm or compute_benchmark(c)
    findings = []

    def _add(priority, area, finding, volume_impact, driver, action, impact_score):
        findings.append({
            "Priority": priority, "Area": area, "TAT Problem": finding,
            "Volume Impact": volume_impact, "Driver / Pattern": driver,
            "Recommended Action": action, "_impact": impact_score,
        })

    # --- Disproportionate share of >24h Resolution TAT, by Group and Type ---
    for dim_col in ("Group", "Type"):
        conc = concentration_table(c, dim_col, "RESBucket", ">24h")
        flagged = conc[conc["Disproportionate?"] == "Yes"].sort_values("Concentration Ratio", ascending=False)
        flagged_names = set(flagged[dim_col])
        for _, row in flagged.head(6).iterrows():
            impact_score = row[f"Tickets >24h"] * row["Concentration Ratio"]
            _add(
                "High Priority" if row["Concentration Ratio"] >= 1.6 else "Medium Priority",
                dim_col,
                f"{row[dim_col]} represents {_fmt_pct(row['% of Total Volume'])} of tickets but "
                f"{_fmt_pct(row['% of All >24h Tickets'])} of all >24h Resolution TAT tickets",
                f"{row['Tickets >24h']:,} tickets >24h ({row['Concentration Ratio']:.1f}x its expected share)",
                "Pattern to investigate: disproportionate ageing concentrated in this segment - process, "
                "staffing, or ticket-complexity bottleneck (not proven by this data alone).",
                f"Review this {dim_col.lower()}'s queue specifically for >24h tickets; prioritize a clearance "
                "pass before it compounds into aged backlog.",
                impact_score,
            )
        # A segment can be the single largest source of >24h tickets in ABSOLUTE
        # terms without tripping the ratio flag (it's already large everywhere,
        # including the slow bucket) - that's still the most important fact for
        # a founder, so it's surfaced separately rather than only via ratio.
        top_absolute = conc[(conc["% of All >24h Tickets"] >= 0.30) & (~conc[dim_col].isin(flagged_names))]
        for _, row in top_absolute.head(2).iterrows():
            _add(
                "High Priority", dim_col,
                f"{row[dim_col]} is the single largest source of >24h Resolution TAT tickets: "
                f"{_fmt_pct(row['% of All >24h Tickets'])} of all of them",
                f"{row['Tickets >24h']:,} tickets >24h, out of {row['Volume']:,} total tickets in this segment",
                "Largely proportional to this segment's overall size (not disproportionately represented), "
                "but its sheer scale makes it the highest-leverage place to fix TAT company-wide.",
                f"Even a modest TAT improvement here would move the company-wide >24h rate more than any "
                f"other single segment - prioritize for process/staffing review.",
                row["Tickets >24h"] * 2.5,
            )

    # --- Aged backlog concentration, by Group ---------------------------------
    # Uses >14 days as the standard "genuinely aged" threshold; if the current
    # data window is too short for anything to have reached that age yet, falls
    # back to >7 days so the check still says something useful about this run.
    aged_buckets = ("14-30 Days", ">30 Days")
    if c.loc[c["Backlog"] == 1, "AgeBucket"].isin(aged_buckets).sum() == 0:
        aged_buckets = ("7-14 Days", "14-30 Days", ">30 Days")
    aged_conc = ageing_concentration(c, "Group", aged_buckets)
    age_col = aged_conc.attrs.get("age_col", "Aged Backlog")
    age_label = ">14 days" if aged_buckets[0] == "14-30 Days" else ">7 days"
    flagged_aged = aged_conc[aged_conc["Disproportionate?"] == "Yes"].sort_values("Concentration Ratio", ascending=False)
    for _, row in flagged_aged.head(4).iterrows():
        impact_score = row[age_col] * row["Concentration Ratio"] * 3
        _add(
            "High Priority", "Group",
            f"{row['Group']} holds {_fmt_pct(row['% of Total Backlog'])} of total backlog but "
            f"{_fmt_pct(row['% of All Aged Backlog'])} of backlog aged {age_label}",
            f"{row[age_col]:,} tickets aged {age_label} ({row['Concentration Ratio']:.1f}x its "
            "expected share of aged backlog)",
            "Pattern to investigate: tickets in this Group are not just backlogged but stuck - aged well "
            "past the point most tickets clear.",
            f"Run a dedicated ageing clearance push for {row['Group']}; identify the oldest tickets first "
            "(see Backlog & Ageing tab for the full breakdown).",
            impact_score,
        )

    # --- Reps with unusually high average Resolution TAT --------------------
    owners = owner_tat_outliers(c, reps, bm)
    for _, row in owners.head(4).iterrows():
        impact_score = row["Total Raised"] * row["TAT vs Benchmark (%)"]
        _add(
            "Medium Priority", "Sales Rep",
            f"{row['Sales Person']}'s average Resolution TAT is {_fmt_pct(row['TAT vs Benchmark (%)'])} slower "
            f"than benchmark on {row['Total Raised']:,} tickets",
            f"{row['Avg Resolution TAT']:.1f}h average vs {bm.avg_res_tat:.1f}h benchmark",
            "Pattern to investigate: distinct from backlog rate - this rep's tickets take longer to close on "
            "average even where they do get resolved.",
            f"Review {row['Sales Person']}'s ticket queue mix and escalation habits; confirm whether this "
            "reflects harder tickets or a process gap before coaching.",
            impact_score,
        )

    df = pd.DataFrame(findings)
    if df.empty:
        return df
    df = df.sort_values("_impact", ascending=False)
    # Quota so High Priority volume/concentration findings don't crowd out
    # every Medium Priority owner-level finding (e.g. individual reps with
    # slow TAT) - about 2/3 High, 1/3 Medium.
    quotas = {"High Priority": max(1, round(MAX_TAT_INSIGHTS * 0.65)),
              "Medium Priority": max(1, round(MAX_TAT_INSIGHTS * 0.35))}
    picked = [df[df["Priority"] == tier].head(q) for tier, q in quotas.items()]
    out = pd.concat(picked)
    if len(out) < MAX_TAT_INSIGHTS:
        out = pd.concat([out, df.drop(out.index).head(MAX_TAT_INSIGHTS - len(out))])
    priority_rank = {"High Priority": 0, "Medium Priority": 1, "Opportunity": 2}
    out = out.assign(_prank=out["Priority"].map(priority_rank)) \
             .sort_values(["_prank", "_impact"], ascending=[True, False]) \
             .drop(columns=["_prank", "_impact"])
    return out.head(MAX_TAT_INSIGHTS).reset_index(drop=True)

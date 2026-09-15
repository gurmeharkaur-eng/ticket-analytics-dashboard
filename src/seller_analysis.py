"""Group x Type x Seller analysis - the actual merchant/seller entity behind
a ticket (Seller ID / Seller Name), paired with the Sales Person and Team who
own that seller. This is a distinct cut from Sales Person performance
(performance.py): a seller can be a genuine operational problem (bad
packaging, address quality, process) independent of which rep manages them,
and the two lenses are meant to be read together, not confused for one
another.
"""
from __future__ import annotations

import pandas as pd

from config import MIN_SEGMENT_VOLUME, OPPORTUNITY_DEVIATION_PP, HIGH_PRIORITY_DEVIATION_PP
from src.performance import Benchmark, compute_benchmark

SELLER_KEYS = ["Group", "Type", "SellerLabel", "SellerID", "SalesPerson", "Team"]


def group_type_seller_table(c: pd.DataFrame, min_volume: int = MIN_SEGMENT_VOLUME,
                             bm: Benchmark | None = None) -> pd.DataFrame:
    """One row per (Group, Type, Seller) combination with >= min_volume
    tickets. Tickets with no Seller ID are excluded (nothing to attribute).
    Sales Person and Team are 1:1 with Seller ID, carried along as
    descriptive columns."""
    bm = bm or compute_benchmark(c)
    sub = c[c["SellerID"].notna()]
    grp = sub.groupby(SELLER_KEYS, observed=True)
    tickets = grp.size()
    avg_tat = grp["RESTAT"].mean()
    backlog = grp["Backlog"].sum()
    over16 = sub[sub["RESTAT"] > 16].groupby(SELLER_KEYS, observed=True).size()
    over24 = sub[sub["RESTAT"] > 24].groupby(SELLER_KEYS, observed=True).size()

    out = pd.DataFrame({
        "Tickets": tickets, "Avg Resolution TAT": avg_tat, "Total Backlog": backlog,
    })
    out[">16h"] = over16.reindex(out.index).fillna(0).astype(int)
    out[">24h"] = over24.reindex(out.index).fillna(0).astype(int)
    out = out[out["Tickets"] >= min_volume].reset_index()

    out["Backlog %"] = out["Total Backlog"] / out["Tickets"]
    out["Resolution Rate"] = 1 - out["Backlog %"]
    out["RR vs Benchmark (pp)"] = out["Resolution Rate"] - bm.resolution_rate
    out["Impact Score"] = out["Tickets"] * out["RR vs Benchmark (pp)"].abs()

    vol_median = out["Tickets"].median() if len(out) else 0

    def _status(row):
        high_vol = row["Tickets"] >= vol_median
        dev = row["RR vs Benchmark (pp)"]
        if dev >= OPPORTUNITY_DEVIATION_PP:
            return "Healthy"
        if dev <= -HIGH_PRIORITY_DEVIATION_PP:
            return "High-volume underperformer" if high_vol else "Low-volume outlier"
        return "Typical" if high_vol else "Low-volume outlier" if dev < 0 else "Typical"

    out["Status"] = out.apply(_status, axis=1)
    return out.sort_values("Tickets", ascending=False).reset_index(drop=True)


def top_sellers_for(gt_table: pd.DataFrame, group: str, type_: str, n: int = 3) -> pd.DataFrame:
    """Sellers for one specific Group/Type, sorted by business impact - used
    to nest sellers under a Group -> Type row in the hierarchy view."""
    sub = gt_table[(gt_table["Group"] == group) & (gt_table["Type"] == type_)]
    return sub.sort_values("Impact Score", ascending=False).head(n)


def mine_seller_insights(c: pd.DataFrame, bm: Benchmark | None = None, top_n: int = 8) -> pd.DataFrame:
    """Same finding shape as performance.mine_actionable_insights (Priority,
    Area, Owner / Segment, Finding, Evidence, Impact, Recommended Action,
    _impact) so the two lists can be concatenated directly. Only
    High-volume underperformer sellers are mined as problems here - a
    Low-volume outlier is real but explicitly not high-priority (see the
    Status classification above), and Healthy/Typical sellers aren't findings."""
    bm = bm or compute_benchmark(c)
    gts = group_type_seller_table(c, bm=bm)
    problems = gts[gts["Status"] == "High-volume underperformer"].sort_values("Impact Score", ascending=False)

    rows = []
    for _, row in problems.head(top_n).iterrows():
        extra = int(round(row["Tickets"] * abs(row["RR vs Benchmark (pp)"])))
        priority = "High Priority" if row["RR vs Benchmark (pp)"] <= -HIGH_PRIORITY_DEVIATION_PP else "Medium Priority"
        rows.append({
            "Priority": priority, "Area": "Seller",
            "Owner / Segment": f"{row['Group']} -> {row['Type']} -> {row['SellerLabel']}",
            "Finding": f"{row['SellerLabel']} ({row['Group']} -> {row['Type']}) is a high-volume "
                       f"underperforming seller: {row['RR vs Benchmark (pp)'] * 100:+.1f}pp vs benchmark",
            "Evidence": f"{row['Tickets']:,} tickets, {row['Resolution Rate']:.1%} resolution rate vs "
                        f"{bm.resolution_rate:.1%} benchmark, {row['>24h']:,} tickets >24h TAT. "
                        f"Sales Person: {row['SalesPerson']} (Team: {row['Team']}).",
            "Impact": f"~{extra:,} tickets from this seller alone are backlogged beyond what the benchmark "
                      f"rate would predict.",
            "Recommended Action": "Pattern to investigate: this looks seller-specific (packaging, address "
                                   "quality, process) rather than rep-specific if the same Sales Person "
                                   "handles other healthy sellers in this segment - check the Group -> Type -> "
                                   "Seller view for that comparison before escalating to the rep.",
            "_impact": row["Impact Score"],
        })
    return pd.DataFrame(rows)


def seller_mapping_coverage(c: pd.DataFrame) -> dict:
    total = len(c)
    vc = c["MappingStatus"].value_counts()
    return {
        "total": total,
        "mapped": int(vc.get("Mapped", 0)),
        "unmapped_seller": int(vc.get("Unmapped Seller", 0)),
        "no_seller_id": int(vc.get("No Seller ID", 0)),
        "mapped_pct": vc.get("Mapped", 0) / total if total else 0.0,
    }

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

    # Seller Company Name is a per-Seller-ID attribute (from the optional LSQ
    # file) - mapped in separately rather than added to SELLER_KEYS, since a
    # groupby key with nulls (most sellers currently have no company name on
    # file) would silently drop those rows from the table.
    id_to_company = c.dropna(subset=["SellerID"]).drop_duplicates("SellerID").set_index("SellerID")["SellerCompanyName"]
    out["SellerCompanyName"] = out["SellerID"].map(id_to_company)

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

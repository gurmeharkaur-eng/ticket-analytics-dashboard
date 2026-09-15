"""All grouped/cut tables - the code equivalent of the Excel workbook's
Overall / Group / Type / Sales Person / Backlog & Ageing / TAT Analysis tabs.

Every function takes the computed per-ticket DataFrame (`calculations.compute`
output) and returns a plain pandas DataFrame shaped exactly like the
corresponding Excel table, so the UI layer can render it with minimal glue.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import AGE_BUCKETS, MOM_MONTHS_BACK, TAT_BUCKETS

DIM_TABLE_COLUMNS = [
    "Total Raised", "% of Total", "Open", "New", "Pending", "Re-Opened",
    "Total Backlog", "% Backlog", "Avg First Resp TAT", "Median First Resp TAT",
    "Avg Resolution TAT", "Median Resolution TAT",
]
STATUS_COLS = ["Open", "New", "Pending", "Re-Opened"]


def _status_counts(c: pd.DataFrame, by) -> pd.DataFrame:
    ct = pd.crosstab(by, c["Status"])
    for s in STATUS_COLS:
        if s not in ct.columns:
            ct[s] = 0
    return ct[STATUS_COLS]


def build_dim_table(c: pd.DataFrame, dim_col: str, order: list[str] | None = None,
                     total_denominator: int | None = None) -> pd.DataFrame:
    """The 12-metric table shape reused for Group / Type / Sales Person cuts."""
    by = c[dim_col]
    total = by.value_counts()
    status = _status_counts(c, by)
    backlog = c.groupby(by, observed=True)["Backlog"].sum()
    fr_avg = c.groupby(by, observed=True)["FRTAT"].mean()
    fr_med = c.groupby(by, observed=True)["FRTAT"].median()
    res_avg = c.groupby(by, observed=True)["RESTAT"].mean()
    res_med = c.groupby(by, observed=True)["RESTAT"].median()

    idx = order if order is not None else total.sort_values(ascending=False).index.tolist()
    out = pd.DataFrame(index=pd.Index(idx, name=dim_col))
    out["Total Raised"] = total.reindex(idx).fillna(0).astype(int)
    denom = total_denominator if total_denominator is not None else len(c)
    out["% of Total"] = out["Total Raised"] / denom if denom else 0.0
    for s in STATUS_COLS:
        out[s] = status.reindex(idx)[s].fillna(0).astype(int)
    out["Total Backlog"] = backlog.reindex(idx).fillna(0).astype(int)
    out["% Backlog"] = np.where(out["Total Raised"] > 0, out["Total Backlog"] / out["Total Raised"].replace(0, np.nan), 0.0)
    out["Avg First Resp TAT"] = fr_avg.reindex(idx)
    out["Median First Resp TAT"] = fr_med.reindex(idx)
    out["Avg Resolution TAT"] = res_avg.reindex(idx)
    out["Median Resolution TAT"] = res_med.reindex(idx)
    return out.reset_index().rename(columns={dim_col: dim_col})


def group_level_table(c: pd.DataFrame) -> pd.DataFrame:
    order = c["Group"].value_counts().index.tolist()
    return build_dim_table(c, "Group", order=order)


def group_type_combo_table(c: pd.DataFrame) -> pd.DataFrame:
    """Group x Type combinations (Type is NOT exclusive to one Group in this
    data - see Logic Validation - so the hierarchy is built on the combo,
    not on an assumed single parent Group per Type)."""
    group_order = c["Group"].value_counts().index.tolist()
    combo_counts = c.groupby(["Group", "Type"], observed=True).size().reset_index(name="n")
    combo_counts["_gord"] = combo_counts["Group"].map({g: i for i, g in enumerate(group_order)})
    combo_counts = combo_counts.sort_values(["_gord", "n"], ascending=[True, False])
    combo_order = list(zip(combo_counts["Group"], combo_counts["Type"]))

    by = list(zip(c["Group"], c["Type"]))
    by_series = pd.Series(by, index=c.index)
    group_totals = c["Group"].value_counts()

    rows = []
    status_ct = c.groupby([c["Group"], c["Type"], c["Status"]], observed=True).size()
    fr_avg = c.groupby(["Group", "Type"], observed=True)["FRTAT"].mean()
    fr_med = c.groupby(["Group", "Type"], observed=True)["FRTAT"].median()
    res_avg = c.groupby(["Group", "Type"], observed=True)["RESTAT"].mean()
    res_med = c.groupby(["Group", "Type"], observed=True)["RESTAT"].median()
    backlog = c.groupby(["Group", "Type"], observed=True)["Backlog"].sum()
    total = c.groupby(["Group", "Type"], observed=True).size()

    for g, t in combo_order:
        tot = int(total.get((g, t), 0))
        bl = int(backlog.get((g, t), 0))
        row = {
            "Group | Type": f"{g}  |  {t}",
            "Group": g, "Type": t,
            "Total Raised": tot,
            "% of Group": tot / group_totals[g] if group_totals[g] else 0.0,
            "Open": int(status_ct.get((g, t, "Open"), 0)),
            "New": int(status_ct.get((g, t, "New"), 0)),
            "Pending": int(status_ct.get((g, t, "Pending"), 0)),
            "Re-Opened": int(status_ct.get((g, t, "Re-Opened"), 0)),
            "Total Backlog": bl,
            "% Backlog": (bl / tot) if tot else 0.0,
            "Avg First Resp TAT": fr_avg.get((g, t), np.nan),
            "Median First Resp TAT": fr_med.get((g, t), np.nan),
            "Avg Resolution TAT": res_avg.get((g, t), np.nan),
            "Median Resolution TAT": res_med.get((g, t), np.nan),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def type_level_table(c: pd.DataFrame) -> pd.DataFrame:
    order = c["Type"].value_counts().index.tolist()
    return build_dim_table(c, "Type", order=order)


def type_primary_group(c: pd.DataFrame) -> pd.DataFrame:
    """For each Type, the single Group contributing the most tickets to it,
    and whether it also occurs under other Groups."""
    combo = c.groupby(["Type", "Group"], observed=True).size().reset_index(name="n")
    combo = combo.sort_values(["Type", "n"], ascending=[True, False])
    primary = combo.drop_duplicates("Type")
    groups_per_type = combo.groupby("Type")["Group"].nunique()
    type_order = c["Type"].value_counts().index.tolist()

    rows = []
    for t in type_order:
        row = primary[primary["Type"] == t].iloc[0]
        rows.append({
            "Type": t,
            "Primary Group": row["Group"],
            "Tickets from Primary Group": int(row["n"]),
            "Spans Other Groups Too?": "Yes" if groups_per_type[t] > 1 else "No",
        })
    return pd.DataFrame(rows)


def sales_person_table(c: pd.DataFrame, reps: list[str]) -> pd.DataFrame:
    pseudo = ["No Seller ID", "Unmapped Seller", "Unassigned Rep"]
    order = reps + pseudo
    return build_dim_table(c, "SalesPerson", order=order)


def status_distribution(c: pd.DataFrame) -> pd.DataFrame:
    vc = c["Status"].value_counts()
    total = len(c)
    df = vc.rename_axis("Status").reset_index(name="Ticket Count")
    df["% of Total"] = df["Ticket Count"] / total if total else 0.0
    other = total - df["Ticket Count"].sum()
    if other:
        df.loc[len(df)] = ["Other / not in list above (reconciliation)", other, other / total if total else 0.0]
    return df


def backlog_summary(c: pd.DataFrame) -> pd.DataFrame:
    bl = c[c["Backlog"] == 1]
    vc = bl["Status"].value_counts()
    total_backlog = len(bl)
    df = vc.rename_axis("Status").reset_index(name="Ticket Count")
    df["% of Backlog"] = df["Ticket Count"] / total_backlog if total_backlog else 0.0
    df = df.sort_values("Status")
    df.loc[len(df)] = ["TOTAL BACKLOG", total_backlog, 1.0]
    return df


def month_on_month(c: pd.DataFrame, as_of: pd.Timestamp, months_back: int = MOM_MONTHS_BACK) -> pd.DataFrame:
    anchor = pd.Timestamp(year=as_of.year, month=as_of.month, day=1)
    months = [anchor - pd.DateOffset(months=k) for k in range(months_back - 1, -1, -1)]
    rows = []
    prev_total = None
    for m in months:
        key = m.strftime("%Y-%m")
        sub = c[c["MonthSort"] == key]
        total = len(sub)
        vc = sub["Status"].value_counts()
        row = {"Month": m.strftime("%b-%Y"), "Total": total}
        for s in ["New", "Open", "Pending", "Re-Opened", "Closed", "Resolved", "Waiting on Customer"]:
            row[s] = int(vc.get(s, 0))
        row["Total Backlog"] = int(sub["Backlog"].sum())
        row["Backlog %"] = row["Total Backlog"] / total if total else 0.0
        row["MoM Ticket Change"] = None if prev_total is None else total - prev_total
        row["MoM Ticket %"] = None if not prev_total else (total / prev_total - 1)
        prev_total = total
        rows.append(row)
    return pd.DataFrame(rows)


def overall_ageing(c: pd.DataFrame) -> pd.DataFrame:
    bl = c[c["Backlog"] == 1]
    total_backlog = len(bl)
    vc = bl["AgeBucket"].value_counts()
    rows = [{"Ageing Bucket": b, "Ticket Count": int(vc.get(b, 0)),
             "% of Total Backlog": (vc.get(b, 0) / total_backlog) if total_backlog else 0.0} for b in AGE_BUCKETS]
    rows.append({"Ageing Bucket": "TOTAL BACKLOG", "Ticket Count": total_backlog, "% of Total Backlog": 1.0})
    return pd.DataFrame(rows)


def status_x_ageing(c: pd.DataFrame) -> pd.DataFrame:
    bl = c[c["Backlog"] == 1]
    rows = []
    for s in ["Open", "New", "Pending", "Re-Opened"]:
        sub = bl[bl["Status"] == s]
        vc = sub["AgeBucket"].value_counts()
        row = {"Status": s}
        for b in AGE_BUCKETS:
            row[b] = int(vc.get(b, 0))
        row["Total Backlog"] = len(sub)
        rows.append(row)
    return pd.DataFrame(rows)


def _dim_x_ageing(c: pd.DataFrame, dim_col: str) -> pd.DataFrame:
    bl = c[c["Backlog"] == 1]
    order = bl[dim_col].value_counts().index.tolist()
    rows = []
    for d in order:
        sub = bl[bl[dim_col] == d]
        vc = sub["AgeBucket"].value_counts()
        row = {dim_col: d}
        for b in AGE_BUCKETS:
            row[b] = int(vc.get(b, 0))
        row["Total Backlog"] = len(sub)
        row["Oldest (days)"] = sub["AgeDays"].max() if len(sub) else 0.0
        row["Avg Age (days)"] = sub["AgeDays"].mean() if len(sub) else 0.0
        rows.append(row)
    return pd.DataFrame(rows)


def group_x_ageing(c: pd.DataFrame) -> pd.DataFrame:
    return _dim_x_ageing(c, "Group")


def type_x_ageing(c: pd.DataFrame) -> pd.DataFrame:
    return _dim_x_ageing(c, "Type")


def backlog_contribution_ranking(c: pd.DataFrame, dim_col: str) -> pd.DataFrame:
    bl = c[c["Backlog"] == 1]
    total_backlog = len(bl)
    vc = bl[dim_col].value_counts()
    df = vc.rename_axis(dim_col).reset_index(name="Total Backlog")
    df["% of Total Backlog"] = df["Total Backlog"] / total_backlog if total_backlog else 0.0
    df["Cumulative %"] = df["% of Total Backlog"].cumsum()
    return df


def tat_bucket_table(c: pd.DataFrame, bucket_col: str) -> pd.DataFrame:
    tat_col = "FRTAT" if bucket_col == "FRBucket" else "RESTAT"
    valid = c[tat_col].notna().sum()
    vc = c[bucket_col].value_counts()
    rows = [{"Bucket": b, "Ticket Count": int(vc.get(b, 0)),
             "% of Valid TAT Tickets": (vc.get(b, 0) / valid) if valid else 0.0} for b in TAT_BUCKETS]
    rows.append({"Bucket": "VALID TAT TICKETS", "Ticket Count": int(valid), "% of Valid TAT Tickets": 1.0})
    return pd.DataFrame(rows)


def tat_bucket_by_dim(c: pd.DataFrame, dim_col: str, bucket_col: str, order: list[str]) -> pd.DataFrame:
    ct = pd.crosstab(c[dim_col], c[bucket_col])
    for b in TAT_BUCKETS:
        if b not in ct.columns:
            ct[b] = 0
    ct = ct[TAT_BUCKETS].reindex(order).fillna(0).astype(int)
    ct["Valid TAT Count"] = ct.sum(axis=1)
    return ct.reset_index().rename(columns={dim_col: dim_col})

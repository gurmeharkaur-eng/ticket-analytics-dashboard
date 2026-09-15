"""Automatic reconciliation checks - the code equivalent of the Excel
workbook's Data Quality tab. Every 'Diff' should read 0.
"""
from __future__ import annotations

import pandas as pd

from src.aggregations import (
    group_level_table, group_type_combo_table, sales_person_table,
    status_distribution, tat_bucket_table, overall_ageing, type_level_table,
)


def ticket_total_reconciliation(c: pd.DataFrame, reps: list[str]) -> pd.DataFrame:
    total = len(c)
    checks = [
        ("Sum of Groups vs Overall Total", group_level_table(c)["Total Raised"].sum() - total),
        ("Sum of Group x Type combos vs Overall Total", group_type_combo_table(c)["Total Raised"].sum() - total),
        ("Sum of Types vs Overall Total", type_level_table(c)["Total Raised"].sum() - total),
        ("Sum of Sales Persons (incl. unmapped categories) vs Overall Total",
         sales_person_table(c, reps)["Total Raised"].sum() - total),
        ("Sum of Status categories vs Overall Total", status_distribution(c)["Ticket Count"].sum() - total),
    ]
    return pd.DataFrame(checks, columns=["Check", "Diff (should be 0)"])


def backlog_tat_reconciliation(c: pd.DataFrame) -> pd.DataFrame:
    backlog_flag_sum = int(c["Backlog"].sum())
    status_backlog = c["Status"].isin(["Open", "New", "Pending", "Re-Opened"]).sum()
    fr_bucket_sum = tat_bucket_table(c, "FRBucket")["Ticket Count"].iloc[:-1].sum()
    res_bucket_sum = tat_bucket_table(c, "RESBucket")["Ticket Count"].iloc[:-1].sum()
    age_bucket_sum = overall_ageing(c)["Ticket Count"].iloc[:-1].sum()

    checks = [
        ("Backlog (Open+New+Pending+Re-Opened) vs SUM(Backlog Flag)", int(status_backlog) - backlog_flag_sum),
        ("Sum of First Response TAT buckets vs Valid FR TAT count", int(fr_bucket_sum) - int(c["FRTAT"].notna().sum())),
        ("Sum of Resolution TAT buckets vs Valid Resolution TAT count", int(res_bucket_sum) - int(c["RESTAT"].notna().sum())),
        ("Sum of Overall Ageing buckets vs Total Backlog", int(age_bucket_sum) - backlog_flag_sum),
    ]
    df = pd.DataFrame(checks, columns=["Check", "Diff (should be 0)"])
    return df


def excluded_tat_counts(raw: pd.DataFrame) -> pd.DataFrame:
    from config import COL_CREATED, COL_INITIAL_RESPONSE, COL_RESOLVED
    fr = (raw[COL_INITIAL_RESPONSE] - raw[COL_CREATED]).dt.total_seconds() / 3600
    res = (raw[COL_RESOLVED] - raw[COL_CREATED]).dt.total_seconds() / 3600
    rows = [
        ("Negative First Response TAT values found & excluded", int((fr < 0).sum())),
        ("Negative Resolution TAT values found & excluded", int((res < 0).sum())),
    ]
    return pd.DataFrame(rows, columns=["Check", "Count"])


def duplicate_ticket_ids(c: pd.DataFrame) -> int:
    return int(c["Ticket ID"].duplicated().sum())


def missing_field_rates(c: pd.DataFrame) -> pd.DataFrame:
    total = len(c)
    rows = [
        ("Type (blank -> shown as 'Unknown')", int((c["Type"] == "Unknown").sum())),
        ("Group (blank -> shown as 'No Group')", int((c["Group"] == "No Group").sum())),
        ("Seller ID (ticket has none)", int((c["MappingStatus"] == "No Seller ID").sum())),
        ("Seller ID present but not found in Sales Mapping", int((c["MappingStatus"] == "Unmapped Seller").sum())),
        ("Initial Response Time missing or invalid (First Response TAT not computable)", int(total - c["FRTAT"].notna().sum())),
        ("Resolved Time missing or invalid (Resolution TAT not computable)", int(total - c["RESTAT"].notna().sum())),
    ]
    df = pd.DataFrame(rows, columns=["Field", "Missing / Blank"])
    df["% of Total Tickets"] = df["Missing / Blank"] / total if total else 0.0
    return df


def mapping_validation(mapping: pd.DataFrame, c: pd.DataFrame) -> pd.DataFrame:
    unique_sellers = len(mapping)
    with_rep = int(mapping["_sales_person_norm"].notna().sum())
    dup_ids = int(mapping["_seller_id_num"].duplicated().sum())
    rows = [
        ("Unique sellers in mapping sheet", unique_sellers),
        ("Sellers with a Sales Person assigned", with_rep),
        ("Sellers with NO Sales Person assigned (blank rep)", unique_sellers - with_rep),
        ("Duplicate Seller IDs found in mapping sheet (auto-check)", dup_ids),
        ("Tickets with no Seller ID at all", int((c["MappingStatus"] == "No Seller ID").sum())),
        ("Tickets whose Seller ID is not in the mapping sheet", int((c["MappingStatus"] == "Unmapped Seller").sum())),
        ("Tickets successfully mapped to a Sales Person", int((c["MappingStatus"] == "Mapped").sum())),
    ]
    return pd.DataFrame(rows, columns=["Metric", "Value"])

"""Per-ticket computed fields - the code equivalent of the Excel workbook's
'Computed' helper sheet. Every downstream table in aggregations.py and
insights.py is built from the DataFrame returned by `compute()`, never from
the raw file directly, mirroring how every Excel analysis tab reads from
Computed rather than Raw Data.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from config import (
    AGE_BUCKETS, AGE_BUCKET_BOUNDS, BACKLOG_STATUSES, COL_CREATED, COL_GROUP,
    COL_INITIAL_RESPONSE, COL_RESOLVED, COL_SELLER_ID, COL_STATUS, COL_TICKET_ID,
    COL_TYPE, MAP_SALES_PERSON, TAT_BUCKETS, TAT_BUCKET_BOUNDS,
)


def _bucket(hours: pd.Series, bounds: list[float], labels: list[str]) -> pd.Series:
    """Upper-bound-inclusive bucketing; NaN input -> NaN output (excluded)."""
    out = pd.Series(pd.array([None] * len(hours), dtype="string"), index=hours.index)
    valid = hours.notna()
    edges = [-np.inf] + bounds + [np.inf]
    cut = pd.cut(hours[valid], bins=edges, labels=labels, right=True)
    out.loc[valid] = cut.astype(str)
    return out


def as_of_date(created: pd.Series) -> pd.Timestamp:
    """End-of-day of the latest Created time in the loaded raw data - never a
    hardcoded date, so ageing recalculates correctly on every upload."""
    latest = created.max()
    return pd.Timestamp(latest).normalize() + pd.Timedelta(hours=23, minutes=59, seconds=59)


def _classify_sales_person(seller_id_num: pd.Series, mapping: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Returns (mapping_status, sales_person) Series.

    mapping_status in {"No Seller ID", "Unmapped Seller", "Mapped"}.
    sales_person is the rep's normalized name, or "Unassigned Rep" for a
    mapped seller with no rep on file, or mirrors mapping_status's label for
    the two unmapped cases (so it can be used directly as one dimension).
    """
    id_to_person = dict(zip(mapping["_seller_id_num"], mapping["_sales_person_norm"]))
    known_ids = set(mapping["_seller_id_num"])

    mapping_status = pd.Series("Mapped", index=seller_id_num.index, dtype="object")
    mapping_status[seller_id_num.isna()] = "No Seller ID"
    mapping_status[seller_id_num.notna() & ~seller_id_num.isin(known_ids)] = "Unmapped Seller"

    sales_person = seller_id_num.map(id_to_person)
    sales_person = sales_person.where(sales_person.notna(), "Unassigned Rep")
    sales_person = sales_person.where(mapping_status == "Mapped", mapping_status)
    return mapping_status, sales_person


@dataclass
class ComputedData:
    df: pd.DataFrame
    as_of: pd.Timestamp


def compute(raw: pd.DataFrame, mapping: pd.DataFrame) -> ComputedData:
    n = len(raw)
    c = pd.DataFrame(index=raw.index)

    c["Ticket ID"] = raw[COL_TICKET_ID]
    c["Created"] = raw[COL_CREATED]
    c["Month"] = c["Created"].dt.strftime("%b-%Y")
    c["MonthSort"] = c["Created"].dt.strftime("%Y-%m")
    c["Group"] = raw[COL_GROUP].fillna("No Group").astype(str).str.strip().replace("", "No Group")
    c["Type"] = raw[COL_TYPE].fillna("Unknown").astype(str).str.strip().replace("", "Unknown")
    c["Status"] = raw[COL_STATUS].astype(str).str.strip()

    seller_id_num = pd.to_numeric(raw[COL_SELLER_ID], errors="coerce")
    c["SellerID"] = seller_id_num
    c["MappingStatus"], c["SalesPerson"] = _classify_sales_person(seller_id_num, mapping)

    fr_hours = (raw[COL_INITIAL_RESPONSE] - raw[COL_CREATED]).dt.total_seconds() / 3600
    fr_hours = fr_hours.where(fr_hours >= 0)  # negative TAT excluded, not zeroed
    res_hours = (raw[COL_RESOLVED] - raw[COL_CREATED]).dt.total_seconds() / 3600
    res_hours = res_hours.where(res_hours >= 0)
    c["FRTAT"] = fr_hours
    c["RESTAT"] = res_hours
    c["FRBucket"] = _bucket(fr_hours, TAT_BUCKET_BOUNDS, TAT_BUCKETS)
    c["RESBucket"] = _bucket(res_hours, TAT_BUCKET_BOUNDS, TAT_BUCKETS)

    status_norm = c["Status"].str.upper().str.strip()
    c["Backlog"] = status_norm.isin(BACKLOG_STATUSES).astype(int)

    asof = as_of_date(raw[COL_CREATED])
    age_days = (asof - c["Created"]).dt.total_seconds() / 86400
    c["AgeDays"] = age_days.where(c["Backlog"] == 1)
    c["AgeBucket"] = _bucket(c["AgeDays"], AGE_BUCKET_BOUNDS, AGE_BUCKETS)

    c["Duplicate"] = c["Ticket ID"].duplicated(keep=False).astype(int)

    return ComputedData(df=c, as_of=asof)

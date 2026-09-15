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
    AGE_BUCKETS, AGE_BUCKET_BOUNDS, BACKLOG_STATUSES, COL_CREATED, COL_DUE_BY, COL_GROUP,
    COL_INITIAL_RESPONSE, COL_RESOLVED, COL_SELLER_ID, COL_STATUS, COL_SURVEY, COL_TICKET_ID,
    COL_TYPE, LSQ_COMPANY_NAME, LSQ_SELLER_NAME, MAP_SELLER_NAME, NO_TEAM_LABEL, TAT_BUCKETS,
    TAT_BUCKET_BOUNDS,
)


SUNDAY_WEEKMASK = "1111110"  # numpy weekmask order: Mon Tue Wed Thu Fri Sat Sun - Sunday is the only day off


def _business_hours_elapsed(start: pd.Series, end: pd.Series) -> pd.Series:
    """Elapsed hours from start to end, excluding Sunday (the only
    non-working day) entirely - every Sunday hour is excluded regardless of
    where in the interval it falls:
      - if `start` itself falls on a Sunday, the effective start moves to
        the following Monday 00:00:00 - the SLA clock doesn't start until a
        working day.
      - any Sunday(s) FULLY spanned between start and end are excluded (a
        full 24h removed per Sunday calendar date overlapped, using numpy's
        business-day counting with Sunday as the only day off).
      - if `end` itself falls on a Sunday (the ticket was responded to /
        resolved ON a Sunday), the hours from that Sunday's 00:00:00 up to
        `end` are excluded too - np.busday_count treats its end argument as
        exclusive, so a Sunday that IS the end date is never counted by the
        "fully spanned" logic above and needs this separate term, otherwise
        those hours would silently leak into the TAT.
    Negative or NaN results are left as-is for the caller to exclude, same
    as the plain calendar-elapsed calculation."""
    valid = start.notna() & end.notna()
    eff_start = start.copy()
    is_sun = start.dt.dayofweek == 6  # Monday=0 ... Sunday=6
    eff_start[is_sun & valid] = start[is_sun & valid].dt.normalize() + pd.Timedelta(days=1)

    raw_hours = (end - eff_start).dt.total_seconds() / 3600

    start_dates = eff_start.dt.normalize().values.astype("datetime64[D]")
    end_dates = end.dt.normalize().values.astype("datetime64[D]")
    # np.busday_count requires begin <= end; same-day or invalid rows are
    # masked out via `valid` anyway, but guard against a negative range
    # blowing up busday_count by clipping end to start where it's smaller.
    clipped_end = np.where(end_dates >= start_dates, end_dates, start_dates)
    total_days = (clipped_end - start_dates).astype("timedelta64[D]").astype(int)
    working_days = np.busday_count(start_dates, clipped_end, weekmask=SUNDAY_WEEKMASK)
    sundays_spanned = total_days - working_days

    # Partial Sunday AT THE END: eff_start is guaranteed never on a Sunday
    # (handled above), so the only Sunday that can be only PARTIALLY inside
    # the interval is the one containing `end` itself - subtract just the
    # hours from that Sunday's midnight up to the actual end time.
    end_is_sun = end.dt.dayofweek == 6
    sunday_partial_hours = pd.Series(0.0, index=start.index)
    sunday_partial_hours[end_is_sun & valid] = (
        end[end_is_sun & valid] - end[end_is_sun & valid].dt.normalize()
    ).dt.total_seconds() / 3600

    business_hours = raw_hours - sundays_spanned * 24 - sunday_partial_hours
    return pd.Series(business_hours, index=start.index).where(valid)


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


def _resolve_ownership(seller_id_num: pd.Series, mapping: pd.DataFrame,
                        team_data: pd.DataFrame | None, team_lists: pd.DataFrame | None,
                        lsq_data: pd.DataFrame | None = None
                        ) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """Returns (mapping_status, sales_person, team, seller_name, seller_company_name) Series.

    Sales Person / Team resolution priority per Seller ID:
      1. Team Level Data (seller Id -> Sales Person, Team) - the more
         complete, more current source.
      2. The plain Sales Mapping file (Seller ID -> Sales Person) - used
         where Team Level Data doesn't cover a seller. It carries no Team,
         so Team then falls back to the Team Lists roster (Sales Person ->
         Team) if that person is on it, else "No Team Info".
      3. Neither source has the Seller ID -> "Unmapped Seller".

    Seller Name priority: the Sales Mapping file's name first, then the
    optional LSQ Seller Data file's name where the mapping file has none -
    LSQ covers a different (mostly non-overlapping) set of Seller IDs, so it
    fills real gaps rather than overriding a curated name. Seller Company
    Name has no other source and comes from LSQ alone, shown as its own
    field, never folded into Seller Name.

    mapping_status in {"No Seller ID", "Unmapped Seller", "Mapped"}. Both
    sales_person and team mirror mapping_status's label for the two unmapped
    cases, so either can be used directly as one dimension.
    """
    id_to_name = dict(zip(mapping["_seller_id_num"], mapping[MAP_SELLER_NAME]))
    id_to_person_old = dict(zip(mapping["_seller_id_num"], mapping["_sales_person_norm"]))
    known_ids = set(mapping["_seller_id_num"])

    id_to_person_td: dict = {}
    id_to_team_td: dict = {}
    if team_data is not None:
        id_to_person_td = dict(zip(team_data["_seller_id_num"], team_data["_sales_person_norm"]))
        id_to_team_td = dict(zip(team_data["_seller_id_num"], team_data["_team_norm"]))
        known_ids = known_ids | set(team_data["_seller_id_num"])

    person_to_team_list: dict = {}
    if team_lists is not None:
        person_to_team_list = dict(zip(team_lists["_sales_person_norm"], team_lists["_team_norm"]))

    id_to_lsq_name: dict = {}
    id_to_lsq_company: dict = {}
    if lsq_data is not None:
        id_to_lsq_name = dict(zip(lsq_data["_seller_id_num"], lsq_data[LSQ_SELLER_NAME]))
        id_to_lsq_company = dict(zip(lsq_data["_seller_id_num"], lsq_data[LSQ_COMPANY_NAME]))

    mapping_status = pd.Series("Mapped", index=seller_id_num.index, dtype="object")
    mapping_status[seller_id_num.isna()] = "No Seller ID"
    mapping_status[seller_id_num.notna() & ~seller_id_num.isin(known_ids)] = "Unmapped Seller"

    sp_from_team_data = seller_id_num.map(id_to_person_td)
    sp_from_mapping = seller_id_num.map(id_to_person_old)
    sales_person = sp_from_team_data.where(sp_from_team_data.notna(), sp_from_mapping)
    sales_person = sales_person.where(sales_person.notna(), "Unassigned Rep")
    sales_person = sales_person.where(mapping_status == "Mapped", mapping_status)

    team_from_team_data = seller_id_num.map(id_to_team_td)
    team_from_roster = sales_person.map(person_to_team_list)
    team = team_from_team_data.where(team_from_team_data.notna(), team_from_roster)
    team = team.where(team.notna(), NO_TEAM_LABEL)
    team = team.where(mapping_status == "Mapped", mapping_status)

    seller_name = seller_id_num.map(id_to_name)
    seller_name_lsq = seller_id_num.map(id_to_lsq_name)
    seller_name = seller_name.where(seller_name.notna(), seller_name_lsq)
    seller_company_name = seller_id_num.map(id_to_lsq_company)
    return mapping_status, sales_person, team, seller_name, seller_company_name


@dataclass
class ComputedData:
    df: pd.DataFrame
    as_of: pd.Timestamp


def compute(raw: pd.DataFrame, mapping: pd.DataFrame, team_data: pd.DataFrame | None = None,
            team_lists: pd.DataFrame | None = None, lsq_data: pd.DataFrame | None = None) -> ComputedData:
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
    c["MappingStatus"], c["SalesPerson"], c["Team"], c["SellerName"], c["SellerCompanyName"] = _resolve_ownership(
        seller_id_num, mapping, team_data, team_lists, lsq_data)
    c["SellerLabel"] = c["SellerName"].where(
        c["SellerName"].notna(), seller_id_num.apply(lambda x: f"Seller {int(x)}" if pd.notna(x) else None))
    c["SellerLabel"] = c["SellerLabel"].where(c["SellerLabel"].notna(), c["MappingStatus"])

    # Business-day TAT: Sunday is a non-working day (see
    # _business_hours_elapsed) - a ticket created on Sunday has its clock
    # start pushed to Monday 00:00:00, and any Sunday the response/resolution
    # window spans is excluded from the elapsed-hours count. This replaces
    # plain calendar-elapsed time everywhere TAT is used (buckets, averages,
    # medians, benchmarks) - Backlog Age (how long a ticket has been
    # waiting) is unaffected and stays pure calendar time, since that's about
    # elapsed wait, not work capacity.
    fr_hours = _business_hours_elapsed(raw[COL_CREATED], raw[COL_INITIAL_RESPONSE])
    fr_hours = fr_hours.where(fr_hours >= 0)  # negative TAT excluded, not zeroed
    res_hours = _business_hours_elapsed(raw[COL_CREATED], raw[COL_RESOLVED])
    res_hours = res_hours.where(res_hours >= 0)
    c["FRTAT"] = fr_hours
    c["RESTAT"] = res_hours
    c["FRBucket"] = _bucket(fr_hours, TAT_BUCKET_BOUNDS, TAT_BUCKETS)
    c["RESBucket"] = _bucket(res_hours, TAT_BUCKET_BOUNDS, TAT_BUCKETS)

    status_norm = c["Status"].str.upper().str.strip()
    c["Backlog"] = status_norm.isin(BACKLOG_STATUSES).astype(int)

    # Resolved-in-TAT: whether a ticket was resolved by its own per-ticket SLA
    # deadline (Due by Time), not a flat hour cutoff. Verified against the raw
    # 'Resolution status' field (100% agreement on 7,297 resolved tickets with
    # both timestamps present) - see Logic Validation. NaN (not "") for
    # tickets that aren't resolved yet, so it's excluded from rate
    # calculations the same way FRTAT/RESTAT are.
    if COL_DUE_BY in raw.columns:
        resolved_present = raw[COL_RESOLVED].notna()
        due_present = raw[COL_DUE_BY].notna()
        in_tat = pd.Series(np.nan, index=raw.index, dtype="float64")
        both = resolved_present & due_present
        in_tat[both] = (raw.loc[both, COL_RESOLVED] <= raw.loc[both, COL_DUE_BY]).astype(float)
        c["InTAT"] = in_tat
    else:
        c["InTAT"] = np.nan

    # CSAT: parsed from the trailing "(Positive/Neutral/Negative)" label in
    # the raw 'Survey results' text (e.g. "5 (Positive)"), not the leading
    # numeric score, since Freshdesk's own numeric-to-sentiment mapping can
    # vary by survey configuration - the text label is unambiguous.
    if COL_SURVEY in raw.columns:
        survey = raw[COL_SURVEY].astype("string")
        c["SurveySentiment"] = survey.str.extract(r"\((Positive|Neutral|Negative)\)", expand=False)
    else:
        c["SurveySentiment"] = pd.Series(pd.array([None] * n, dtype="string"), index=raw.index)

    asof = as_of_date(raw[COL_CREATED])
    age_days = (asof - c["Created"]).dt.total_seconds() / 86400
    c["AgeDays"] = age_days.where(c["Backlog"] == 1)
    c["AgeBucket"] = _bucket(c["AgeDays"], AGE_BUCKET_BOUNDS, AGE_BUCKETS)

    c["Duplicate"] = c["Ticket ID"].duplicated(keep=False).astype(int)

    return ComputedData(df=c, as_of=asof)

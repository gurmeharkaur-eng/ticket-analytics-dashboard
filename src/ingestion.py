"""Load and lightly validate the input files: raw ticket export, Seller ->
Sales Person mapping, and (optionally) the two team-ownership files. Accepts
.csv or .xlsx for any of them.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import pandas as pd

from config import (
    COL_CREATED, COL_INITIAL_RESPONSE, COL_RESOLVED, COL_SELLER_ID,
    MAP_SALES_PERSON, MAP_SELLER_ID, MAP_SELLER_NAME,
    REQUIRED_RAW_COLUMNS, RECOMMENDED_RAW_COLUMNS,
    TEAM_DATA_MONTH, TEAM_DATA_MONTH_ORDER, TEAM_DATA_SALES_PERSON, TEAM_DATA_SELLER_ID,
    TEAM_DATA_TEAM, TEAM_LIST_SALES_PERSON, TEAM_LIST_TEAM, TEAM_NAME_CANONICAL,
)

DATETIME_COLUMNS = [COL_CREATED, "Due by Time", COL_RESOLVED, "Closed time",
                    "Last update time", COL_INITIAL_RESPONSE]


def norm_name(x) -> str | None:
    """Title-case, trimmed person name - the single normalization used
    everywhere a person's name is compared or grouped, so 'Astha jain' and
    'Astha Jain' from different source files merge into one person."""
    if not isinstance(x, str) or not x.strip() or x.strip().lower() == "nan":
        return None
    return " ".join(w.capitalize() for w in x.strip().split())


def norm_team(x) -> str | None:
    if not isinstance(x, str) or not x.strip() or x.strip().lower() == "nan":
        return None
    x = x.strip()
    return TEAM_NAME_CANONICAL.get(x.upper(), x)


@dataclass
class LoadResult:
    raw: pd.DataFrame
    mapping: pd.DataFrame
    team_data: pd.DataFrame | None = None
    team_lists: pd.DataFrame | None = None
    warnings: list[str] = field(default_factory=list)


def _read_any(source, **kwargs) -> pd.DataFrame:
    """Read a CSV or XLSX from a path, UploadedFile, or bytes buffer."""
    name = getattr(source, "name", None) or str(source)
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    if str(name).lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(source, **kwargs)
    return pd.read_csv(source, low_memory=False, **kwargs)


def load_raw_tickets(source) -> pd.DataFrame:
    df = _read_any(source)
    df.columns = [str(c).strip() for c in df.columns]

    missing_required = [c for c in REQUIRED_RAW_COLUMNS if c not in df.columns]
    if missing_required:
        raise ValueError(
            "Raw ticket file is missing required column(s): " + ", ".join(missing_required)
            + ". Expected a Freshdesk-style export with headers matching the reference workbook."
        )
    for c in RECOMMENDED_RAW_COLUMNS:
        if c not in df.columns:
            df[c] = pd.NA

    for c in DATETIME_COLUMNS:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")

    return df


def load_seller_mapping(source) -> pd.DataFrame:
    df = _read_any(source)
    df.columns = [str(c).strip() for c in df.columns]

    missing = [c for c in (MAP_SELLER_ID, MAP_SALES_PERSON) if c not in df.columns]
    if missing:
        raise ValueError(
            "Sales mapping file is missing required column(s): " + ", ".join(missing)
        )
    if MAP_SELLER_NAME not in df.columns:
        df[MAP_SELLER_NAME] = pd.NA

    df["_seller_id_num"] = pd.to_numeric(df[MAP_SELLER_ID], errors="coerce")
    df[MAP_SELLER_NAME] = df[MAP_SELLER_NAME].astype("string").str.strip()
    df[MAP_SALES_PERSON] = df[MAP_SALES_PERSON].astype("string").str.strip()
    df["_sales_person_norm"] = df[MAP_SALES_PERSON].apply(norm_name)

    total_rows = len(df)
    df = df.dropna(subset=["_seller_id_num"]).drop_duplicates("_seller_id_num", keep="first").reset_index(drop=True)
    dedup_meta = {"raw_rows": total_rows, "unique_sellers": len(df)}
    df.attrs["dedup_meta"] = dedup_meta
    return df


def load_team_lists(source) -> pd.DataFrame:
    """Sales Person -> Team roster (one row per person)."""
    df = _read_any(source)
    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in (TEAM_LIST_SALES_PERSON, TEAM_LIST_TEAM) if c not in df.columns]
    if missing:
        raise ValueError("Team Lists file is missing required column(s): " + ", ".join(missing))
    df["_sales_person_norm"] = df[TEAM_LIST_SALES_PERSON].apply(norm_name)
    df["_team_norm"] = df[TEAM_LIST_TEAM].apply(norm_team)
    df = df.dropna(subset=["_sales_person_norm"]).drop_duplicates("_sales_person_norm", keep="first").reset_index(drop=True)
    return df


def load_team_level_data(source) -> pd.DataFrame:
    """Seller ID -> Sales Person -> Team -> Owner/KAM Person, keyed by seller.
    More complete and more current than the plain Sales Mapping file, so it
    is preferred wherever it covers a Seller ID."""
    df = _read_any(source)
    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in (TEAM_DATA_SELLER_ID, TEAM_DATA_SALES_PERSON) if c not in df.columns]
    if missing:
        raise ValueError("Team Level Data file is missing required column(s): " + ", ".join(missing))

    df["_seller_id_num"] = pd.to_numeric(df[TEAM_DATA_SELLER_ID], errors="coerce")
    df["_sales_person_norm"] = df[TEAM_DATA_SALES_PERSON].apply(norm_name)
    if TEAM_DATA_TEAM in df.columns:
        df["_team_norm"] = df[TEAM_DATA_TEAM].apply(norm_team)
    else:
        df["_team_norm"] = None

    if TEAM_DATA_MONTH in df.columns:
        order = {m: i for i, m in enumerate(TEAM_DATA_MONTH_ORDER)}
        df["_month_rank"] = df[TEAM_DATA_MONTH].map(order).fillna(-1)
    else:
        df["_month_rank"] = 0

    total_rows = len(df)
    df = df.dropna(subset=["_seller_id_num"])
    conflicts = int(df["_seller_id_num"].duplicated(keep=False).sum())
    # Keep the most recent month's assignment per Seller ID; ties keep the
    # last row encountered (stable order from the source file).
    df = df.sort_values(["_seller_id_num", "_month_rank"]).drop_duplicates("_seller_id_num", keep="last").reset_index(drop=True)
    df.attrs["dedup_meta"] = {"raw_rows": total_rows, "unique_sellers": len(df), "conflicting_rows": conflicts}
    return df


def load_all(raw_source, mapping_source, team_data_source=None, team_lists_source=None) -> LoadResult:
    warnings: list[str] = []
    raw = load_raw_tickets(raw_source)
    mapping = load_seller_mapping(mapping_source)

    team_data = None
    if team_data_source is not None:
        try:
            team_data = load_team_level_data(team_data_source)
        except Exception as e:
            warnings.append(f"Team Level Data could not be read and was skipped: {e}")

    team_lists = None
    if team_lists_source is not None:
        try:
            team_lists = load_team_lists(team_lists_source)
        except Exception as e:
            warnings.append(f"Team Lists could not be read and was skipped: {e}")

    dup_ids = raw[raw.columns[0]].duplicated().sum() if len(raw.columns) else 0
    if dup_ids:
        warnings.append(f"{dup_ids} duplicate Ticket ID(s) found in the raw file - see Data Quality tab.")

    return LoadResult(raw=raw, mapping=mapping, team_data=team_data, team_lists=team_lists, warnings=warnings)
